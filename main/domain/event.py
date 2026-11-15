"""Encja domenowa Event.

Czysty Python: bez pydantic, bez SQLAlchemy, bez FastAPI. Każdy setter sprawdza
reguły biznesowe, więc obiekt nie może zawierać niepoprawnych danych, skądkolwiek
powstał (router, skrypt, import, test).
"""
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from main.domain.errors import (
    EventNotEditable,
    EventValidationError,
    InvalidStatusTransition,
)

INT_MAX = 2_147_483_647  # górna granica kolumny INT w PostgreSQL
_PRICE_LIMIT = Decimal(10) ** 8  # DECIMAL(10, 2): do 99 999 999,99
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EventStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class EventVisibility(str, Enum):
    PUBLIC = "public"
    LOGGED_IN = "logged_in"


# Dozwolone przejścia statusu. archived i cancelled są końcowe.
ALLOWED_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.DRAFT: frozenset({EventStatus.PUBLISHED, EventStatus.CANCELLED}),
    EventStatus.PUBLISHED: frozenset({EventStatus.ARCHIVED, EventStatus.CANCELLED}),
    EventStatus.ARCHIVED: frozenset(),
    EventStatus.CANCELLED: frozenset(),
}
EDITABLE_STATUSES = frozenset({EventStatus.DRAFT, EventStatus.PUBLISHED})


# ---------- funkcje pomocnicze do walidacji ----------
def _positive_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventValidationError(f"{name} musi być liczbą całkowitą")
    if value <= 0 or value > INT_MAX:
        raise EventValidationError(f"{name} musi być w zakresie 1-{INT_MAX}")
    return value


def _text(name: str, value: Any, max_length: int | None) -> str:
    if not isinstance(value, str):
        raise EventValidationError(f"{name} musi być tekstem")
    value = value.strip()
    if not value:
        raise EventValidationError(f"{name} nie może być pusty")
    if max_length is not None and len(value) > max_length:
        raise EventValidationError(f"{name} może mieć maksymalnie {max_length} znaków")
    return value


