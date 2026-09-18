# --- IP intelligence data -----------------------------------------------------
#
# Built in its own stage so the databases land in the image while the tooling used
# to fetch and derive them does not.
#
# --keep-city retains DB-IP City Lite (~125 MB), which is the only source of true
# coordinates: without it every address in a country resolves to the same
# centroid, so impossible-travel sees zero distance for any move inside a country.
# The centroid table is generated regardless and remains the fallback for
# addresses the city database cannot place.
#
# To build a country-only image instead, override the arg and set GEOIP_CITY_PATH
# to empty at runtime:
#   docker build --build-arg IP_BUNDLE_ARGS=--with-city .
#
# This stage needs network access. Only the *runtime* is air-gapped: an isolated
# site consumes a pre-built image rather than building one in place.
FROM python:3.11 AS ipdata

WORKDIR /build
RUN pip install --no-cache-dir maxminddb

# The repository layout is preserved, because the script locates its committed
# seed relative to its own parent directory.
COPY scripts/build_ip_bundle.py /build/scripts/build_ip_bundle.py
COPY ipdata/seed /build/ipdata/seed
# Empty in the repository, so this COPY always succeeds and --source-dir below is
# a no-op by default. An air-gapped builder drops artefacts from a connected host
# here (see ipdata/seed/README.md) and adds --offline:
#   docker build --build-arg \
#     IP_BUNDLE_ARGS="--with-city --keep-city --source-dir ipdata/staged --offline" .
COPY ipdata/staged /build/ipdata/staged

ARG IP_BUNDLE_ARGS="--with-city --keep-city --source-dir ipdata/staged"
RUN python scripts/build_ip_bundle.py --out /ipdata ${IP_BUNDLE_ARGS}


# --- engine -------------------------------------------------------------------
FROM python:3.11 AS build

WORKDIR /app

RUN apt update && apt install -y postgresql-client

COPY ./requirements.lock /app/requirements.lock

RUN pip install pandas==2.2.2 --only-binary pandas
RUN pip install -r /app/requirements.lock
COPY . .

# The bundled databases and lists. IP_DATA_DIR points here, and each edition can
# be overridden individually so an operator can mount their own MMDB instead.
COPY --from=ipdata /ipdata /opt/amfa/ipdata
ENV IP_DATA_DIR=/opt/amfa/ipdata

ENV PYTHONPATH=/app
# Unbuffered stdout/stderr so INFO/DEBUG logs reach the container log stream
# immediately instead of sitting in a block buffer until it fills (which delays
# and can hide log lines in low-traffic periods).
ENV PYTHONUNBUFFERED=1

RUN python -m compileall -f /app || true

COPY scripts/migrations-entrypoint.sh /migrations-entrypoint.sh
RUN chmod +x /migrations-entrypoint.sh
ENTRYPOINT ["/migrations-entrypoint.sh"]

CMD ["python", "src"]
