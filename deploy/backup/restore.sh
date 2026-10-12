#!/usr/bin/env sh
# Restore a dump made by backup.sh into a NEW database of the running Postgres container. It never touches the live database:
# look at the result (psql, or point POSTGRES_URL at it), then swap names yourself when you are sure.
#   deploy/backup/restore.sh backups/agentdb-20261008-020000.dump            # -> database agentdb_restore
#   deploy/backup/restore.sh backups/agentdb-20261008-020000.dump agentdb_check
# Run it from the project root (it uses `docker compose exec` on the postgres service).
set -eu
dump="${1:?usage: restore.sh <file.dump> [target-database]}"
target="${2:-agentdb_restore}"
[ -f "$dump" ] || { echo "no such file: $dump" >&2; exit 1; }
docker compose exec -T postgres sh -c '
  [ "$0" != "$POSTGRES_DB" ] || { echo "refusing to overwrite the live database $POSTGRES_DB" >&2; exit 1; }
  dropdb -U "$POSTGRES_USER" --if-exists "$0" && createdb -U "$POSTGRES_USER" "$0"
' "$target"
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" --no-owner --exit-on-error -d "$0"' "$target" < "$dump"
echo "restored $dump into database $target"
