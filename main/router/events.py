from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from main.domain.event import INT_MAX
from main.notifications.mail import Notifier
from main.router.schemas import (
    EventCreate,
    EventFilters,
    EventList,
    EventOut,
    EventUpdate,
)
from main.service.event_service import EventResult, EventService

PREFIX = "/api/v1/events"
router = APIRouter(prefix=PREFIX, tags=["events"])


# ---------- zależności ----------
async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session  # zamknięcie sesji cofa niezatwierdzone zmiany


def get_notifier(request: Request) -> Notifier:
    return request.app.state.notifier


def get_service(session: Annotated[AsyncSession, Depends(get_session)]) -> EventService:
    return EventService(session)


ServiceDep = Annotated[EventService, Depends(get_service)]
NotifierDep = Annotated[Notifier, Depends(get_notifier)]
EventId = Annotated[int, Path(gt=0, le=INT_MAX)]


def _schedule_mail(
    background: BackgroundTasks, notifier: NotifierDep, result: EventResult
) -> None:
    """Mail idzie w tle, po wysłaniu odpowiedzi i po commit w bazie."""
    if result.notification_kind is not None:
        background.add_task(
            notifier.notify, result.notification_kind, result.event, result.changes
        )


# ---------- endpointy ----------
@router.post("", response_model=EventOut, status_code=201)
async def create_event(
    payload: EventCreate,
    response: Response,
    background: BackgroundTasks,
    service: ServiceDep,
    notifier: NotifierDep,
) -> EventOut:
    result = await service.create(payload.model_dump())
    response.headers["Location"] = f"{PREFIX}/{result.event.get_id()}"
    _schedule_mail(background, notifier, result)
    return EventOut.from_domain(result.event)


@router.get("", response_model=EventList)
async def list_events(
    filters: Annotated[EventFilters, Query()], service: ServiceDep
) -> EventList:
    """Tylko wydarzenia opublikowane, rosnąco po start_time."""
    events, total = await service.list_published(
        category_id=filters.category_id,
        organizer_id=filters.organizer_id,
        starts_from=filters.starts_from,
        starts_to=filters.starts_to,
        limit=filters.limit,
        offset=filters.offset,
    )
    return EventList(
        items=[EventOut.from_domain(e) for e in events],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: EventId, service: ServiceDep) -> EventOut:
    """Zwraca wydarzenie w każdym statusie, żeby dało się nim zarządzać."""
    return EventOut.from_domain(await service.get(event_id))


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: EventId,
    payload: EventUpdate,
    background: BackgroundTasks,
    service: ServiceDep,
    notifier: NotifierDep,
) -> EventOut:
    result = await service.update(event_id, payload.model_dump(exclude_unset=True))
    _schedule_mail(background, notifier, result)
    return EventOut.from_domain(result.event)
