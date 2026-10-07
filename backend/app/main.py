from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1 import auth, portfolio, market, bot, settings as settings_router
from app.db.base import Base
from app.db.session import engine


def create_application() -> FastAPI:
    app = FastAPI(title=settings.APP_NAME, version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(portfolio.router, prefix="/api/v1")
    app.include_router(market.router, prefix="/api/v1")
    app.include_router(bot.router, prefix="/api/v1")
    app.include_router(settings_router.router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup():
        Base.metadata.create_all(bind=engine)
        from app.services.bot_service import bot_orchestrator
        await bot_orchestrator.restore()

    @app.on_event("shutdown")
    async def shutdown():
        from app.services.bot_service import bot_orchestrator
        await bot_orchestrator.shutdown()

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "paper" if not settings.ENABLE_LIVE_TRADING else "live_enabled"}

    return app


app = create_application()
