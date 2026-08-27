from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status
from sqlalchemy.ext.asyncio import AsyncEngine

from blackbread import __version__
from blackbread.config import Settings, get_settings
from blackbread.database import create_engine
from blackbread.health import check_readiness


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    app_engine = engine or create_engine(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await app_engine.dispose()

    app = FastAPI(title="BlackBread", version=__version__, lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "alive", "version": __version__}

    @app.get("/health/ready")
    async def ready(response: Response) -> dict[str, str]:
        readiness = await check_readiness(app_engine)
        if not readiness.ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "ready" if readiness.ready else "not_ready",
            "database": readiness.database,
            "migrations": readiness.migrations,
        }

    return app


app = create_app()
