import uvicorn

from src.core.config.environment import ENGINE_PORT, WORKERS, validate


def main() -> None:
    validate()
    uvicorn.run(
        "src.server_init:app", host="0.0.0.0", port=ENGINE_PORT, workers=WORKERS
    )


if __name__ == "__main__":
    main()
