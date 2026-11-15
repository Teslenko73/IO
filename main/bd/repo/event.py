from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from main.bd.maper.event import apply_to_model, to_domain, to_model
from main.bd.modle.event import EventModel
from main.domain.errors import ConstraintViolation, EventNotFound, ReferenceNotFound
from main.domain.event import Event, EventStatus

_FK_FIELDS = {"fk_organizer_id": "organizer_id", "fk_category_id": "category_id"}


def _translate(exc: IntegrityError) -> Exception:
    """Zamienia błąd bazy na wyjątek domenowy (kody SQLSTATE: 23503 = klucz obcy)."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23503":
        cause = getattr(exc.orig, "__cause__", None)
        field = _FK_FIELDS.get(getattr(cause, "constraint_name", None))
        if field:
            return ReferenceNotFound(f"{field} wskazuje na nieistniejący rekord")
        return ReferenceNotFound(
            "organizer_id lub category_id wskazuje na nieistniejący rekord"
        )
    return ConstraintViolation("Dane naruszają ograniczenia bazy danych")


class EventRepository:
    """Zapis i odczyt wydarzeń. Przyjmuje i zwraca encje Event, nie modele ORM.
    Nie robi commit, bo transakcją steruje serwis."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: Event) -> Event:
        model = to_model(event)
        self._session.add(model)
        try:
            await self._session.flush()  # id nadaje baza (RETURNING)
        except IntegrityError as exc:
            raise _translate(exc) from exc
        return to_domain(model)

    async def get(self, event_id: int, *, for_update: bool = False) -> Event | None:
        stmt = select(EventModel).where(EventModel.id == event_id)
        if for_update:
            stmt = stmt.with_for_update()  # blokada wiersza do końca transakcji
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return None if model is None else to_domain(model)

    async def update(self, event: Event) -> Event:
        # wiersz jest już w sesji po get(), więc session.get nie robi zapytania
        model = await self._session.get(EventModel, event.get_id())
        if model is None:
            raise EventNotFound("Nie znaleziono wydarzenia")
        apply_to_model(event, model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise _translate(exc) from exc
        return to_domain(model)

    async def list_published(
        self,
        *,
        category_id: int | None,
        organizer_id: int | None,
        starts_from: datetime | None,
        starts_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Event], int]:
        conditions = [EventModel.status == EventStatus.PUBLISHED]
        if category_id is not None:
            conditions.append(EventModel.category_id == category_id)
        if organizer_id is not None:
            conditions.append(EventModel.organizer_id == organizer_id)
        if starts_from is not None:
            conditions.append(EventModel.start_time >= starts_from)
        if starts_to is not None:
            conditions.append(EventModel.start_time <= starts_to)

        total = (
            await self._session.execute(
                select(func.count()).select_from(EventModel).where(*conditions)
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                select(EventModel)
                .where(*conditions)
                .order_by(EventModel.start_time, EventModel.id)
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
        return [to_domain(row) for row in rows], total
