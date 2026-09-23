from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.database import DB
from src.core.redis import get_redis
from src.utils.auth.dependency import require_auth
from src.utils.info_provider.ip_intel import report


class HealthRoute:
    def __init__(self):
        self.router = APIRouter()

        self.router.add_api_route(
            "/health",
            self.health_check,
            methods=["GET"],
        )
        # The plain /health above answers liveness for anyone who can reach it
        # (Docker/orchestrator probes, the e2e preflight check, an operator's
        # curl) with no credential required, so it must never carry more than
        # a summary word. The full diagnostic inventory -- absolute filesystem
        # paths, database ages, loaded-category labels, hosting ASN counts --
        # is real reconnaissance value to an attacker and is only available
        # here, behind the same bearer-token check /decision and
        # /params_config already require.
        self.router.add_api_route(
            "/health/detail",
            self.health_detail,
            methods=["GET"],
            dependencies=[Depends(require_auth)],
        )

    async def _check_db_and_redis(self) -> tuple[str, str]:
        db_status = "ok"
        redis_status = "ok"

        try:
            async_session = DB.get_session()
            if not isinstance(async_session, async_sessionmaker):
                raise ValueError("No async database session available")
            async with async_session() as session:
                await session.execute(text("SELECT 1"))
        except Exception:
            db_status = "error"

        try:
            r = get_redis()
            await r.ping()
        except Exception:
            redis_status = "error"

        return db_status, redis_status

    async def health_check(self) -> JSONResponse:
        db_status, redis_status = await self._check_db_and_redis()

        # Readiness depends on the database and Redis only. The IP data block below
        # is reported, never enforced: it describes data files, and a stale or missing
        # one degrades a single risk signal rather than breaking authentication.
        # Failing readiness on it would drain an engine that is authenticating people
        # correctly, and on an air-gapped site that cannot refresh on demand there
        # would be no remedy available.
        all_ok = db_status == "ok" and redis_status == "ok"
        status_code = 200 if all_ok else 503

        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if all_ok else "degraded",
                "db": db_status,
                "redis": redis_status,
                # status_only() swallows its own errors and carries no detail
                # beyond the summary word -- see its docstring and the
                # comment at this router's registration above.
                "ip_data": report.status_only(),
            },
        )

    async def health_detail(self) -> JSONResponse:
        db_status, redis_status = await self._check_db_and_redis()
        all_ok = db_status == "ok" and redis_status == "ok"

        return JSONResponse(
            status_code=200 if all_ok else 503,
            content={
                "status": "ok" if all_ok else "degraded",
                "db": db_status,
                "redis": redis_status,
                # snapshot() swallows its own errors, so this cannot make the
                # endpoint fail. It is the same snapshot the startup log reports.
                "ip_data": report.snapshot(),
            },
        )
