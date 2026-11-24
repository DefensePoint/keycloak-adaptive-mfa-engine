#!/usr/bin/env bash
# Runs a command in the e2e runner container, on the network of the quick start
# stack started as project "amfa", the way CI runs tests/e2e:
#
#   scripts/ci/e2e-run.sh python tests/e2e/run_e2e.py
#
# The runner image is the engine image plus the docker CLI (see the e2e job in
# .github/workflows/ci.yml). On the stack's network the suite reaches keycloak,
# adaptive_auth and mailpit by name, the modules that import the engine get the
# image's own dependencies, and the docker socket lets it exec into the stack's
# containers. The container gets -i, so a script can be piped to it.
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
env_file="$repo/config/keycloak/.env"
setting() { sed -n "s/^$1=//p" "$env_file"; }

network=$(docker inspect -f '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}' amfa-adaptive_auth-1)
ca=/work/config/keycloak/certs/rootCA.pem

exec docker run --rm -i --network "$network" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$repo:/work" -w /work \
  -e PYTHONPATH=/work -e PYTHONDONTWRITEBYTECODE=1 \
  -e REQUESTS_CA_BUNDLE="$ca" -e SSL_CERT_FILE="$ca" \
  -e E2E_ENGINE_BASE=http://adaptive_auth:80 \
  -e E2E_MAILPIT_BASE=http://mailpit:8025 \
  -e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB="$(setting POSTGRES_DB)" \
  -e POSTGRES_USER="$(setting POSTGRES_USER)" \
  -e POSTGRES_PASSWORD="$(setting POSTGRES_PASSWORD)" \
  -e REDIS_HOST=redis -e REDIS_PORT=6379 \
  "${E2E_RUNNER_IMAGE:-amfa-e2e-runner}" "$@"
