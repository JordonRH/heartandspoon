# Hearth & Spoon

A private, self-hosted kitchen for recipes worth keeping. Built on **[Mealie](https://github.com/mealie-recipes/mealie)**, with a new interface and a protected AI workflow.

- Five themes: Hearth, Midnight, Botanical, Nordic and High Contrast.
- Manual, pasted-text, supported-URL and ChatGPT MCP recipe drafts.
- Ingredients, methods, cooking times, appliance settings and private recipe photos.
- Local matching against 7,793 USDA foods; calculated calories and nutrients with explicit missing-data indicators.
- Smaller batches, selected components and resumable cooking sessions that preserve the original.
- Immutable recipe history. Established recipes require two human confirmations and password verification before a replacement version is published.
- ChatGPT OAuth MCP using the official Python SDK and the local Career Vault connection pattern. AI cannot approve its own edits.
- Docker Compose, private PostgreSQL, health checks, autoheal labels, encrypted nightly backups and GitHub Actions CI/CD.

Deployment: [DEPLOYMENT.hearth.md](DEPLOYMENT.hearth.md). Repositories, licenses and data credits: [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md). Original Mealie documentation: [README.mealie.md](README.mealie.md).

## Runtime

```bash
node scripts/prepare-runtime.mjs
mkdir -p backups
docker compose up -d --build
docker compose exec -it hearth uv run --no-project /opt/mealie/bin/python -m mealie.hearth.setup_owner
```

The interactive account command asks for your credentials without echoing the password. No public registration or usable default login is enabled.

Local origin: `http://127.0.0.1:8098`. Intended HTTPS hostname: `https://recipes.jrhtechservices.party`. ChatGPT connector: `https://recipes.jrhtechservices.party/mcp/` with OAuth. Tunnel/route configuration is user-operated.

## Development and verification

The backend extension is in `mealie/hearth/`; it reuses Mealie's native recipe models, schema and account storage. All writes go through the kitchen workflow. Published snapshots pin food data, methods, components and media references, preventing indirect changes. The custom Alembic migration adds workflow/history records in the same database.

```bash
bash scripts/ci.sh
```

CI uses disposable containers for both SQLite and PostgreSQL and restores an encrypted synthetic backup. It never connects to production data. On successful main-branch checks, a dedicated local runner deploys the verified commit and checks health. See deployment documentation for setup and recovery limits.

## Attribution and license

This repository retains Mealie's AGPL-3.0 license, notices, source and history. Mealie v3.31.0 is the foundation. The official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) provides the AI transport; [recipe-scrapers](https://github.com/hhursev/recipe-scrapers) provides supported-site extraction. The food catalogue is derived from public-domain [USDA FoodData Central](https://fdc.nal.usda.gov/download-datasets/) SR Legacy data. The complete list of incorporated/reference projects and deployment tooling is in [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).

Recipe prose and photos entered or imported by users retain their original attribution and rights. No bulk third-party recipe collection is bundled.
