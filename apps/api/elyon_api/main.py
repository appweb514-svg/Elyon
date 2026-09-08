from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from elyon_api.config import Settings
from elyon_api.db import build_session_factory
from elyon_api.routers import (
    auth,
    content,
    enroll,
    groups,
    lab,
    media,
    ops,
    publish,
    sites,
    teams,
    triggers,
    users,
)

settings = Settings()


def migrate(settings: Settings) -> None:
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(alembic_cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    app.state.session_factory = build_session_factory(settings)
    if settings.auto_migrate:
        migrate(settings)
    # Purge de la corbeille (>30 jours) au démarrage puis toutes les 6 h.
    import asyncio

    from elyon_api.services.trash import purge_expired_trash

    async def _trash_sweeper() -> None:
        from elyon_api.services.alerts import sweep_offline_alerts

        while True:
            try:
                purge_expired_trash(app.state.session_factory, app.state.settings)
                sweep_offline_alerts(app.state.session_factory, app.state.settings)
            except Exception:  # noqa: BLE001 — jamais bloquant
                pass
            await asyncio.sleep(60 if app.state.settings.alert_smtp_host else 6 * 3600)

    sweeper = asyncio.create_task(_trash_sweeper())
    try:
        yield
    finally:
        sweeper.cancel()


def create_app(app_settings: Settings | None = None, run_migrations: bool = True) -> FastAPI:
    app_settings = app_settings or Settings()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        app.state.settings = app_settings
        app.state.session_factory = build_session_factory(app_settings)
        if run_migrations:
            migrate(app_settings)
        yield

    application = FastAPI(title="Elyon API", lifespan=_lifespan)
    application.state.settings = app_settings
    application.state.session_factory = build_session_factory(app_settings)

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        return response

    @application.middleware("http")
    async def csrf_protection(request: Request, call_next):
        method = request.method.upper()
        exempt = {
            "/api/enroll/request",
            "/api/auth/bootstrap",
            "/api/auth/login",
            "/api/server/public-key",
        }
        csrf_required = (
            method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.url.path.startswith("/api")
            and request.url.path not in exempt
            and not request.url.path.startswith("/api/trigger/")
            and not request.headers.get("Authorization", "").startswith("Bearer ")
        )
        if csrf_required:
            csrf_cookie = request.cookies.get(app_settings.csrf_cookie_name)
            csrf_header = request.headers.get("X-CSRF-Token")
            if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
                return JSONResponse(status_code=403, content={"detail": "Jeton CSRF invalide"})
        return await call_next(request)

    application.include_router(auth.router)
    application.include_router(users.router)
    application.include_router(sites.router)
    application.include_router(enroll.router)
    application.include_router(groups.router)
    application.include_router(lab.router)
    application.include_router(triggers.router)
    application.include_router(media.router)
    application.include_router(teams.router)
    application.include_router(content.router)
    application.include_router(publish.router)
    application.include_router(ops.router)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @application.get("/api/server/public-key")
    def server_public_key(request: Request) -> dict[str, str]:
        from elyon_api.services.signing import load_or_create_signing_key, public_key_pem

        private_key = load_or_create_signing_key(request.app.state.settings)
        return {"public_key_pem": public_key_pem(private_key)}

    return application


app = create_app()