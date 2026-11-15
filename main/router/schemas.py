"""Kontrakt API: dokładnie te pola i typy, które przyjmuje i zwraca moduł Event.

Wejście jest ścisłe: nieznane pola są odrzucane (extra="forbid"), liczby całkowite
i flagi muszą być prawdziwymi liczbami i boolami (nie "1" ani "true" w cudzysłowie),
a daty muszą być napisami ISO 8601 ze strefą czasową.
"""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from main.domain.category import available_ids_text, get_category
from main.domain.event import INT_MAX, Event, EventStatus, EventVisibility


# ---------- typy wielokrotnego użytku ----------
def _iso_string_only(value: Any) -> Any:
    if not isinstance(value, str):
        raise ValueError("data musi być napisem w formacie ISO 8601 ze strefą czasową")
    return value


def _reject_bool(value: Any) -> Any:
    if isinstance(value, bool):
        raise ValueError("wartość musi być liczbą")
    return value


def _max_254(value: str) -> str:
    if len(value) > 254:
        raise ValueError("adres może mieć maksymalnie 254 znaki")
    return value


def _known_category(value: int) -> int:
    if get_category(value) is None:
        raise ValueError(f"nieznana kategoria (dostępne id: {available_ids_text()})")
    return value


def _text(max_length: int | None):
    return Annotated[
        str,
        StringConstraints(
            strict=True, strip_whitespace=True, min_length=1, max_length=max_length
        ),
    ]


Id = Annotated[StrictInt, Field(gt=0, le=INT_MAX)]
# id kategorii musi być z katalogu w main/domain/category.py
CategoryId = Annotated[
    StrictInt, Field(gt=0, le=INT_MAX), AfterValidator(_known_category)
]
Title = _text(200)
Location = _text(200)
Description = _text(None)
Speaker = _text(500)
Capacity = Annotated[StrictInt, Field(gt=0, le=INT_MAX)]
Price = Annotated[
    Decimal,
    BeforeValidator(_reject_bool),
    Field(ge=0, max_digits=10, decimal_places=2),
]
IsoDatetime = Annotated[AwareDatetime, BeforeValidator(_iso_string_only)]
Email = Annotated[EmailStr, AfterValidator(_max_254)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- wejście: POST /events ----------
class EventCreate(_Input):
    organizer_id: Id
    category_id: CategoryId
    title: Title
    description: Description
    start_time: IsoDatetime
    end_time: IsoDatetime
    location: Location
    email_for_organization: Email
    speaker: Speaker | None = None
    price: Price = Decimal("0")
    registration_required: StrictBool = True
    capacity: Capacity | None = None
    status: EventStatus = EventStatus.DRAFT
    visibility: EventVisibility = EventVisibility.PUBLIC

    @field_validator("status")
    @classmethod
    def _creation_status(cls, value: EventStatus) -> EventStatus:
        if value not in (EventStatus.DRAFT, EventStatus.PUBLISHED):
            raise ValueError("przy tworzeniu status może być tylko draft lub published")
        return value

    @model_validator(mode="after")
    def _check_times(self) -> "EventCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time musi być późniejszy niż start_time")
        return self


# ---------- wejście: PATCH /events/{id} ----------
# pola, które w bazie są NOT NULL, więc nie wolno ich ustawić na null
_NON_NULLABLE = (
    "organizer_id", "category_id", "title", "description", "start_time", "end_time",
    "location", "email_for_organization", "price", "registration_required",
    "status", "visibility",
)


class EventUpdate(_Input):
    organizer_id: Id | None = None
    category_id: CategoryId | None = None
    title: Title | None = None
    description: Description | None = None
    start_time: IsoDatetime | None = None
    end_time: IsoDatetime | None = None
    location: Location | None = None
    email_for_organization: Email | None = None
    speaker: Speaker | None = None  # null dozwolony: kasuje prelegenta
    price: Price | None = None
    registration_required: StrictBool | None = None
    capacity: Capacity | None = None  # null dozwolony: brak limitu miejsc
    status: EventStatus | None = None
    visibility: EventVisibility | None = None

    @field_validator(*_NON_NULLABLE, mode="before")
    @classmethod
    def _no_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("to pole nie może być null")
        return value

    @model_validator(mode="after")
    def _check(self) -> "EventUpdate":
        if not self.model_fields_set:
            raise ValueError("PATCH wymaga co najmniej jednego pola")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("end_time musi być późniejszy niż start_time")
        return self


# ---------- wejście: parametry GET /events ----------
class EventFilters(_Input):
    category_id: (
        Annotated[int, Field(gt=0, le=INT_MAX), AfterValidator(_known_category)] | None
    ) = None
    organizer_id: Annotated[int, Field(gt=0, le=INT_MAX)] | None = None
    starts_from: AwareDatetime | None = None
    starts_to: AwareDatetime | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 20
    offset: Annotated[int, Field(ge=0, le=INT_MAX)] = 0

    @model_validator(mode="after")
    def _check(self) -> "EventFilters":
        if self.starts_from and self.starts_to and self.starts_to < self.starts_from:
            raise ValueError("starts_to nie może być wcześniejsze niż starts_from")
        return self


# ---------- wyjście ----------
class EventOut(BaseModel):
    """Odpowiedź. email_for_organization celowo nie jest zwracany (lista jest publiczna)."""

    id: int
    organizer_id: int
    category_id: int
    category_name: str | None  # nazwa z katalogu kategorii; null, gdy id nie ma w katalogu
    title: str
    description: str
    start_time: datetime
    end_time: datetime
    location: str
    speaker: str | None
    price: Decimal  # w JSON jako napis, np. "49.99"
    registration_required: bool
    capacity: int | None
    status: EventStatus
    visibility: EventVisibility

    @classmethod
    def from_domain(cls, event: Event) -> "EventOut":
        category = get_category(event.get_category_id())
        return cls(
            id=event.get_id(),
            organizer_id=event.get_organizer_id(),
            category_id=event.get_category_id(),
            category_name=category.name if category else None,
            title=event.get_title(),
            description=event.get_description(),
            start_time=event.get_start_time(),
            end_time=event.get_end_time(),
            location=event.get_location(),
            speaker=event.get_speaker(),
            price=event.get_price(),
            registration_required=event.get_registration_required(),
            capacity=event.get_capacity(),
            status=event.get_status(),
            visibility=event.get_visibility(),
        )


class EventList(BaseModel):
    items: list[EventOut]
    total: int
    limit: int
    offset: int


class CategoryOut(BaseModel):
    id: int
    name: str


class CategoryList(BaseModel):
    items: list[CategoryOut]
    total: int
