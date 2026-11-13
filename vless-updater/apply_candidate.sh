#!/bin/bash
# Internal helper: caller update.sh must hold its process-wide flock.
set -Eeuo pipefail
umask 077
: "${XCONFIG:=/usr/local/etc/xray/config.json}"
: "${PROXY:?PROXY required}"
CANDIDATE=${1:?candidate required}
DIR=$(dirname "$XCONFIG")
STAGE=""
BACKUP=""
PENDING=0
cleanup() {
  rc=$?
  trap - EXIT
  set +e
  if [ "$PENDING" = 1 ]; then
    restore=$(mktemp "$DIR/.restore.XXXXXX.json")
    if [ -n "$restore" ] && cp -p -- "$BACKUP" "$restore" && mv -f -- "$restore" "$XCONFIG" && systemctl restart xray && systemctl is-active --quiet xray; then
      echo 'APPLY:rolled_back'
    else
      echo 'APPLY:rollback_failed_manual_intervention_required'
      rc=2
    fi
  fi
  [ -z "$STAGE" ] || rm -f -- "$STAGE"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 1' TERM INT HUP
[ -f "$XCONFIG" ] && [ ! -L "$XCONFIG" ] || exit 2
SERVICE_USER=$(systemctl show xray -p User --value)
SERVICE_USER=${SERVICE_USER:-root}
STAGE=$(mktemp "$DIR/.candidate.XXXXXX.json")
cp -- "$CANDIDATE" "$STAGE"
chown --reference="$XCONFIG" "$STAGE"
chmod --reference="$XCONFIG" "$STAGE"
runuser -u "$SERVICE_USER" -- test -r "$STAGE"
if ! runuser -u "$SERVICE_USER" -- xray run -test -c "$STAGE" >/dev/null 2>&1; then
  echo 'APPLY:validation_failed'
  exit 1
fi
BACKUP=$(mktemp "$DIR/.backup.XXXXXX.json")
cp -p -- "$XCONFIG" "$BACKUP"
PENDING=1
mv -f -- "$STAGE" "$XCONFIG"
systemctl restart xray
sleep 3
systemctl is-active --quiet xray
for attempt in 1 2; do
  code=$(curl -s --max-time 15 --noproxy "" -x "$PROXY" https://openrouter.ai/api/v1/models -o /dev/null -w '%{http_code}') || code=000
  if [ "$code" = 200 ]; then
    PENDING=0
    echo 'APPLY:healthy'
    exit 0
  fi
  sleep 5
done
echo 'APPLY:health_failed'
exit 1
