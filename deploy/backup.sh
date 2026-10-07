#!/usr/bin/env bash
# Nightly Postgres backup for the Arbiter stack.
#
#   1. pg_dump (custom format, compressed) from the running postgres container
#   2. copy the uploaded/translated file storage volume as a tarball
#   3. upload both to off-site object storage with rclone (Hetzner Storage Box,
#      Hetzner Object Storage or any S3-compatible bucket)
#   4. prune local copies older than LOCAL_RETENTION_DAYS and remote ones older
#      than REMOTE_RETENTION_DAYS
#
# Cron (as root on the host, 02:30 server time):
#   30 2 * * * /opt/arbiter/deploy/backup.sh >> /var/log/arbiter-backup.log 2>&1
#
# Config via environment or deploy/.env:
#   BACKUP_DIR              local folder              (default /var/backups/arbiter)
#   RCLONE_REMOTE           rclone remote:path        (e.g. storagebox:arbiter-backups); empty = local only
#   LOCAL_RETENTION_DAYS    default 7
#   REMOTE_RETENTION_DAYS   default 30
#   BACKUP_STORAGE          1 = also archive the file storage volume (default 1)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE=(docker compose -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$SCRIPT_DIR/.env")

if [ -f "$SCRIPT_DIR/.env" ]; then
  # shellcheck disable=SC1091
  set -a; . "$SCRIPT_DIR/.env"; set +a
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/arbiter}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
LOCAL_RETENTION_DAYS="${LOCAL_RETENTION_DAYS:-7}"
REMOTE_RETENTION_DAYS="${REMOTE_RETENTION_DAYS:-30}"
BACKUP_STORAGE="${BACKUP_STORAGE:-1}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
umask 077

log() { echo "[$(date -u +%FT%TZ)] $*"; }

DB_FILE="$BACKUP_DIR/arbiter-db-$STAMP.dump"
log "pg_dump -> $DB_FILE"
"${COMPOSE[@]}" exec -T postgres pg_dump -U arbiter -d arbiter -Fc -Z 6 > "$DB_FILE.partial"
mv "$DB_FILE.partial" "$DB_FILE"
# A dump that pg_restore cannot list is not a backup.
"${COMPOSE[@]}" exec -T postgres pg_restore --list < "$DB_FILE" > /dev/null
log "db dump ok ($(du -h "$DB_FILE" | cut -f1))"

FILES=("$DB_FILE")
if [ "$BACKUP_STORAGE" = "1" ]; then
  ST_FILE="$BACKUP_DIR/arbiter-storage-$STAMP.tar.gz"
  log "storage volume -> $ST_FILE"
  "${COMPOSE[@]}" run --rm --no-deps -T --entrypoint tar worker \
    -C /var/lib/arbiter -czf - storage > "$ST_FILE.partial"
  mv "$ST_FILE.partial" "$ST_FILE"
  FILES+=("$ST_FILE")
fi

( cd "$BACKUP_DIR" && sha256sum "${FILES[@]##*/}" > "arbiter-$STAMP.sha256" )
FILES+=("$BACKUP_DIR/arbiter-$STAMP.sha256")

if [ -n "$RCLONE_REMOTE" ]; then
  for f in "${FILES[@]}"; do
    log "upload $(basename "$f") -> $RCLONE_REMOTE"
    rclone copy --retries 5 "$f" "$RCLONE_REMOTE/"
  done
  log "prune remote older than ${REMOTE_RETENTION_DAYS}d"
  rclone delete --min-age "${REMOTE_RETENTION_DAYS}d" --include "arbiter-*" "$RCLONE_REMOTE/"
else
  log "RCLONE_REMOTE empty: backup kept locally only (not an off-site backup)"
fi

log "prune local older than ${LOCAL_RETENTION_DAYS}d"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'arbiter-*' -mtime +"$LOCAL_RETENTION_DAYS" -delete

log "done"
