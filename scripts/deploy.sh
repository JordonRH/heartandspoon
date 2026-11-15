#!/usr/bin/env bash
set -euo pipefail
target="/home/jbox/Documents/ChatGPT/Linux general/hearth-and-spoon"
cd "$target"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Deployment stopped: tracked local edits need to be committed first." >&2
  exit 1
fi
git fetch https://github.com/JordonRH/heartandspoon.git main
latest=$(git rev-parse FETCH_HEAD)
if [[ -n "${EXPECTED_SHA:-}" && "$latest" != "$EXPECTED_SHA" ]]; then
  echo "A newer main commit exists; this older deployment was skipped."
  exit 0
fi
git merge --ff-only FETCH_HEAD
if [[ "$(git rev-parse HEAD)" != "$latest" ]]; then
  echo "Deployment stopped: the local checkout is ahead of the verified commit." >&2
  exit 1
fi
previous=$(docker image ls --no-trunc --quiet hearth-and-spoon:local | head -n 1)
if [[ -n "$previous" ]]; then docker tag "$previous" hearth-and-spoon:previous; fi
if curl -fsS http://127.0.0.1:8098/api/health >/dev/null 2>&1; then
  docker compose run --rm --no-deps backup --once
fi
docker compose build --pull
rollback() {
  if [[ -n "$previous" ]]; then
    docker tag hearth-and-spoon:previous hearth-and-spoon:local
    docker compose up -d --no-build hearth
  fi
  echo "Deployment failed. The prior application image was restored where available; database rollback requires an operator restore." >&2
}
trap rollback ERR
docker compose up -d --no-build
for attempt in {1..60}; do
  if curl -fsS http://127.0.0.1:8098/api/health >/dev/null 2>&1; then
    test "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8098/api/kitchen/recipes)" = 401
    curl -fsS http://127.0.0.1:8098/kitchen/assets/app.js >/dev/null
    trap - ERR
    echo "Hearth & Spoon deployed and healthy at local port 8098."
    exit 0
  fi
  sleep 2
done
false
