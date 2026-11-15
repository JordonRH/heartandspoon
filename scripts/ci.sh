#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -f Dockerfile.hearth -t hearth-ci .
docker build -t hearth-backup-ci backup
docker run --rm --user 0 --tmpfs /app/data -e DB_ENGINE=sqlite -e PRODUCTION=true -e LOG_LEVEL=ERROR \
  hearth-ci uv run --no-project /opt/mealie/bin/python -m unittest mealie.hearth.tests -q
bash scripts/test-postgres.sh
node --check mealie/hearth/web/app.js
node scripts/check-theme-contrast.mjs
bash -n scripts/deploy.sh
echo "Hearth & Spoon CI checks passed."
