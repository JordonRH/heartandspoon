#!/usr/bin/env bash
set -euo pipefail
if [[ ! -x /runner/run.sh ]]; then cp -a /runner-template/. /runner/; fi
if [[ "${1:-}" = "--register" ]]; then
  : "${RUNNER_TOKEN:?A short-lived registration token is required}"
  /runner/config.sh --url https://github.com/JordonRH/heartandspoon --token "$RUNNER_TOKEN" \
    --name hearth-docker-host --labels hearth-deploy --work /runner/_work --unattended
  exit 0
fi
if [[ ! -f /runner/.runner ]]; then echo "Register the runner with scripts/register-runner.mjs first." >&2; exit 1; fi
unset RUNNER_TOKEN
exec /runner/run.sh
