#!/usr/bin/env bash

docker exec -it backend alembic downgrade -1
