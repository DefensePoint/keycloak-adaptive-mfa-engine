# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed

- The engine workers share one copy of the bundled IP databases instead of holding one each. Every worker read the databases into its own memory, about 140 MB per worker with the city database, so 4 workers held 4 copies. A database that is part of the image is now mapped from the file, and every worker reads the same pages: with `WORKERS=4` the engine starts at about 0.63 GB instead of 1.2 GB. A database on a mounted volume, or one the engine's user can write, is still read into memory, because a copy over a mapped file while the engine runs could hand lookups half-written data or stop the worker; hot reload works as before. Most of the remaining memory is per-worker Python libraries (pandas and scikit-learn, about 100 MB per worker).
- CI builds the engine image and runs the e2e suite against it. A new `e2e` job builds the image from the commit, starts the quick start stack with the e2e overlay (Keycloak with the plugin and admin UI, PostgreSQL, Redis, Mailpit), and runs `run_e2e.py` and `tests/e2e`, except the SSO suite and the browser journeys. The release workflow runs CI, so a tag whose image does not start or fails the suite is not published. The weight-mode signal matrix's baseline comparison runs without blocking, because its baseline predates scoring changes since the first release; its output is uploaded with the stack logs.
- The e2e signal matrix covers the `login_failure` signal. Row `F01`, an expected failure until now, fails five emailed codes in a row, which the Keycloak plugin reports as login errors from 1.1.0, and the signal fires. The attempts are a second and a half apart, because the test realm locks out a user whose failures come less than a second apart. Wrong passwords still do not count toward the signal: they come before the engine opens an auth process. Under bayesian scoring the row is skipped, like `C01`, because those logins are challenged with TOTP, which the test users have not enrolled.

### Removed

- The `geo_loc` parameter. It could be enabled and weighted through the settings API but never scored a login, so a weight given to it had no effect; location is scored by `country_name`, `geolocation_cluster_label` and `impossible_travel`. Settings saved before the upgrade keep their `geo_loc` row in the database, but the engine no longer returns it from `/{realm_id}/settings` or scores it, and a save that still sends it succeeds with the row left out. No login's risk level changes.

### Fixed

- The quick start and the HA stack start on a Linux host. Their `providers` service, which fetches the Adaptive MFA plugin, admin UI and vavr JARs, ran as the curl image's own user, which cannot write to a checkout owned by another user, as on a Linux host or a CI runner: it stopped with curl error 23 and Keycloak never started. It now runs as root and hands the JARs to the checkout's owner, so they are not left owned by root.
- A returning user's device counts as familiar from the first login scored on history. Before, on a screen that is not exactly a common size, such as most laptops', the logins inside the history gate stored the device under the raw screen size and later logins looked it up under the size rounded to its common bucket, so those logins never matched. With the default gate of four logins, device familiarity first counted at the ninth login. The screen size is now rounded before the gate. Device rows stored before the upgrade keep their raw hash and are not counted, and device familiarity needs four matching logins, so an existing user who has not yet had it gets it within their next four logins. `/auth_context` and the login webhook still record the raw size, as the device was reported.
- `RATE_LIMIT=False` turns rate limiting off, for `/decision` and for settings and scoring writes alike. The value was read with `bool()`, so any non-empty value, `False` included, kept it on, and an empty one turned it off; an `.env` that already says `False` now really has no limit. `true`/`false`, `1`/`0`, `yes`/`no` and `on`/`off` are accepted; any other value stops the engine at startup.
- The engine keeps working when its database is restored, swapped or reset while Redis is kept. The device and network steps asked their Redis cache whether a record existed, so a cached record the database no longer had was never written again: every `/decision`, `/auth_context` and login webhook then failed on the foreign key with HTTP 500 until Redis was flushed, and logins ran only on the plugin's fallback risk. Both steps now ask the database, which costs one read by primary key for a known device or network, and add a missing record. The two caches are removed; their `auth:device:v1:*` and `auth:location_network:v2:*` keys are no longer read and expire within a day.
- `docs/keycloak-setup.md` said `adaptiveAuthFailureMode` could be set on the Adaptive MFA page. The page sets only `fallbackRisk`; the failure mode is set through the admin REST API. The guide now shows the `kcadm.sh` command, and warns that an update whose `attributes` hold only the failure mode removes the realm's other attributes, the endpoint and the AMFA switch included.

### Changed

