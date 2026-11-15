#!/bin/sh
set -eu
set -o pipefail
umask 077
run_backup() {
  work=$(mktemp -d)
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  trap 'rm -rf "$work"' EXIT INT TERM
  pg_dump --host=db --username=hearth --dbname=hearth --format=custom --file="$work/database.dump"
  # Media is immutable: copying after the database snapshot includes everything it references.
  tar -C "$work" -cf - database.dump -C /data hearth-media 2>/dev/null \
    | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_KEY -out "/backups/hearth-$stamp.tar.enc.tmp"
  mv "/backups/hearth-$stamp.tar.enc.tmp" "/backups/hearth-$stamp.tar.enc"
  rm -rf "$work"
  trap - EXIT INT TERM
  echo "Encrypted Hearth & Spoon backup completed."
}
if [ "${1:-}" = "--once" ]; then run_backup; exit 0; fi
while true; do
  if ! run_backup; then echo "Hearth & Spoon backup failed; inspect status without displaying credentials." >&2; fi
  sleep 86400
done
