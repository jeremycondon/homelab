#!/usr/bin/env bash
# Nightly backup of this server's NVMe app data to ZFS: tank/backups/hosts/jeremy-n100
#
#   sudo bash nvme-backup.sh            # run once now
#   sudo bash nvme-backup.sh --dry-run  # show what rsync would change and which snapshots would be pruned
#
# What it does, in order:
#   1. Dumps each running database container (currently only photoprism_db, MariaDB)
#      to a .sql.gz file, so the backup holds a consistent copy, not live DB files.
#   2. rsyncs the app data below into the backup dataset (mirror: files deleted on the
#      NVMe are removed from the mirror -- earlier versions stay in the snapshots).
#   3. Snapshots the dataset:  tank/backups/hosts/jeremy-n100@nvme-YYYY-MM-DD_HHMM
#   4. Prunes ONLY snapshots with that "nvme-" prefix: keeps the newest 30, plus the
#      first snapshot of each month for the last 12 months. Nothing else is ever deleted.
#   5. Writes a status file node_exporter can expose, for a "no backup in 48h" alert.
set -euo pipefail

DATASET=tank/backups/hosts/jeremy-n100
PREFIX=nvme-
KEEP_DAILY=30
KEEP_MONTHLY=12
DRY=; [[ "${1:-}" == "--dry-run" ]] && DRY=1
SOURCES=(
  /data                       # app configs/data: plex, photoprism storage, grafana, samba, (old jellyfin)
  /var/lib/docker/volumes     # named Docker volumes (portainer, prometheus, traefik certs)
  /home/jeremy/homelab        # compose files, secrets, scripts
  /etc                        # system configuration
)
EXCLUDES=(  # rebuildable caches / temp only; databases and settings are kept
  --exclude=/data/plex/transcode/
  --exclude='/data/plex/config/Library/Application Support/Plex Media Server/Cache/'
  --exclude='/data/plex/config/Library/Application Support/Plex Media Server/Crash Reports/'
  --exclude='/data/plex/config/Library/Application Support/Plex Media Server/Codecs/'
  --exclude=/data/photoprism/storage/cache/          # thumbnails; PhotoPrism regenerates them
  --exclude='*/transcodes/'
  --exclude='*_photoprism_db/'                       # raw MariaDB files; the SQL dump covers it
)
STATUS_DIR=/var/lib/node_exporter/textfile_collector
LOG_TAG=nvme-backup

log() { echo "$(date '+%F %T') $*"; logger -t "$LOG_TAG" -- "$*" 2>/dev/null || true; }
fail() { log "FAILED: $*"; write_status 0; exit 1; }
write_status() {  # $1 = 1 success / 0 failure
  mkdir -p "$STATUS_DIR"
  local f="$STATUS_DIR/nvme_backup.prom"
  {
    echo "# HELP nvme_backup_last_run_timestamp_seconds Last time the NVMe backup job ran."
    echo "nvme_backup_last_run_timestamp_seconds $(date +%s)"
    echo "# HELP nvme_backup_last_success Whether the last run succeeded (1) or failed (0)."
    echo "nvme_backup_last_success $1"
    [[ $1 == 1 ]] && echo "nvme_backup_last_success_timestamp_seconds $(date +%s)"
  } > "$f.tmp" && mv "$f.tmp" "$f"
}
trap 'fail "error on line $LINENO"' ERR

DEST=$(zfs get -H -o value mountpoint "$DATASET") || fail "dataset $DATASET not found"
[[ -d "$DEST" ]] || fail "mountpoint $DEST missing"
mkdir -p "$DEST/db-dumps" "$DEST/files"
chmod 700 "$DEST"   # the mirror includes /etc (shadow, keys) and ~/homelab/secrets

# 1. Database dumps (only containers that are running)
if docker ps --format '{{.Names}}' | grep -qx photoprism_db; then
  if [[ -z $DRY ]]; then
    log "dumping photoprism_db"
    docker exec photoprism_db sh -c 'exec mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" --all-databases --single-transaction --routines --events' \
      | gzip > "$DEST/db-dumps/photoprism_db.sql.gz.tmp"
    mv "$DEST/db-dumps/photoprism_db.sql.gz.tmp" "$DEST/db-dumps/photoprism_db.sql.gz"
  else
    log "(dry run) would dump photoprism_db"
  fi
else
  log "photoprism_db not running; no dump"
fi

# 2. Mirror the app data
RS=(rsync -aHX --numeric-ids --delete --delete-excluded --relative "${EXCLUDES[@]}")
[[ -n $DRY ]] && RS+=(--dry-run --itemize-changes)
log "rsync ${SOURCES[*]} -> $DEST/files"
"${RS[@]}" "${SOURCES[@]}" "$DEST/files/" || {
  rc=$?; [[ $rc == 24 ]] || fail "rsync exit $rc"   # 24 = files vanished during copy (normal for live data)
}

# 3. Snapshot
SNAP="$DATASET@${PREFIX}$(date +%F_%H%M)"
if [[ -z $DRY ]]; then zfs snapshot "$SNAP"; log "snapshot $SNAP"; else log "(dry run) would snapshot $SNAP"; fi

# 4. Prune our own snapshots only
mapfile -t SNAPS < <(zfs list -H -t snapshot -o name -s creation "$DATASET" | grep "@${PREFIX}" || true)
declare -A KEEP=()
n=${#SNAPS[@]}
for ((i = n - KEEP_DAILY; i < n; i++)); do (( i >= 0 )) && KEEP[${SNAPS[i]}]=1; done       # newest 30
declare -A SEEN_MONTH=()
for s in "${SNAPS[@]}"; do                                                                # first per month
  m=${s#*@${PREFIX}}; m=${m:0:7}
  [[ -z ${SEEN_MONTH[$m]:-} ]] && SEEN_MONTH[$m]=$s
done
MONTHS=()
if (( ${#SEEN_MONTH[@]} > 0 )); then   # no snapshots yet (first run / dry run): nothing to keep or prune
  mapfile -t MONTHS < <(printf '%s\n' "${!SEEN_MONTH[@]}" | sort | tail -n "$KEEP_MONTHLY")
fi
for m in "${MONTHS[@]}"; do [[ -n $m ]] && KEEP[${SEEN_MONTH[$m]}]=1; done
for s in "${SNAPS[@]}"; do
  [[ -n ${KEEP[$s]:-} ]] && continue
  [[ $s == "$DATASET@${PREFIX}"* ]] || continue   # belt and braces: never touch other snapshots
  if [[ -z $DRY ]]; then zfs destroy "$s"; log "pruned $s"; else log "(dry run) would prune $s"; fi
done

[[ -z $DRY ]] && write_status 1
log "done"
