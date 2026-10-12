#!/usr/bin/env sh
# One consistent dump of the application database (RAG chunks, users, conversations, dashboards, audit log, cost data, mem0,
# and the `langfuse` schema, which lives in the same database). Runs inside the db-backup service, or by hand:
#   docker compose -f docker-compose.yml -f docker-compose.backup.yml run --rm --no-deps --entrypoint /backup.sh db-backup
# Redis is NOT backed up: it holds sessions, rate-limit counters and pending approvals, all short-lived.
set -eu
dir="${BACKUP_DIR:-/backups}"
keep="${BACKUP_KEEP_DAYS:-14}"
out="$dir/${POSTGRES_DB}-$(date +%Y%m%d-%H%M%S).dump"
PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h "${POSTGRES_HOST:-postgres}" -U "$POSTGRES_USER" -Fc -f "$out.tmp" "$POSTGRES_DB"
mv "$out.tmp" "$out"   # a half-written dump never has the final name
find "$dir" -name "${POSTGRES_DB}-*.dump" -mtime +"$keep" -delete
echo "backup written: $out ($(du -h "$out" | cut -f1)); kept $keep days"
