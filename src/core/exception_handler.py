import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.core.config.environment import REJECTED_AUTH_RISK_LEVEL


from src.core.exception import (
    RejectedAuthException,
    TimeOutException,
    DataValidationException,
    RateLimitException,
)


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(DataValidationException)
    async def data_validation_exception_handler(
        request: Request, exc: DataValidationException
    ):
        logging.info("DataValidationException occurred")
        return JSONResponse(
            status_code=400,
            content={"success": False, "errors": exc.errors},
        )

    @app.exception_handler(TimeOutException)
    async def timeout_exception_handler(request: Request, exc: TimeOutException):
        logging.info("TimeOutException occurred")
        return JSONResponse(
            status_code=408,
            content={
                "success": False,
                "errors": getattr(exc, "errors", "Request timed out"),
            },
        )

    @app.exception_handler(RateLimitException)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitException):
        logging.info("RateLimitException occurred")
        # No riskLevel in the body: a 429 is a rejection, not a verdict, and a
        # fabricated level here would reintroduce the exact pattern removed
        # from /decision's own error path (a permissive-looking answer on a
        # non-2xx response that a body-trusting caller could mistake for a
        # real decision).
        return JSONResponse(
            status_code=429,
            content={"success": False, "message": "Rate limit exceeded"},
        )

    @app.exception_handler(RejectedAuthException)
    async def rejected_auth_exception_handler(
        request: Request, exc: RejectedAuthException
    ):
        logging.info("RejectedAuthException occurred")
        return JSONResponse(
            status_code=401,
            content={"riskLevel": REJECTED_AUTH_RISK_LEVEL},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logging.error(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": "Internal Server Error"},
        )

    logging.info("Exception handlers initialized")
