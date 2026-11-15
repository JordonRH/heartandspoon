# Repositories and data used

Hearth & Spoon is a derivative of Mealie, not an independently written recipe engine. The original copyright notices and AGPL license are retained. The upstream source and history are available through the `upstream` Git remote.

| Project | How it is used |
| --- | --- |
| [mealie-recipes/mealie](https://github.com/mealie-recipes/mealie) | Foundation: v3.31.0, commit `c87f20d1293b6e7732afe1b25d07ed79152b75a8`. Native recipe models, validation, database migrations, accounts, password hashing, dependency set and Docker base image. AGPL-3.0. |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | FastMCP and Streamable HTTP transport, version 1.28.0. MIT. |
| [hhursev/recipe-scrapers](https://github.com/hhursev/recipe-scrapers) | Extraction of supported recipe websites after a bounded, DNS-pinned public-web fetch. MIT. |
| [fastapi/fastapi](https://github.com/fastapi/fastapi) | HTTP application and validation integration, inherited from Mealie. MIT. |
| [sqlalchemy/sqlalchemy](https://github.com/sqlalchemy/sqlalchemy) | Shared native recipe and workflow persistence, inherited from Mealie. MIT. |
| [python-pillow/Pillow](https://github.com/python-pillow/Pillow) | Private photo validation, resizing, metadata removal and WebP encoding. Retains its upstream licensing. |
| [astral-sh/uv](https://github.com/astral-sh/uv) | Python package installation and execution in Docker. MIT/Apache-2.0. |
| [postgres/postgres](https://github.com/postgres/postgres) | PostgreSQL 16 database, dump and recovery tools. PostgreSQL License. |
| [docker-library/postgres](https://github.com/docker-library/postgres) | Official PostgreSQL Docker image used by the database and backup container. |
| [actions/runner](https://github.com/actions/runner) | Dedicated Docker-based GitHub Actions deployment runner. MIT. |
| [actions/checkout](https://github.com/actions/checkout) | GitHub Actions source checkout. MIT. |
| [willfarrell/docker-autoheal](https://github.com/willfarrell/docker-autoheal) | Existing host autoheal integration through health checks and `autoheal=true` labels; no autoheal source is copied into this project. |
| [JordonRH/career-experience-vault](https://github.com/JordonRH/career-experience-vault) | Reference for the existing ChatGPT OAuth discovery, registration, PKCE and refresh-token connection pattern. Recipe approval is separately enforced in the browser. |
| [JordonRH/JGym](https://github.com/JordonRH/JGym) | Reference for the existing Docker-host deployment runner and startup structure. |

The full inherited Python/JavaScript dependency manifests and lockfiles remain in this repository. Their dependencies retain their respective upstream licenses. The new kitchen interface uses system fonts and code-drawn graphics; it does not copy another application's theme or use stock recipe photography.

## Food data

The local nutrition catalogue contains 7,793 records derived from **USDA FoodData Central SR Legacy, April 2018**. Source: [downloadable datasets](https://fdc.nal.usda.gov/download-datasets/), [data/API licensing](https://fdc.nal.usda.gov/api-guide/). USDA publishes this data under CC0/public-domain terms. Each food retains its FDC identifier and source label.

`scripts/build-food-catalog.py` reproduces the compact catalogue from the official SR Legacy JSON archive. This is nutrition reference data, not a collection of recipe prose or photographs. User-imported recipes and images retain their original attribution and rights.

Tandoor, Rezepte and Grocy were researched as alternatives. Their source code was not incorporated into Hearth & Spoon. No community Mealie or Tandoor MCP bridge was copied; this application uses the official Python SDK directly.
