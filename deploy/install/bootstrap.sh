#!/usr/bin/env bash
# Первичная настройка сервера journal_bot (Debian 13 trixie, x86-64-v1).
#
# Запуск от root:   ADMIN_USER=george bash bootstrap.sh
# Повторный запуск безопасен (идемпотентно), кроме раздела SSH:
#   DISABLE_PASSWORD=0 (по умолчанию) — парольный вход остаётся, ключ добавляется;
#   DISABLE_PASSWORD=1 — парольный вход выключается (запускать ПОСЛЕ проверки ключа).
#
# Что делает: см. deploy/install/README.md §7.

set -euo pipefail

ADMIN_USER="${ADMIN_USER:-${SUDO_USER:-george}}"
DISABLE_PASSWORD="${DISABLE_PASSWORD:-0}"
# Ключ администратора (публичный, не секрет). Можно переопределить через PUBKEY.
PUBKEY="${PUBKEY:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEch1DUTefqjTwz8BB3fktOSFbnm2zy+FNwXUG3+gZx8 journal-server-agent}"

log() { printf '\n\033[1;32m== %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m!! %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запускать от root: sudo ADMIN_USER=<логин> bash bootstrap.sh"
id "$ADMIN_USER" >/dev/null 2>&1 || die "пользователя '$ADMIN_USER' нет"

export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)

log "0. Проверка железа"
if grep -q sse4_2 /proc/cpuinfo; then
  echo "  sse4_2 есть — процессор новее K10, это нормально"
else
  echo "  sse4_2 нет — x86-64-v1, как и ожидалось для Athlon II"
fi
echo "  RAM: $(free -h | awk '/^Mem:/{print $2}'), диск: $(lsblk -dno SIZE /dev/sda 2>/dev/null || echo '?')"
[ -f /swapfile ] && echo "  внимание: есть /swapfile помимо LVM-swap" || true

log "1. Базовые пакеты и обновление"
apt-get update -q
apt-get upgrade "${APT_OPTS[@]}" -q
apt-get install "${APT_OPTS[@]}" -q \
  ca-certificates curl gnupg git rsync htop tmux jq unzip ufw fail2ban \
  unattended-upgrades apt-listchanges smartmontools lm-sensors

log "2. Время, журнал, SSD, swap"
timedatectl set-timezone Europe/Moscow
timedatectl set-ntp true

install -d -m 755 /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/limits.conf <<'EOF'
[Journal]
SystemMaxUse=500M
RuntimeMaxUse=100M
EOF

cat >/etc/sysctl.d/99-journal.conf <<'EOF'
vm.swappiness = 10
vm.vfs_cache_pressure = 50
EOF
sysctl --system -q

# IPv6: сеть провайдера выдаёт AAAA-записи, но маршрута нет. Go-резолвер Docker
# выбирает IPv6 и падает с «network is unreachable». Гасим IPv6 и предпочитаем IPv4.
cat >/etc/sysctl.d/99-journal-noipv6.conf <<'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
for f in /proc/sys/net/ipv6/conf/*/disable_ipv6; do echo 1 >"$f"; done
grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf || echo 'precedence ::ffff:0:0/96  100' >>/etc/gai.conf

systemctl enable --now fstrim.timer

install -d -m 755 /etc/apt/apt.conf.d
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
systemctl enable --now unattended-upgrades

install -d -m 755 /etc/needrestart/conf.d
printf '$nrconf{restart} = "a";\n' >/etc/needrestart/conf.d/auto.conf

log "3. SSH-ключ и sudo для $ADMIN_USER"
install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/$ADMIN_USER/.ssh"
AUTH="/home/$ADMIN_USER/.ssh/authorized_keys"
touch "$AUTH"
grep -qxF "$PUBKEY" "$AUTH" || echo "$PUBKEY" >>"$AUTH"
chown "$ADMIN_USER:$ADMIN_USER" "$AUTH"
chmod 600 "$AUTH"

echo "$ADMIN_USER ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-journal-admin
chmod 440 /etc/sudoers.d/90-journal-admin
visudo -cf /etc/sudoers.d/90-journal-admin >/dev/null || die "сломан sudoers"

log "4. Файрвол и fail2ban"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 22/tcp >/dev/null
ufw --force enable >/dev/null
cat >/etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl restart fail2ban

log "5. Docker CE"
install -m 755 -d /etc/apt/keyrings
if [ ! -s /etc/apt/keyrings/docker.asc ]; then
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
fi
chmod a+r /etc/apt/keyrings/docker.asc
ARCH="$(dpkg --print-architecture)"
CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
echo "deb [arch=$ARCH signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $CODENAME stable" \
  >/etc/apt/sources.list.d/docker.list
apt-get update -q
apt-get install "${APT_OPTS[@]}" -q \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

install -d -m 755 /etc/docker
cat >/etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true,
  "dns": ["1.1.1.1", "8.8.8.8"]
}
EOF
systemctl enable --now docker
# dockerd собран с Go-резолвером, который игнорирует /etc/gai.conf и берёт AAAA.
# GODEBUG=netdns=cgo переводит его на системный (glibc) резолвер, где IPv4 идёт первым.
install -d -m 755 /etc/systemd/system/docker.service.d
printf '[Service]\nEnvironment=GODEBUG=netdns=cgo\n' \
  >/etc/systemd/system/docker.service.d/10-dns.conf
systemctl daemon-reload
systemctl restart docker
usermod -aG docker "$ADMIN_USER"

log "6. Каталоги проекта"
install -d -m 755 -o "$ADMIN_USER" -g "$ADMIN_USER" /srv/journal_bot
install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" /srv/backups
install -d -m 755 -o root -g root /srv/backups/pg

log "7. Проверка"
docker info --format '  Docker: {{.ServerVersion}}, storage={{.Driver}}, cgroup={{.CgroupVersion}}, mem={{.MemTotal}}'
docker compose version | sed 's/^/  /'
ufw status | sed 's/^/  /'
echo "  своп: $(swapon --show=NAME,SIZE --noheadings | tr '\n' ' ')"
echo "  свободно: $(df -h / | awk 'NR==2{print $4}') на /"
echo "  SMART: $(smartctl -H /dev/sda 2>/dev/null | awk -F': ' '/overall-health/{print $2}')"

if [ "$DISABLE_PASSWORD" = "1" ]; then
  log "8. Выключение парольного SSH"
  install -d -m 755 /etc/ssh/sshd_config.d
  cat >/etc/ssh/sshd_config.d/10-journal.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
MaxAuthTries 3
EOF
  sshd -t || die "sshd не принял конфиг — правка не применена"
  systemctl reload ssh
  echo "  вход теперь только по ключу"
else
  log "8. Парольный SSH оставлен включённым"
  echo "  после проверки входа по ключу: DISABLE_PASSWORD=1 bash bootstrap.sh"
fi

log "Готово"
