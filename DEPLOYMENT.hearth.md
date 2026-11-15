# Hearth & Spoon deployment

Public hostname: `recipes.jrhtechservices.party`.

Host-local HTTP address: `http://127.0.0.1:8098`.

Origin reachable by the Docker-based connector: `http://hearth-and-spoon:9000` on the existing `aitrace_proxy` network.

ChatGPT MCP address: `https://recipes.jrhtechservices.party/mcp/`, using OAuth.

## Local services

`compose.yml` runs the Mealie-based application, private PostgreSQL 16 database and daily encrypted-backup container. Application and database have health checks and `autoheal=true`. Services use `restart: unless-stopped`. PostgreSQL has no published host port.

The application runs as UID 911. Deployment follows the other local applications: source under `/home/jbox/Documents/ChatGPT/Linux general/hearth-and-spoon`, Docker Compose, loopback-only published port, and a dedicated container-based Actions runner in `compose.runner.yml`.

## First start

Run commands from this project directory. The runtime preparation command creates `.env` once with mode 0600 and never displays or overwrites its values:

```bash
node scripts/prepare-runtime.mjs
mkdir -p backups
docker compose up -d --build
docker compose exec -it hearth uv run --no-project /opt/mealie/bin/python -m mealie.hearth.setup_owner
```

The account command asks privately for an email, display name and password. It replaces the unusable default admin login and revokes existing sessions and AI connections. There is no public signup or usable default login. Use the same interactive command for operator-controlled password recovery.

If the current shell is not in the Docker group, use `sg docker -c 'COMMAND'` for a noninteractive command. For account setup, `sg docker -c 'docker compose exec -it hearth uv run --no-project /opt/mealie/bin/python -m mealie.hearth.setup_owner'` retains interactive input.

## User-operated networking and startup installation

All Cloudflare tunnel and route configuration remains user-operated. Configure the hostname above to **HTTP `hearth-and-spoon:9000`**. The existing connector runs on Docker bridge networks, so its loopback address is not the host's loopback address. Only the application joins the existing external `aitrace_proxy` network, with the stable alias `hearth-and-spoon`; the database and backup service remain on the private kitchen network. The application, `/oauth/*`, `/.well-known/*` and `/mcp/` must reach the same origin. Do not put an interactive access challenge in front of the MCP or OAuth endpoints; application authentication remains required.

The workspace startup script includes both application and runner Compose files. Installing that updated script requires the user to run:

```bash
sudo install -m 755 '/home/jbox/Documents/ChatGPT/Linux general/jtlinuxbox-startup' /usr/local/sbin/jtlinuxbox-startup
```

No tunnel configuration is included in this repository. The JRH dashboard catalogue is maintained in the neighbouring `jrh-dashboard` project.

## ChatGPT connection

After the hostname reaches the application, add the MCP address above as a ChatGPT connector with OAuth. The flow follows Career Vault's existing pattern: dynamic public-client registration, S256 PKCE, a signed-in consent page, resource-bound access tokens, one-use codes and rotating refresh tokens. Only ChatGPT HTTPS connector callbacks are registered.

There are no browser-approval tools in MCP. ChatGPT creates drafts or proposes revisions and returns a link to review in this application. Finalizing a change to an established recipe requires both browser confirmations and your password. A changed proposal, expired confirmation, changed base revision or different browser session invalidates approval.

Use Your kitchen → Disconnect to revoke a connection. Password recovery/setup also revokes connections.

## CI/CD

`.github/workflows/hearth.yml` builds and tests on GitHub-hosted Ubuntu runners. Checks cover SQLite, PostgreSQL, native Mealie storage, immutable history, two confirmations, password verification, stale proposals, cooking-session pinning, nutrition math, OAuth/PKCE/refresh isolation, MCP transport, SSRF filtering, and an encrypted-backup restore drill.

Successful main-branch runs deploy through the dedicated `hearth-deploy` runner. Pull requests never deploy or run on the private runner. Deployment checks the expected commit, refuses tracked local edits, backs up a running instance, builds, restarts and verifies local health plus authentication. It also probes the application from a disposable container on the connector's shared proxy network, so a host-only health check cannot conceal an unreachable proxy origin. It retains the prior application image for rollback. Database rollback requires an operator restore; image rollback does not reverse migrations.

Runner registration is a separate one-time operator workflow. Its registration token is kept in process memory, passed to a temporary container, and never displayed or tracked. Persistent runner credentials live in ignored `deploy-runner-state/`; do not inspect or commit them. The long-running runner has no registration token environment value.

## Backups and recovery

The backup container creates a nightly timestamped encrypted archive in ignored `backups/`, containing a PostgreSQL custom-format dump and immutable media. Encryption uses OpenSSL AES-256-CBC with PBKDF2 and a separately generated high-entropy key held in runtime configuration. An initial archive is made when the backup service starts.

No automated off-machine copy or retention deletion is configured. Keep an off-machine copy of the archives and the runtime recovery key through your own secure backup process. Losing the key prevents recovery. The JSON export is useful for recipe portability but excludes images and is not a complete backup.

An operator restoring a real archive should decrypt it in a private temporary directory, restore `database.dump` with `pg_restore` into an empty compatible PostgreSQL database, and restore `hearth-media` into the application data volume with ownership 911:911. Never print a dump, key, runtime configuration or runner credential file. `scripts/test-postgres.sh` documents and automatically exercises the process with disposable synthetic data only.

## Current boundaries

The product implements the recipe library, five themes, text/URL/manual/AI drafts, images, immutable revisions, partial batches/components, resumable cook mode, local USDA matching, calculated calories/macros and ChatGPT OAuth MCP. It uses a purpose-built interface over Mealie's models; the stock Mealie web/API write surface is not mounted. Meal planning, pantry integration, PDF/photo OCR and a separate phone app are future additions. Owner account recovery is operator-controlled; MFA and passkeys are not implemented in this first version.
