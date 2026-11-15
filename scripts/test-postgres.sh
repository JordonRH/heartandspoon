#!/usr/bin/env bash
# Entirely synthetic: no production volumes, secrets, ports or databases are used.
set -euo pipefail
suffix="${GITHUB_RUN_ID:-local}-$$"
network="hearth-test-$suffix"
db="hearth-test-db-$suffix"
backup="hearth-test-backup-$suffix"
restore="hearth-test-restore-$suffix"
data="hearth-test-data-$suffix"
archives="hearth-test-archives-$suffix"
cleanup() {
  docker rm -f "$db" "$backup" "$restore" >/dev/null 2>&1 || true
  docker volume rm "$data" "$archives" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
}
trap cleanup EXIT
docker network create "$network" >/dev/null
docker volume create "$data" >/dev/null
docker volume create "$archives" >/dev/null
docker run -d --name "$db" --network "$network" --network-alias db \
  -e POSTGRES_DB=hearth -e POSTGRES_USER=hearth -e POSTGRES_PASSWORD=synthetic-postgres-password postgres:16-alpine >/dev/null
for i in {1..45}; do
  if docker exec "$db" pg_isready -U hearth -d hearth >/dev/null 2>&1; then break; fi
  sleep 1
done
docker run --rm --user 0 --network "$network" -v "$data:/app/data" \
  -e DB_ENGINE=postgres -e POSTGRES_SERVER=db -e POSTGRES_DB=hearth -e POSTGRES_USER=hearth \
  -e POSTGRES_PASSWORD=synthetic-postgres-password -e PRODUCTION=true -e LOG_LEVEL=ERROR \
  hearth-ci uv run --no-project /opt/mealie/bin/python -m unittest mealie.hearth.tests -q
docker run --rm --user 0 -v "$data:/data" hearth-ci uv run --no-project /opt/mealie/bin/python -c \
  'from pathlib import Path; p=Path("/data/hearth-media/synthetic"); p.mkdir(parents=True,exist_ok=True); (p/"fixture.txt").write_text("synthetic restore fixture")'
docker run --name "$backup" --network "$network" -v "$data:/data:ro" -v "$archives:/backups" \
  -e PGPASSWORD=synthetic-postgres-password -e BACKUP_KEY=synthetic-backup-encryption-key hearth-backup-ci --once
docker exec "$db" createdb -U hearth hearth_restore
docker run --name "$restore" --network "$network" -v "$archives:/backups:ro" \
  -e PGPASSWORD=synthetic-postgres-password -e BACKUP_KEY=synthetic-backup-encryption-key \
  --entrypoint sh hearth-backup-ci -ec '
    archive=$(find /backups -name "*.enc" | head -n 1)
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_KEY -in "$archive" | tar -xf - -C /tmp
    pg_restore --host=db --username=hearth --dbname=hearth_restore --no-owner --exit-on-error /tmp/database.dump
    test "$(cat /tmp/hearth-media/synthetic/fixture.txt)" = "synthetic restore fixture"
    test "$(psql --host=db --username=hearth --dbname=hearth_restore -Atc "SELECT count(*) > 0 FROM hearth_revisions")" = t
    test "$(psql --host=db --username=hearth --dbname=hearth_restore -Atc "SELECT count(*) FROM hearth_foods")" = 7793
    echo "Synthetic encrypted backup and restoration passed."
  '