def _aware_utc(name: str, value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise EventValidationError(f"{name} musi być typu datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventValidationError(f"{name} musi zawierać strefę czasową")
    return value.astimezone(timezone.utc)


class Event:
    def __init__(
        self,
        organizer_id: int,
        category_id: int,
        title: str,
        description: str,
        start_time: datetime,
        end_time: datetime,
        location: str,
        email_for_organization: str,
        speaker: str | None = None,
        price: Decimal | int | float | str = 0,
        registration_required: bool = True,
        capacity: int | None = None,
        status: EventStatus | str = EventStatus.DRAFT,
        visibility: EventVisibility | str = EventVisibility.PUBLIC,
        id: int | None = None,  # nadaje baza (GENERATED ALWAYS), tu tylko przy odczycie
    ) -> None:
        self._id = None if id is None else _positive_int("id", id)

        # czasy sprawdzamy razem, zanim ustawimy którekolwiek z nich
        self._start_time, self._end_time = self._validate_times(start_time, end_time)

        self.set_organizer_id(organizer_id)
        self.set_category_id(category_id)
        self.set_title(title)
        self.set_description(description)
        self.set_location(location)
        self.set_email_for_organization(email_for_organization)
        self.set_speaker(speaker)
        self.set_price(price)
        self.set_registration_required(registration_required)
        self.set_capacity(capacity)
        self.set_status(status)
        self.set_visibility(visibility)

    # ---------- id (tylko getter, nadaje je baza) ----------
    def get_id(self) -> int | None:
        return self._id

    # ---------- organizer_id ----------
    def get_organizer_id(self) -> int:
        return self._organizer_id

    def set_organizer_id(self, value: int) -> None:
        self._organizer_id = _positive_int("organizer_id", value)

    # ---------- category_id ----------
    def get_category_id(self) -> int:
        return self._category_id

    def set_category_id(self, value: int) -> None:
        self._category_id = _positive_int("category_id", value)

    # ---------- title ----------
    def get_title(self) -> str:
        return self._title

    def set_title(self, value: str) -> None:
        self._title = _text("title", value, 200)

    # ---------- description ----------
    def get_description(self) -> str:
        return self._description

    def set_description(self, value: str) -> None:
        self._description = _text("description", value, None)

    # ---------- start_time / end_time ----------
    @staticmethod
    def _validate_times(start: Any, end: Any) -> tuple[datetime, datetime]:
        start = _aware_utc("start_time", start)
        end = _aware_utc("end_time", end)
        if end <= start:
            raise EventValidationError("end_time musi być późniejszy niż start_time")
        return start, end

    def get_start_time(self) -> datetime:
        return self._start_time

    def set_start_time(self, value: datetime) -> None:
        self._start_time, self._end_time = self._validate_times(value, self._end_time)

    def get_end_time(self) -> datetime:
        return self._end_time

    def set_end_time(self, value: datetime) -> None:
        self._start_time, self._end_time = self._validate_times(self._start_time, value)

    def set_times(self, start: datetime, end: datetime) -> None:
        """Zmiana obu terminów naraz (np. przesunięcie wydarzenia o tydzień)."""
        self._start_time, self._end_time = self._validate_times(start, end)

    # ---------- location ----------
    def get_location(self) -> str:
        return self._location

    def set_location(self, value: str) -> None:
        self._location = _text("location", value, 200)

    # ---------- speaker ----------
    def get_speaker(self) -> str | None:
        return self._speaker

    def set_speaker(self, value: str | None) -> None:
        self._speaker = None if value is None else _text("speaker", value, 500)

    # ---------- price ----------
    def get_price(self) -> Decimal:
        return self._price

    def set_price(self, value: Decimal | int | float | str) -> None:
        if value is None or isinstance(value, bool):
            raise EventValidationError("price musi być liczbą")
        try:
            price = Decimal(str(value))
        except InvalidOperation:
            raise EventValidationError("price musi być liczbą")
        if not price.is_finite():
            raise EventValidationError("price musi być skończoną liczbą")
        if price < 0:
            raise EventValidationError("price musi być >= 0")
        rounded = price.quantize(Decimal("0.01"))
        if price != rounded:
            raise EventValidationError("price może mieć maksymalnie 2 miejsca po przecinku")
        if rounded >= _PRICE_LIMIT:
            raise EventValidationError("price jest zbyt duża")
        self._price = rounded

    # ---------- registration_required ----------
    def get_registration_required(self) -> bool:
        return self._registration_required

    def set_registration_required(self, value: bool) -> None:
        if not isinstance(value, bool):
            raise EventValidationError("registration_required musi być typu bool")
        self._registration_required = value

    # ---------- capacity ----------
    def get_capacity(self) -> int | None:
        return self._capacity

    def set_capacity(self, value: int | None) -> None:
        self._capacity = None if value is None else _positive_int("capacity", value)

    # ---------- status ----------
    def get_status(self) -> EventStatus:
        return self._status

    def set_status(self, value: EventStatus | str) -> None:
        """Ustawia status bez sprawdzania przejść (odczyt z bazy).

        Zmiany z regułami cyklu życia robi change_status().
        """
        self._status = self._parse_status(value)

    @staticmethod
    def _parse_status(value: Any) -> EventStatus:
        try:
            return EventStatus(value)
        except ValueError:
            raise EventValidationError(f"niepoprawny status: {value!r}")

    # ---------- visibility ----------
    def get_visibility(self) -> EventVisibility:
        return self._visibility

    def set_visibility(self, value: EventVisibility | str) -> None:
        try:
            self._visibility = EventVisibility(value)
        except ValueError:
            raise EventValidationError(f"niepoprawna widoczność: {value!r}")

    # ---------- email_for_organization ----------
    def get_email_for_organization(self) -> str:
        return self._email_for_organization

    def set_email_for_organization(self, value: str) -> None:
        value = _text("email_for_organization", value, 254)
        if not _EMAIL_RE.match(value):
            raise EventValidationError("email_for_organization ma niepoprawny format")
        self._email_for_organization = value

    # ---------- reguły cyklu życia ----------
    def is_editable(self) -> bool:
        return self._status in EDITABLE_STATUSES

    def change_status(self, new_status: EventStatus | str) -> bool:
        """Zmienia status według ALLOWED_TRANSITIONS.

        Zwraca True, gdy status się zmienił, False, gdy nowy równa się obecnemu.
        """
        target = self._parse_status(new_status)
        if target == self._status:
            return False
        if target not in ALLOWED_TRANSITIONS[self._status]:
            raise InvalidStatusTransition(
                f"Niedozwolona zmiana statusu: {self._status.value} -> {target.value}"
            )
        self._status = target
        return True

    # ---------- zmiana wielu pól naraz (PATCH) ----------
    _SIMPLE_FIELDS = frozenset(
        {
            "organizer_id", "category_id", "title", "description", "location",
            "speaker", "price", "registration_required", "capacity",
            "visibility", "email_for_organization",
        }
    )

    def snapshot(self) -> dict[str, Any]:
        """Wszystkie pola poza id, do porównywania stanu przed i po zmianie."""
        return {
            "organizer_id": self._organizer_id,
            "category_id": self._category_id,
            "title": self._title,
            "description": self._description,
            "start_time": self._start_time,
            "end_time": self._end_time,
            "location": self._location,
            "speaker": self._speaker,
            "price": self._price,
            "registration_required": self._registration_required,
            "capacity": self._capacity,
            "status": self._status,
            "visibility": self._visibility,
            "email_for_organization": self._email_for_organization,
        }

    def apply_changes(self, changes: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
        """Stosuje częściową zmianę. Zwraca {pole: (przed, po)} tylko dla pól,
        które faktycznie się zmieniły.

        Rzuca EventNotEditable dla wydarzeń archived i cancelled,
        InvalidStatusTransition przy złym przejściu statusu oraz
        EventValidationError przy złych wartościach. Przy błędzie obiekt może być
        częściowo zmieniony, więc wywołujący odrzuca go razem z transakcją.
        """
        if not changes:
            return {}
        if not self.is_editable():
            raise EventNotEditable(
                f"Wydarzenie ma status {self._status.value} i jest tylko do odczytu"
            )

        changes = dict(changes)
        new_status = changes.pop("status", None)
        has_times = "start_time" in changes or "end_time" in changes
        start = changes.pop("start_time", self._start_time)
        end = changes.pop("end_time", self._end_time)
        unknown = set(changes) - self._SIMPLE_FIELDS
        if unknown:
            raise EventValidationError(f"Nieznane pola: {', '.join(sorted(unknown))}")

        # status sprawdzamy najpierw, żeby zły status nie zmienił nic po drodze
        target = None
        if new_status is not None:
            target = self._parse_status(new_status)
            if target != self._status and target not in ALLOWED_TRANSITIONS[self._status]:
                raise InvalidStatusTransition(
                    f"Niedozwolona zmiana statusu: {self._status.value} -> {target.value}"
                )

        before = self.snapshot()
        if has_times:
            self.set_times(start, end)
        for name, value in changes.items():
            getattr(self, f"set_{name}")(value)
        if target is not None:
            self.change_status(target)

        after = self.snapshot()
        return {k: (before[k], after[k]) for k in after if before[k] != after[k]}

    def __repr__(self) -> str:
        return (
            f"Event(id={self._id}, title={self._title!r}, "
            f"start_time={self._start_time.isoformat()}, "
            f"end_time={self._end_time.isoformat()}, status={self._status.value!r})"
        )
