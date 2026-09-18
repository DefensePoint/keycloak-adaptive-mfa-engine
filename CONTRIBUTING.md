# Contributing to Adaptive MFA

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository and create a branch from `main`.
2. Follow the setup instructions in the README to run the service locally.
3. Make your changes, add tests where applicable, and ensure all existing tests pass.
4. Open a pull request with a clear description of the change.

## Development Setup

```bash
# Start the full stack (Keycloak + engine + redis + postgres)
cd config/keycloak
cp .env.example .env
docker compose up --build -d
```

See `config/keycloak/docker-compose.yml` and `docs/keycloak-setup.md` for details.

## Running Tests

```bash
pytest tests/unit -v
```

## Code Style

- Python 3.11+, async/await throughout
- Pydantic v2 for schemas, SQLAlchemy 2.0 async ORM
- New risk checks go in `src/service/risk_evaluation/checks/`
- All new code must have corresponding unit tests in `tests/unit/`

## Pull Request Guidelines

- Keep PRs focused on a single concern
- Include a test for any bug fix or new feature
- Update relevant documentation if behavior changes

## Reporting Issues

Open a GitHub issue with a clear description, steps to reproduce, and the version you are running.
