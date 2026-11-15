# Verification — 15 November 2026

- Complete local CI script passed: Docker builds, 12 integration tests against SQLite, the same 12 against PostgreSQL, JavaScript syntax and shell syntax.
- Tests include native Mealie persistence, immutable-history triggers, mandatory two-confirmation edits, password verification, approval expiry/session binding, changed drafts, stale revisions, idempotent AI additions, partial-batch nutrition, pinned cooking sessions, CSRF, denied stock API writes, private-address import rejection, image validation and theme preferences.
- OAuth tests cover ChatGPT callback registration, S256 PKCE, one-use codes, access/refresh token isolation, rotating refresh tokens, scope enforcement and an actual authenticated MCP recipe-draft tool call. No approval/publish tool is exposed over MCP.
- An encrypted synthetic PostgreSQL/database-and-media archive was restored into a separate disposable database. Its recipes, food catalogue and media fixture were checked.
- Local application health is successful. Application and database containers report healthy and publish only the intended application port on loopback.
- Existing autoheal automatically restarted a disposable unhealthy container carrying `autoheal=true`; the probe was then removed.
- JRH dashboard tests passed and the running catalogue contains Hearth & Spoon at the requested hostname.
- Dedicated `hearth-deploy` GitHub runner is registered and online. The workspace startup script includes application and runner services; installation of that updated script is user-operated.
- A local encrypted backup archive was created; verification used file metadata only and did not inspect production backup contents.

Browser inventory was empty and the in-app browser was unavailable. Visual layout, mobile interactions and accessibility contrast have not been verified in a live browser. This is explicitly separate from the passing backend and syntax checks.

The real ChatGPT connection depends on the user configuring the hostname to the documented origin and completing OAuth after setting up the owner account. No Cloudflare tunnel or route configuration was inspected or changed.