- Familiarity now needs the network as well as the device. With device familiarity counting, a known device would have lowered the level of a login from a network the user has never used, and of a Tor or hosting address, because the device outweighs the network in the familiarity score. So that a stolen session cookie or a device used from somewhere new is still challenged: a network with familiarity below 0.3 raises the level to 3 whatever the device, unless an allowlist covers it; familiarity lowers the level only when the network's is at least 0.6; and it lowers by one step, never straight to Risk 1. A login with no changed signal is already relaxed one step by the drop-down, so familiarity does not lower it a second time. Nor does familiarity lower a login on which a concurrent session, impossible travel or a recent credential change fired: those signals say someone else may be using the account, which the login's own device and network cannot vouch for. In bayesian mode the familiarity evidence follows the same rule: an unfamiliar network counts as unfamiliar, and a network between 0.3 and 0.6 adds no trust.
- `RATE_LIMIT_MAX_REQ` defaults to 30 `/decision` requests per user and realm per minute instead of 4, in the code and in `config/keycloak/.env.example`. A refused request gets HTTP 429, which the Keycloak plugin handles like an engine failure: at 4, a user's fifth login within a minute continued at the realm's fallback risk level, without a step-up when that level is 1. A deployment that sets the variable keeps its value: an `.env` copied from the earlier example still has `RATE_LIMIT_MAX_REQ=4`, so change or remove that line when upgrading.

## [1.2.0] - 2026-11-19

### Added

- `location_network` stores the coordinates of each address (migration `5ae8978564f9`), and the monitoring endpoints read them for a failed login stored without a risk decision, such as a wrong password or an unknown user, so it appears on the map. An address the lookup cannot place, a private one for example, stores none. Rows written before the upgrade are not backfilled. Such a row gets its coordinates only when its address logs in again while the geo and VPN data for it are unchanged, because the row's hash covers that data: after a data refresh the address gets a new row and the old one stays without coordinates, and an address that never logs in again, such as a one-off attacker's, keeps none. Failed logins stored against those rows stay off the map. The `location_network` cache key moves to `v2`, so the cache starts empty once, and during a rolling upgrade or after a rollback each version reads only its own entries. An older image will not start on a database migrated to this revision; to roll back, run `alembic downgrade f7a8b9c0d1e2` with this version first. The downgrade drops the coordinates, but `v2` cache entries keep them for up to 24 hours, so before upgrading again within that time delete the `auth:location_network:v2:*` keys from Redis; otherwise an address cached before the rollback gets its coordinates back only on a login after its entry expires.
- `MSSQL_POOL_SIZE` and `MSSQL_MAX_OVERFLOW` size the SQL Server connection pool. `MSSQL_AUTHENTICATION=ActiveDirectoryMsi` signs in with an Azure managed identity.
- `tests/integration` runs the login-scoring and monitoring queries against a real database, on PostgreSQL and SQL Server, in CI and before a release.
- `DB_TYPE=mssql` runs the engine against Azure SQL (or any SQL Server) in the same codebase as PostgreSQL. Postgres remains the default. Connection still uses the existing `POSTGRES_*` variables; ODBC Driver 18 is in the image for the SQL Server path.
- `config/keycloak/docker-compose.ha.yml` runs a high-availability stack: two Keycloak nodes clustered through embedded Infinispan and JDBC_PING, and two engine replicas sharing one PostgreSQL and Redis, behind nginx, which terminates TLS on port 8443 and balances both. It uses the same host ports as the single-node stack, and nginx answers to the `keycloak` and `adaptive_auth` names, so the realm configuration and the plugin's engine URL work unchanged. nginx (pinned to 1.27.5) looks the engine hostnames up again every 10 seconds, so a recreated engine replica gets traffic without restarting nginx, and it starts while the engines are down. `docs/ha-setup.md` describes how to run it and test failover.
- `docs/keycloak-setup.md` explains how to run AMFA for logins through an identity provider (SSO), as each provider's post login flow, and warns that a provider without that flow skips AMFA. The test realm ships the flow as `amfa-post-broker`, bound to no provider. `docs/environment-variables.md` lists every setting the engine reads, with its default.

### Changed

- The quick start (`config/keycloak/docker-compose.yml` and `Dockerfile.keycloak`) and the HA stack install the Adaptive MFA plugin and admin UI 1.1.0 instead of 1.0.1, pinned by their published SHA-256 digests, with vavr 1.0.1 as before. The test realm registers the plugin's `amfa-login-event-details` required action, and `docs/keycloak-setup.md` says how to register it and what plugin 1.1.0 reports to the engine that 1.0.1 did not: wrong codes on its email and TOTP steps, and device data for logins through an identity provider.
- On PostgreSQL, `/{realm}/monitoring/events` reads a page from the realm index instead of scanning the realm: with 2 million events, a page of 100 takes about 1 ms instead of 25 to 40 ms, wherever the cursor is. The cursor is a row comparison, and events with a realm of their own and events matched through their auth_process are read in separate branches. The pages are the same as before. SQL Server keeps its query, which it already serves from its realm index.
- The published image's lock file moves 60 packages: 54 upgraded and 6 added. The largest moves are FastAPI 0.109 to 0.162, Starlette 0 to 1 (0.35.1 to 1.10.0), Uvicorn 0.21 to 0.53, redis 5 to 8, and cryptography 44 to 50.
- Startup and shutdown run through a FastAPI lifespan handler, because Starlette 1 removed `add_event_handler`.
- CI installs `requirements.in` and the image lock file in separate jobs, and fails when an installed version does not satisfy `requirements.in`.
- Dependencies are declared in `requirements.in`, and `requirements.txt` is the lock, generated by pip-compile. It replaces `requirements.lock` with the same 79 pins. Dependabot updates the lock through pip-compile, and scanners that read `requirements.txt` by default, such as Trivy and Grype, now scan the pinned versions the image ships.

