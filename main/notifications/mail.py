"""Powiadomienia mailowe do organizatora wydarzenia."""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from email.message import EmailMessage
from enum import Enum
from typing import Any

import aiosmtplib

from main.config import Settings
from main.domain.event import Event

logger = logging.getLogger("main.notifications")


class NotificationKind(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


_SUBJECTS = {
    NotificationKind.CREATED: "Utworzono wydarzenie: {title}",
    NotificationKind.UPDATED: "Zmieniono wydarzenie: {title}",
    NotificationKind.PUBLISHED: "Opublikowano wydarzenie: {title}",
    NotificationKind.ARCHIVED: "Zarchiwizowano wydarzenie: {title}",
    NotificationKind.CANCELLED: "Anulowano wydarzenie: {title}",
}
_INTROS = {
    NotificationKind.CREATED: "Wydarzenie zostało utworzone.",
    NotificationKind.UPDATED: "Wydarzenie zostało zmienione.",
    NotificationKind.PUBLISHED: "Wydarzenie zostało opublikowane.",
    NotificationKind.ARCHIVED: "Wydarzenie zostało zarchiwizowane.",
    NotificationKind.CANCELLED: "Wydarzenie zostało anulowane.",
}
_LABELS = {
    "organizer_id": "Organizator (id)",
    "category_id": "Kategoria (id)",
    "title": "Tytuł",
    "description": "Opis",
    "start_time": "Początek",
    "end_time": "Koniec",
    "location": "Miejsce",
    "speaker": "Prelegent",
    "price": "Cena",
    "registration_required": "Wymagana rejestracja",
    "capacity": "Liczba miejsc",
    "status": "Status",
    "visibility": "Widoczność",
    "email_for_organization": "E-mail organizatora",
}


@dataclass(frozen=True)
class Notification:
    to: str
    subject: str
    body: str


def _format_value(value: Any, tz: tzinfo) -> str:
    if value is None:
        return "(brak)"
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M (%Z)")
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "tak" if value else "nie"
    text = str(value)
    return text if len(text) <= 200 else text[:197] + "..."


def build_notification(
    kind: NotificationKind,
    event: Event,
    changes: dict[str, tuple[Any, Any]] | None = None,
    tz: tzinfo = timezone.utc,
) -> Notification:
    """Składa temat i treść maila. Odbiorca to email_for_organization po zmianie."""
    title = " ".join(event.get_title().split())  # bez złamań linii w nagłówku
    lines = [
        _INTROS[kind],
        "",
        f"Tytuł: {event.get_title()}",
        f"Termin: {_format_value(event.get_start_time(), tz)} - "
        f"{_format_value(event.get_end_time(), tz)}",
        f"Miejsce: {event.get_location()}",
        f"Status: {event.get_status().value}",
    ]
    if kind is not NotificationKind.CREATED and changes:
        lines += ["", "Zmienione pola:"]
        for name, (before, after) in changes.items():
            label = _LABELS.get(name, name)
            lines.append(
                f"- {label}: {_format_value(before, tz)} -> {_format_value(after, tz)}"
            )
    return Notification(
        to=event.get_email_for_organization(),
        subject=_SUBJECTS[kind].format(title=title),
        body="\n".join(lines) + "\n",
    )


class MailSender(ABC):
    """Interfejs wysyłki. W testach podmieniamy go atrapą."""

    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailSender(MailSender):
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._s.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        # port 465 = TLS od razu, pozostałe porty z SMTP_TLS=true = STARTTLS
        implicit_tls = self._s.smtp_tls and self._s.smtp_port == 465
        start_tls = self._s.smtp_tls and not implicit_tls
        await aiosmtplib.send(
            message,
            hostname=self._s.smtp_host,
            port=self._s.smtp_port,
            username=self._s.smtp_user,
            password=self._s.smtp_password,
            use_tls=implicit_tls,
            start_tls=start_tls,
            timeout=10,
        )


class NullMailSender(MailSender):
    """Używany, gdy SMTP_HOST nie jest ustawiony (np. lokalny development)."""

    async def send(self, to: str, subject: str, body: str) -> None:
        logger.warning("SMTP nie jest skonfigurowany, pomijam mail do %s: %s", to, subject)


def build_mail_sender(settings: Settings) -> MailSender:
    return SmtpMailSender(settings) if settings.smtp_host else NullMailSender()


class Notifier:
    """Buduje i wysyła powiadomienie. Błąd wysyłki jest tylko logowany (ERROR),
    więc nie psuje odpowiedzi API."""

    def __init__(self, sender: MailSender, tz: tzinfo = timezone.utc) -> None:
        self._sender = sender
        self._tz = tz

    async def notify(
        self,
        kind: NotificationKind,
        event: Event,
        changes: dict[str, tuple[Any, Any]] | None = None,
    ) -> None:
        try:
            n = build_notification(kind, event, changes, self._tz)
            await self._sender.send(n.to, n.subject, n.body)
        except Exception:
            logger.exception(
                "Nie udało się wysłać maila (event_id=%s, rodzaj=%s)",
                event.get_id(),
                kind.value,
            )
