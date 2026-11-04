#!/bin/bash
source /opt/vless-updater/env

CACHE=/opt/vless-updater/nodes_cache.txt
ALERT_TS=/opt/vless-updater/.alert_ts
ALERT_COOLDOWN=14400   # 4 часа

log() { echo "[vless-updater] $1"; }

notify() {
  [ -z "$TG_TOKEN" ] && return
  curl -s --max-time 20 -x "$PROXY" \
    "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
    -d "chat_id=$TG_CHAT_ID" --data-urlencode "text=$1" >/dev/null 2>&1 \
  || curl -s --max-time 20 \
    "https://api.telegram.org/bot$TG_TOKEN/sendMessage" \
    -d "chat_id=$TG_CHAT_ID" --data-urlencode "text=$1" >/dev/null 2>&1
}

notify_rate() {
  now=$(date +%s)
  last=$(cat "$ALERT_TS" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt $ALERT_COOLDOWN ]; then
    log "alert throttled: $1"
    return 0
  fi
  notify "$1"
  echo "$now" > "$ALERT_TS"
}

health() {
  curl -s --max-time 15 -x "$PROXY" https://openrouter.ai/api/v1/models \
    -o /dev/null -w "%{http_code}" 2>/dev/null
}

code=$(health)
if [ "$code" = "200" ]; then
  log "healthy (HTTP 200), nothing to do"
  exit 0
fi
log "unhealthy (HTTP $code), fetching subscription..."

tmpfile=$(mktemp)
curl -sL --max-time 30 -x "$PROXY" "$SUB_URL" | base64 -di > "$tmpfile" 2>/dev/null
if [ ! -s "$tmpfile" ]; then
  if grep -q "^vless://" "$CACHE" 2>/dev/null; then
    log "fetch failed, using nodes cache ($(wc -l < "$CACHE") nodes)"
    cp "$CACHE" "$tmpfile"
  else
    log "ERROR: subscription fetch failed and no cache"
    notify_rate "⚠️ VPN VPS: не удалось скачать подписку ithyper (кэша нет)"
    rm -f "$tmpfile"
    exit 1
  fi
else
  cp "$tmpfile" "$CACHE"
fi

result=$(python3 /opt/vless-updater/apply_node.py "$CONFIG" "$tmpfile")
rc=$?
rm -f "$tmpfile"
log "apply_node: $result"

case $rc in
  0)
      systemctl restart sing-box
      sleep 3
      code1=$(health); [ "$code1" = "200" ] || { sleep 5; code1=$(health); }
      if [ "$code1" = "200" ]; then
        log "config updated, healthy"
        notify_rate "✅ VPN VPS: прокси починен автоматически ($result), OpenRouter снова 200"
      else
        log "ERROR: still unhealthy after update (HTTP $code1)"
        notify_rate "❌ VPN VPS: обновил конфиг ($result), но OpenRouter недоступен (HTTP $code1) — нужен ручной разбор"
        exit 1
      fi
      ;;
  3)  notify_rate "⚠️ VPN VPS: прокси болен, но подписка не изменилась — временный сбой ноды"
      ;;
  *)  notify_rate "❌ VPN VPS: все ноды из подписки недоступны ($result)"
      exit 1 ;;
esac