### Removed

- `POSTGRES_SCHEMA`. It was read and never used.

### Fixed

- The time-of-day check (`date_time`, off by default) no longer flags a login HIGH because the user has too little history. With a few logins, almost any hour not seen yet looked anomalous, so in a realm that switched the check on, an ordinary login at a new hour counted toward a step-up. It now stays LOW until the user has `DATETIME_MIN_SAMPLES` (default 20) logins on the same kind of day, weekday or weekend; with that much history it judges as before.
- On SQL Server, paging through `/{realm}/monitoring/events` returns each event once. `event_time` was stamped to 100 ns and read back to the microsecond, so a page cursor fell just before its own row: walking oldest first returned events again, and newest first could skip them. Migration `94c441a0b691` stamps microseconds from now on and truncates existing times to the microsecond the engine has always read. It rewrites those rows, and `event_time` leads the clustered index, so on a large SQL Server database the upgrade takes longer than usual. PostgreSQL is unchanged.
- A database user or password containing a space works, on PostgreSQL and SQL Server. The space reached the database as `+`, so the engine could not sign in and did not start.
- The monitoring endpoints report the IP address, country and VPN flag of a failed login the engine stored without a risk decision, such as a wrong password or an unknown user. They read the location the webhook stored for the event; before, such a failure showed no IP, no country and no VPN flag, and a failed login from a VPN address did not count in `flagged_ips`. These failures have no coordinates, so they are still not on the map.
- Image lock file pins SQLAlchemy 2.0.54 so `mssql+aioodbc` loads (added in 2.0.23). CI installs from the same lock file and runs the unit suite against SQL Server.
- Boolean and keyset filters no longer compile to `col = 1 = 1` on SQL Server, so login scoring, configuration activation, VPN filters, and monitoring paging work there.
- Map buckets round once, at the configured precision, in a subquery, so SQL Server groups and places coordinates as PostgreSQL does. Rounding through 4 decimals first put 38.74996 in the 38.8 cell, and capped the precision at 4 decimals.
- `/health` and `/health/detail` answer within `HEALTH_CHECK_TIMEOUT` (3 seconds by default) when the database or Redis hangs, on both databases, and recover by the next probe once it is back. They could previously hold a probe for 15 seconds or more. Checks use their own connections, so a stuck check cannot hold a slot in the shared pool.
- Realm, group, and human-readable text columns are `NVARCHAR` with a case-sensitive UTF-8 collation on SQL Server. Hash columns use a binary collation.
- `wait_for_db.py` brace-escapes the ODBC password so generated Azure passwords containing `;`, `{`, or `}` can start the container.
- SQL Server connection pools default to 2 plus 2 overflow per worker, so the default four workers stay under Azure SQL Basic's limits of 30 concurrent workers and logins.
- Monitoring queries no longer fail with a collation conflict on a SQL Server database that uses the server's default collation.
- `auth_event` and `auth_process` cluster on time rather than a random UUID on SQL Server, so they do not fragment as they grow. The realm index on `auth_event` uses ascending keys for the same reason. The remaining secondary indexes need routine maintenance, described in `docs/environment-variables.md`.
- `alembic check` reports no changes on a migrated database, on either dialect, and CI enforces it.
- A login without a screen resolution, such as a direct grant or a browser flow without the Screen Resolution step, gets a risk decision. `/auth_context` and `/decision` refused it with 422, so Keycloak fell back to the realm's fallback risk and the engine stored the login without a decision. The screen resolution and the auth context hash are now optional, and a missing screen resolution is scored as unknown: it earns no trust and is not compared with the previous login. An empty or malformed screen resolution is still refused.
- Requests that store the same new device or network at the same time, such as the events of a first SSO login from a new device, all succeed. Before, all but the first failed on the primary key with a 500 and their event was lost; now they use the record already stored.
- A LOGIN or LOGIN_ERROR event sent under the id of the decision that scored it is linked to that decision and closes it. Before, the engine linked an outcome only to the user's newest decision, through a pointer kept for 5 minutes, so an outcome was stored without its decision, or against the wrong one, when the login took longer than 5 minutes, when an earlier LOGIN_ERROR in the same login had already closed the decision (a wrong code in Keycloak's own OTP form), or when two logins of one user finished in reverse order; that decision then stayed open. A successful login replaces an earlier failure, never the other way round. An event whose id names no decision of that user and realm, such as one from a plugin that does not send the decision id, is linked as before.
- Requests for a realm whose OIDC discovery document is being fetched wait for that fetch and share its result, instead of getting an immediate 503. Before, the admin page's parallel loads could show "Could not load", and in a burst of logins right after an engine restart all but one request per worker process got a 503, which the plugin answered with the realm's fallback risk. `DISCOVERY_MAX_WAITERS` caps how many requests wait at once per worker process (default half the worker-thread pool, `min(32, CPU count + 4) // 2`); each waits at most `OIDC_DISCOVERY_TIMEOUT` plus 1 second, and a request past the cap still gets the 503.
- A discovery lookup that failed because Keycloak could not be reached (a connection error, a timeout or a 5xx) is remembered for `DISCOVERY_UNREACHABLE_CACHE_TTL` (default 5 seconds) instead of `DISCOVERY_FAILURE_CACHE_TTL` (default 30 seconds). Before, after Keycloak restarted, every realm asked about during the outage kept answering 503, and its logins fell back to the realm's fallback risk, for up to 30 seconds after Keycloak was back. A 404 or other 4xx, which a nonexistent realm gets, keeps the full TTL.
- Settings and scoring writes have their own limit, `CONFIG_RATE_LIMIT_MAX_REQ` (default 20 per `RATE_LIMIT_TIME_WINDOW`), per realm and calling client. They used `RATE_LIMIT_MAX_REQ` (default 4), and every admin of a realm writes through the same service account while the admin page spends two writes per Save, so with the defaults a third Save within a minute was refused with 429, whoever made it. `/decision` keeps `RATE_LIMIT_MAX_REQ`.
- When `LOG_DIR` exists but cannot be written, such as a root-owned volume or a read-only mount, the engine logs to the console and each worker logs one "File logging disabled" warning at startup. Before, every log record printed a traceback and no log file was written.
- The quick start runs on a clean checkout. The SHA-256 digests pinned for the SPI and admin UI v1.0.1 jars in `docker-compose.yml` and `Dockerfile.keycloak` did not match the published release, so the providers service failed and Keycloak never started. The README's test user also gets the first and last name the test realm requires, so its first login no longer stops at "Update Account Information".
- `docs/keycloak-setup.md` places the risk tiers inside the "forms" subflow, as the test realm does, and adds the deny tier that refuses a risk 4 login. A browser flow built as the guide described before, with the tiers next to "forms", showed no login form, and without the deny tier a risk 4 login got in after the email code.
- The release workflow runs the same tests as CI, from the same lock file the image uses.

