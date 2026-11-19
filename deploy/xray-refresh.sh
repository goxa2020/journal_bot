#!/usr/bin/env bash
# Обновляет конфиг xray из подписки провайдера и перезапускает службу,
# только если новый конфиг прошёл проверку. Запуск на сервере: sudo deploy/xray-refresh.sh
#
# Ссылка на подписку хранится в /etc/xray/subscription (0600), а не в репозитории:
# репозиторий публичный, а подписка — учётные данные.
set -euo pipefail

SUB_FILE="${SUB_FILE:-/etc/xray/subscription}"
CONFIG="${CONFIG:-/usr/local/etc/xray/config.json}"
UA="Happ/2.0"          # провайдер отдаёт sing-box JSON только этому клиенту
TMP_JSON="$(mktemp --suffix=.json)"
TMP_CFG="$(mktemp --suffix=.json)"
trap 'rm -f "$TMP_JSON" "$TMP_CFG"' EXIT

[ "$(id -u)" -eq 0 ] || { echo "нужен root" >&2; exit 1; }
[ -r "$SUB_FILE" ]   || { echo "нет $SUB_FILE" >&2; exit 1; }

echo "== загрузка подписки"
curl -fsSL -m 30 -A "$UA" "$(cat "$SUB_FILE")" -o "$TMP_JSON"
[ -s "$TMP_JSON" ] || { echo "пустой ответ подписки" >&2; exit 1; }

echo "== сборка конфига"
python3 - "$TMP_JSON" "$TMP_CFG" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
data = json.load(open(src))
cfg = data[0] if isinstance(data, list) else data
nodes = [o for o in cfg.get('outbounds', []) if o.get('protocol') == 'vless']
if not nodes:
    sys.exit('в подписке нет vless-нод')
node = nodes[0]
vnext = node['settings']['vnext'][0]
user = vnext['users'][0]
rs = node['streamSettings']['realitySettings']
out = {
    "log": {"loglevel": "warning"},
    "inbounds": [{"tag": "http-in", "listen": "172.17.0.1", "port": 10809,
                  "protocol": "http", "settings": {"auth": "noauth", "udp": False}}],
    "outbounds": [{
        "tag": "proxy", "protocol": "vless",
        "settings": {"vnext": [{"address": vnext['address'], "port": vnext['port'],
                                "users": [{"id": user['id'], "encryption": "none",
                                           "flow": user.get('flow', '')}]}]},
        "streamSettings": {"network": "tcp", "security": "reality",
            "realitySettings": {"serverName": rs['serverName'],
                                "fingerprint": rs.get('fingerprint', 'chrome'),
                                "publicKey": rs['publicKey'], "shortId": rs['shortId'],
                                "spiderX": "/"}}
    }]
}
open(dst, 'w').write(json.dumps(out, indent=2))
print(f"  нода: {vnext['address']}:{vnext['port']}, reality {rs['serverName']}")
PY

echo "== проверка конфига"
xray -test -config "$TMP_CFG" >/dev/null 2>&1 || { echo "конфиг невалиден, оставляю прежний" >&2; exit 1; }

install -m 600 "$TMP_CFG" "$CONFIG"
systemctl restart xray
sleep 3

echo "== проверка доступа к Telegram"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 -x http://172.17.0.1:10809 https://api.telegram.org/ || true)
if [ "$code" = "302" ] || [ "$code" = "200" ]; then
  echo "  Telegram отвечает ($code) — обновление применено"
else
  echo "  Telegram не отвечает (код '$code') — проверь подписку и ноду" >&2
  exit 1
fi
