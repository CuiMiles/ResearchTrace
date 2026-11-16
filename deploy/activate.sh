#!/bin/sh
# Run on ECS as root after the final image, private environment and seed are ready.
# Usage: deploy/activate.sh /opt/researchtrace/releases/<release> researchtrace:<tag>
set -eu
umask 077
release=$(realpath "$1")
image=$2
case "$release" in /opt/researchtrace/releases/*) ;; *) exit 2 ;; esac
test -f "$release/deploy/compose.ecs.yaml"
test -s /opt/researchtrace/private/runtime.env
docker image inspect "$image" >/dev/null
docker compose -p researchtrace -f "$release/deploy/compose.ecs.yaml" config --quiet
if test -f /opt/researchtrace/data/researchtrace.sqlite; then
    python3 "$release/scripts/backup.py" --data /opt/researchtrace/data --destination /opt/researchtrace/backups --env /opt/researchtrace/private/runtime.env
fi
previous=$(readlink -f /opt/researchtrace/current || true)
printf '%s\n' "$previous" > /opt/researchtrace/private/previous-release
export RT_IMAGE="$image"
docker compose -p researchtrace -f "$release/deploy/compose.ecs.yaml" up -d --no-build --wait --wait-timeout 90
# Publish pointer only after the candidate's API health check has passed.
ln -s "$release" /opt/researchtrace/current-next
mv -Tf /opt/researchtrace/current-next /opt/researchtrace/current
printf '%s\n' "$image" > /opt/researchtrace/private/current-image
install -m 0644 "$release/deploy/researchtrace-backup.service" /etc/systemd/system/researchtrace-backup.service
install -m 0644 "$release/deploy/researchtrace-backup.timer" /etc/systemd/system/researchtrace-backup.timer
systemctl daemon-reload
systemctl enable --now researchtrace-backup.timer
curl --fail --silent http://127.0.0.1:18970/healthz
printf '\nResearchTrace containers activated; public HTTPS/login need independent verification.\n'
