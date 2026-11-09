#!/bin/bash
# v3.1 — retry-цикл на случай общего флапа ithyper (08.11.2026: все 4 ноды лежали ~20 мин)
source /opt/vless-updater/env

CACHE=/opt/vless-updater/nodes_cache.txt
ALERT_TS=/opt/vless-updater/.alert_ts
STATE=/opt/vless-updater/.state
ALERT_COOLDOWN=14400
XCONFIG=${XCONFIG:-/usr/local/etc/xray/config.json}
BUILDER=/opt/vless-updater/build_xray_config.py
ATTEMPTS=${ATTEMPTS:-4}
RETRY_DELAY=${RETRY_DELAY:-180}

log() { echo "[vless-updater] $1"; }

notify() {
  [ -z "$TG_TOKEN" ] && return
  log "alert send: ${1:0:60}"
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

state() { cat "$STATE" 2>/dev/null || echo ok; }
mark()  { echo "$1" > "$STATE"; }

health() {
  curl -s --max-time 15 -x "$PROXY" https://openrouter.ai/api/v1/models \
    -o /dev/null -w "%{http_code}" 2>/dev/null
}

fetch_nodes() {
  local raw; raw=$(mktemp)
  local mode
  for mode in proxy direct; do
    if [ "$mode" = proxy ]; then
      curl -sL --max-time 30 -x "$PROXY" "$SUB_URL" -o "$raw" 2>/dev/null
    else
      log "fetch: retrying direct"
      curl -sL --max-time 30 "$SUB_URL" -o "$raw" 2>/dev/null
    fi
    if [ -s "$raw" ] && base64 -di "$raw" 2>/dev/null | grep -q "^vless://"; then
      base64 -di "$raw" > "$1" 2>/dev/null
      rm -f "$raw"
      log "fetch: OK via $mode"
      return 0
    fi
  done
  rm -f "$raw"
  return 1
}

recovered() {
  cur=$(grep -oP '(?<="address": ")[^"]+' "$XCONFIG" | head -1)
  notify "✅ VPN VPS: прокси восстановлен (нода $cur), OpenRouter 200"
  mark ok
}

code=$(health)
if [ "$code" = "200" ]; then
  [ "$(state)" = "fail" ] && recovered
  mark ok
  log "healthy (HTTP 200), nothing to do"
  exit 0
fi
log "unhealthy (HTTP $code), starting heal attempts..."

fixed=""
for attempt in $(seq 1 "$ATTEMPTS"); do
  if [ "$attempt" -gt 1 ]; then
    log "attempt $attempt/$ATTEMPTS: пауза ${RETRY_DELAY}s, затем ре-проверка"
    sleep "$RETRY_DELAY"
    code=$(health)
    if [ "$code" = "200" ]; then
      log "self-recovered during retry window"
      recovered
      log "healthy (HTTP 200) after wait"
      exit 0
    fi
  fi

  tmpfile=$(mktemp)
  if fetch_nodes "$tmpfile"; then
    cp "$tmpfile" "$CACHE"
    log "attempt $attempt: nodes: $(grep -c '^vless://' "$tmpfile") from subscription"
  elif grep -q "^vless://" "$CACHE" 2>/dev/null; then
    log "attempt $attempt: fetch failed, using cache ($(grep -c '^vless://' "$CACHE") nodes)"
    cp "$CACHE" "$tmpfile"
  else
    log "attempt $attempt: ERROR subscription fetch failed and no cache"
    notify_rate "⚠️ VPN VPS: не удалось скачать подписку ithyper (кэша нет)"
    rm -f "$tmpfile"
    continue
  fi

  n=$(grep -c '^vless://' "$tmpfile")
  i=0
  while [ $i -lt "$n" ]; do
    i=$((i+1))
    onecfg=$(mktemp --suffix=.json)
    res=$(python3 "$BUILDER" "$tmpfile" "$onecfg" "$i" 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
      log "attempt $attempt node $i: skip ($res)"
      rm -f "$onecfg"
      continue
    fi
    if ! xray run -test -c "$onecfg" >/dev/null 2>&1; then
      log "attempt $attempt node $i: xray -test failed"
      rm -f "$onecfg"
      continue
    fi
    cp "$onecfg" "$XCONFIG"
    rm -f "$onecfg"
    systemctl restart xray
    sleep 3
    c1=$(health); [ "$c1" = "200" ] || { sleep 5; c1=$(health); }
    disp="${res#BUILT:}"; disp="${disp% extra=yes}"
    log "attempt $attempt node $i: $disp health $c1"
    if [ "$c1" = "200" ]; then fixed="$disp"; break; fi
  done
  rm -f "$tmpfile"
  [ -n "$fixed" ] && break
done

if [ -n "$fixed" ]; then
  log "config updated, healthy on $fixed"
  notify "✅ VPN VPS: прокси починен автоматически ($fixed), OpenRouter 200"
  mark ok
  exit 0
fi

log "ERROR: все кандидаты мертвы после $ATTEMPTS попыток"
if [ "$(state)" != "fail" ]; then
  notify "❌ VPN VPS: все ноды недоступны ($ATTEMPTS попытки за ~$(( (ATTEMPTS-1)*RETRY_DELAY/60 + 10 )) мин) — похоже на общий сбой ithyper. Повтор через час по таймеру."
fi
mark fail
exit 1
