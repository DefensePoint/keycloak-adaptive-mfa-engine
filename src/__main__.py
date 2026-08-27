import uvicorn

from src.core.config.environment import WORKERS

uvicorn.run("src.server_init:app", host="0.0.0.0", port=80, workers=WORKERS)
