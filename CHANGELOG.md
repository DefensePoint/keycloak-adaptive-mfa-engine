# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.0.1]: https://github.com/DefensePoint/keycloak-adaptive-mfa-engine/releases/tag/v1.0.1
