#!/usr/bin/env bash
# Install + first run for the disk/pool health metrics job.
#   sudo bash install-disk-health.sh
# Installs: /usr/local/sbin/disk-health-metrics, /etc/systemd/system/disk-health.{service,timer}
# Then: first run (via systemd) -> show the metrics -> restart smartd -> enable the 5-minute timer.
set -euo pipefail
cd "$(dirname "$0")"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
OUT=/var/lib/node_exporter/textfile_collector/disk_health.prom

echo "== install"
install -m 750 -o root -g root disk-health-metrics.py /usr/local/sbin/disk-health-metrics
install -m 644 -o root -g root disk-health.service disk-health.timer /etc/systemd/system/
systemctl daemon-reload

echo "== first run"
systemctl start disk-health.service
journalctl -u disk-health.service --since "-2 min" --no-pager -o cat | tail -10
[[ $(systemctl show -p Result --value disk-health.service) == success ]] || { echo "FIRST RUN FAILED; timer not enabled"; exit 1; }
grep -E '^(smart_device_up|smart_temperature|zpool_data_errors|zpool_vdev_online)' "$OUT"
n=$(grep -c '^smart_device_up{.*kind="hdd"' "$OUT" || true)
(( n == 3 )) || echo "WARNING: expected 3 pool disks with SMART data, got $n"

# smartd only scans for disks at startup; after the enclosure reconnected as sdd/sde/sdf it stopped
# logging them (attrlog.*.csv). A restart makes it pick up whatever is attached now.
echo "== restart smartd"
systemctl restart smartmontools

echo "== enable 5-minute timer"
systemctl enable --now disk-health.timer
systemctl list-timers disk-health.timer --no-pager
echo "All good."