## [1.1.0] - 2026-10-19

### Added

- `MONITORING_TRUSTED_READERS` lets a named service account read the read-only `/monitoring` endpoints of any realm, so one monitoring client in an admin realm can read every tenant realm
- `REDIS_USERNAME` for a Redis 6+ ACL user, and `REDIS_SSL` and `REDIS_SSL_CA_CERTS` for TLS to Redis

### Fixed

- `REDIS_PASSWORD` is sent to Redis, so the engine starts against a Redis that requires a password, and startup stops with a clear error when Redis cannot be reached or refuses the credentials
- Removed a check for LOGIN events with no open auth process that never ran; such events are stored as before

## [1.0.1] - 2026-09-22

### Added

- Risk evaluation engine with 19 configurable signals
- Local ML inference using K-Modes, DBSCAN, and histogram-based time profiling
- Weight-based and log-odds Bayesian scoring modes
- Device and network familiarity scoring
- Impossible travel detection
- VPN, proxy, and Tor detection using bundled IP databases
- Per-realm configuration for weights, allow-lists, and deny-lists
- Self-healing risk decay over repeated clean logins
- REST API with `POST /decision` and `POST /auth_context` endpoints
- Docker Compose stack with Keycloak, PostgreSQL, Redis, and Mailpit
- Alembic database migrations
- Bundled DB-IP Lite geolocation and ASN databases
- DB-IP CC BY 4.0 attribution in README
- Local dev credentials warning in README
- SECURITY.md, CODE_OF_CONDUCT.md, and CONTRIBUTING.md

[1.2.0]: https://github.com/DefensePoint/keycloak-adaptive-mfa-engine/releases/tag/v1.2.0
[1.1.0]: https://github.com/DefensePoint/keycloak-adaptive-mfa-engine/releases/tag/v1.1.0
[1.0.1]: https://github.com/DefensePoint/keycloak-adaptive-mfa-engine/releases/tag/v1.0.1
