from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from main.bd.repo.event import EventRepository
from main.domain.errors import EventNotFound
from main.domain.event import Event, EventStatus
from main.notifications.mail import NotificationKind

_STATUS_KIND = {
    EventStatus.PUBLISHED: NotificationKind.PUBLISHED,
    EventStatus.ARCHIVED: NotificationKind.ARCHIVED,
    EventStatus.CANCELLED: NotificationKind.CANCELLED,
}


@dataclass(frozen=True)
class EventResult:
    """Wynik operacji zapisu: encja plus informacja, jaki mail wysłać (jeśli jakiś)."""

    event: Event
    notification_kind: NotificationKind | None = None
    changes: dict[str, tuple[Any, Any]] = field(default_factory=dict)


class EventService:
    """Scenariusze użycia. Steruje transakcją: commit dopiero po udanym zapisie,
    a mail wysyła router w tle już po commit."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = EventRepository(session)

    async def create(self, values: dict[str, Any]) -> EventResult:
        event = Event(**values)  # domena waliduje jeszcze raz
        saved = await self._repo.add(event)
        await self._session.commit()
        return EventResult(saved, NotificationKind.CREATED)

    async def get(self, event_id: int) -> Event:
        event = await self._repo.get(event_id)
        if event is None:
            raise EventNotFound("Nie znaleziono wydarzenia")
        return event

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
        return await self._repo.list_published(
            category_id=category_id,
            organizer_id=organizer_id,
            starts_from=starts_from,
            starts_to=starts_to,
            limit=limit,
            offset=offset,
        )

    async def update(self, event_id: int, changes: dict[str, Any]) -> EventResult:
        # blokada wiersza chroni przed dwoma równoczesnymi PATCH-ami tego samego wydarzenia
        event = await self._repo.get(event_id, for_update=True)
        if event is None:
            raise EventNotFound("Nie znaleziono wydarzenia")

        diff = event.apply_changes(changes)
        if not diff:  # nic się nie zmieniło: bez UPDATE i bez maila
            await self._session.commit()
            return EventResult(event)

        saved = await self._repo.update(event)
        await self._session.commit()

        # jedno żądanie = najwyżej jeden mail; zmiana statusu ma pierwszeństwo
        if "status" in diff:
            kind = _STATUS_KIND[saved.get_status()]
        else:
            kind = NotificationKind.UPDATED
        return EventResult(saved, kind, diff)
