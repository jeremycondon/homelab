#!/usr/bin/env bash
# Install + first run + restore test for the nightly NVMe backup.
#   sudo bash install-nvme-backup.sh
# Installs: /usr/local/sbin/nvme-backup.sh, /etc/systemd/system/nvme-backup.{service,timer}
# Then: dry run -> real run (as the systemd service) -> restore test -> enable 03:30 nightly timer.
# The timer is enabled ONLY if the first run and the restore test pass.
set -euo pipefail
cd "$(dirname "$0")"
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
DS=tank/backups/hosts/jeremy-n100
MP=$(zfs get -H -o value mountpoint $DS)

echo "== install"
install -m 750 -o root -g root nvme-backup.sh /usr/local/sbin/nvme-backup.sh
install -m 644 -o root -g root nvme-backup.service nvme-backup.timer /etc/systemd/system/
systemctl daemon-reload

echo "== dry run (no changes)"
/usr/local/sbin/nvme-backup.sh --dry-run | grep -vE '^[.>cd]' | tail -15

echo "== first real run (via systemd, so it runs exactly as it will nightly)"
systemctl start nvme-backup.service
journalctl -u nvme-backup.service --since "-10 min" --no-pager -o cat | tail -15
[[ $(systemctl show -p Result --value nvme-backup.service) == success ]] || { echo "FIRST RUN FAILED; timer not enabled"; exit 1; }

echo "== restore test"
SNAP=$(zfs list -H -t snapshot -o name -s creation $DS | grep '@nvme-' | tail -1)
echo "latest snapshot: $SNAP"
SD="$MP/.zfs/snapshot/${SNAP#*@}"
ok=1
cmp -s "$SD/files/home/jeremy/homelab/docker-compose.yml" /home/jeremy/homelab/docker-compose.yml \
  && echo "  compose file restored from snapshot: identical to live" || { echo "  compose file MISMATCH"; ok=0; }
if [[ -f "$SD/db-dumps/photoprism_db.sql.gz" ]]; then
  # read the whole dump (grep -q would close the pipe early -> SIGPIPE -> false failure under pipefail)
  D="$SD/db-dumps/photoprism_db.sql.gz"
  tables=$(zcat "$D" | grep -c '^CREATE TABLE' || true)
  last=$(zcat "$D" | tail -n 1)
  if gzip -t "$D" && (( tables > 0 )) && [[ $last == "-- Dump completed"* ]]; then
    echo "  photoprism_db dump: valid gzip, $tables tables, complete ('$last')"
  else
    echo "  photoprism_db dump INVALID (tables=$tables, last line='${last:0:60}')"; ok=0
  fi
else
  echo "  photoprism_db dump missing"; ok=0
fi
[[ -d "$SD/files/data/plex/config" ]] && echo "  plex config present in snapshot" || { echo "  plex config missing"; ok=0; }
du -sh "$MP/files" "$MP/db-dumps" | sed 's/^/  size: /'
(( ok )) || { echo "RESTORE TEST FAILED; timer not enabled"; exit 1; }

echo "== enable nightly timer"
systemctl enable --now nvme-backup.timer
systemctl list-timers nvme-backup.timer --no-pager
echo "All good."
