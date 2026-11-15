"""Punkt wejścia: uvicorn main.app:app"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from main.bd.session import create_session_factory
from main.config import (
    Settings,
    cors_origins_from_env,
    mail_timezone_from_env,
)
from main.notifications.mail import MailSender, Notifier, build_mail_sender
from main.router import categories_router, events_router
from main.router.errors import register_exception_handlers


def create_app(
    *,
    settings: Settings | None = None,
    session_factory=None,
    mail_sender: MailSender | None = None,
) -> FastAPI:
    """Fabryka aplikacji. Bez argumentów bierze konfigurację ze zmiennych
    środowiskowych przy starcie serwera; testy wstrzykują własną sesję i atrapę maila."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = None
        cfg = settings
        if session_factory is None:
            cfg = cfg or Settings.from_env()
            engine, app.state.session_factory = create_session_factory(cfg.database_url)
        if mail_sender is None:
            cfg = cfg or Settings.from_env()
            app.state.notifier = Notifier(build_mail_sender(cfg), mail_timezone_from_env())
        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title="Events API", version="1.0.0", lifespan=lifespan)
    if session_factory is not None:
        app.state.session_factory = session_factory
    if mail_sender is not None:
        app.state.notifier = Notifier(mail_sender, mail_timezone_from_env())

    origins = cors_origins_from_env()
    if origins:  # potrzebne, gdy formularz działa na innej domenie niż API
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)
    app.include_router(categories_router)
    app.include_router(events_router)
    return app


app = create_app()
