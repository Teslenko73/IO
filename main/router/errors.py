"""Zamiana wyjątków na odpowiedzi HTTP. Format: {"detail": ...}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError

from main.domain.errors import (
    ConstraintViolation,
    EventNotEditable,
    EventNotFound,
    EventValidationError,
    InvalidStatusTransition,
    ReferenceNotFound,
)

logger = logging.getLogger("main.api")


def _json(status_code: int, detail) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # tylko loc, msg i type per pole; bez echa danych wejściowych
        detail = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return _json(422, detail)

    @app.exception_handler(EventValidationError)
    async def domain_validation(request: Request, exc: EventValidationError):
        return _json(422, str(exc))

    @app.exception_handler(ReferenceNotFound)
    @app.exception_handler(ConstraintViolation)
    async def database_rejected(request: Request, exc: Exception):
        return _json(422, str(exc))

    @app.exception_handler(EventNotFound)
    async def not_found(request: Request, exc: EventNotFound):
        return _json(404, "Nie znaleziono wydarzenia")

    @app.exception_handler(InvalidStatusTransition)
    @app.exception_handler(EventNotEditable)
    async def conflict(request: Request, exc: Exception):
        return _json(409, str(exc))

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    @app.exception_handler(OSError)
    async def database_unavailable(request: Request, exc: Exception):
        logger.error("Baza danych niedostępna: %r", exc)
        return _json(503, "Błąd serwera")

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logger.exception("Nieobsłużony błąd w %s %s", request.method, request.url.path)
        return _json(500, "Błąd serwera")
