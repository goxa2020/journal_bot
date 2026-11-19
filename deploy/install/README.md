# Сервер journal_bot: Debian 13 с нуля

Инструкция для физической установки на старый ПК (Athlon II X4, 8 ГБ, SSD).
Установку делает человек, потому что флешку в USB и выбор загрузки в BIOS
через SSH не сделать. После первой загрузки управление переходит агенту:
что именно он настраивает — в [bootstrap.sh](bootstrap.sh) и в §7.

**Почему Debian 13, а не Mint/Ubuntu:** процессор K10 — это x86-64-v1,
без SSE4.2. Debian держит базовый x86-64 и в trixie, поэтому система
гарантированно загрузится и проживёт до ~2030 года. RHEL-семейство и
часть современного софта требуют v2 и на этом железе не пойдут.

---

## 0. Что понадобится

- флешка ≥ 2 ГБ (содержимое сотрётся);
- ISO **Debian 13 amd64 netinst**, ~700 МБ: <https://www.debian.org/download>;
- кабель Ethernet — по Wi-Fi это железо почти наверняка останется без драйверов;
- клавиатура, экран, доступ к BIOS;
- 20–30 минут.

## 1. Записать ISO на флешку (Windows)

Rufus → выбрать ISO → **Схема разделов: MBR**, **Целевая система: BIOS (или UEFI-CSM)**
→ «Записать» (режим записи образа, не «ISO-образ»).

## 2. BIOS

F2 / Del при включении. Проверить:

- **SATA Mode = AHCI** — если стоит IDE, переключить сейчас, потом будет больно;
- загрузка с USB первой (режим Legacy/CSM; UEFI на этой плате не нужен);
- если установщик зависает на «Detecting hardware» — отключить Floppy,
  Serial Port и Parallel Port.

F10 → сохранить и выйти.

## 3. Установщик: ответы по экранам

| Экран | Что выбрать |
|---|---|
| Language | English (логи читать проще; на работу не влияет) |
| Location | Europe → Russian Federation |
| Keymap | English (US), Russian можно добавить вторым |
| Hostname | `journal`, Domain — **пусто** |
| Root password | **оставить пустым** (root отключён, sudo у первого пользователя) |
| Full name / username | имя на твой вкус, логин — например `george` — **запомни его** |
| Clock | Europe/Moscow, UTC+3 |
| Partitioning | **Manual** — см. §4 |
| Mirror | `deb.debian.org` (или `mirror.yandex.ru/debian`), proxy — пусто |
| Popularity contest | No |
| Software | снять всё; отметить только **SSH server** и **standard system utilities** |
| GRUB | да, в **/dev/sda** (не в раздел) |

## 4. Разметка вручную (LVM)

Цель: `/boot` 1 ГБ, swap 4 ГБ, остальное — корень ext4 в LVM.
Шифрование не делаем: на K10 нет AES-NI, LUKS съест производительность базы
без выигрыша для домашнего сервера.

1. `Manual`.
2. Выбрать `SCSI1 (0,0,0) (sda)` → **Yes**, создать пустую таблицу разделов.
3. `FREE SPACE` → *Create a new partition* → **1 GB** → Beginning →
   *Use as:* **Ext4 journaling file system** → mount point **`/boot`**.
4. Оставшееся `FREE SPACE` → *Create a new partition* → максимум →
   *Use as:* **physical volume for LVM**.
5. *Configure the Logical Volume Manager* → Yes →
   *Create volume group* → имя **`vg0`** → устройство `/dev/sda2` →
   *Create logical volume* → VG `vg0` → имя **`swap`** → **4 GB** →
   *Create logical volume* → VG `vg0` → имя **`root`** → весь остаток.
6. Вернуться в разметку: `lv_swap` → *Use as:* **swap area**;
   `lv_root` → **Ext4**, mount point **`/`**.
7. *Finish partitioning and write changes to disk* → Yes.

**Проверка перед подтверждением:** в списке ровно четыре строки —
`sda1` (`/boot`), `sda2` (LVM PV), `lv_root` (`/`), `lv_swap` (swap).
Если появилось что-то ещё или размеры не те — вернуться и переделать.

## 5. Первая загрузка

1. Вынуть флешку, дождаться `journal login:`.
2. Войти под своим пользователем.
3. `ip -4 addr show` — записать адрес вида `192.168.1.x`.
4. **Закрепить адрес в роутере** (DHCP reservation по MAC). Если не закрепить,
   через N дней адрес сменится и доступ пропадёт.
5. `systemctl status ssh` → `active (running)`.
6. Убедиться, что процессор действительно v1:
   `grep -o -m1 'sse4_2' /proc/cpuinfo` → **пусто** (иначе плата другая, скажи мне).

## 6. Передать агенту

IP-адрес, логин и пароль — **один раз**. Дальше вход только по ключу:
агент поставит свой `ssh-ed25519`, проверит его и выключит вход по паролю.

## 7. Что сделает агент (bootstrap.sh)

- обновление системы, часовой пояс, `unattended-upgrades`;
- `ufw`: входящие запрещены, открыт только 22/tcp; `fail2ban` на sshd;
- Docker CE из официального репозитория + compose-плагин;
- `/etc/docker/daemon.json`: ротация логов (10 МБ × 3), `live-restore`;
- вход по ключу, `sudo` без пароля для администратора, парольный SSH — выключен;
- `fstrim.timer` для SSD, лимиты журнала (500 МБ), `vm.swappiness=10`;
- каталоги `/srv/journal_bot` (код и `.env`) и `/srv/backups`;
- `smartmontools` + `lm-sensors`: состояние диска и температуры под контролем.

После этого — деплой: `docker compose -f docker-compose.prod.yml up -d`.

## 8. Если что-то пошло не так

| Симптом | Причина и что делать |
|---|---|
| Установщик не стартует с флешки | Rufus: MBR + BIOS (не UEFI), режим «запись образа» |
| «No common CD-ROM drive» | то же: USB записан в ISO-режиме |
| Не видит диск | SATA = AHCI, проверить кабель и питание |
| Зависает на «Detecting hardware» | отключить Floppy/Serial/Parallel в BIOS |
| После установки не грузится | GRUB в MBR `/dev/sda`; в BIOS загрузка с HDD первой |
| Нет сети после загрузки | кабель, `ip a`; Wi-Fi на этом железе не рассчитываем |
