import uvicorn

from src.core.config.environment import WORKERS, validate


def main() -> None:
    validate()
    uvicorn.run("src.server_init:app", host="0.0.0.0", port=80, workers=WORKERS)


if __name__ == "__main__":
    main()
