from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from main.bd.base import Base
from main.domain.event import EventStatus, EventVisibility


def _pg_enum(enum_cls: type, name: str) -> ENUM:
    # typy ENUM istnieją już w bazie (tworzy je migracja), więc create_type=False;
    # values_callable zapisuje wartości ("draft"), a nie nazwy ("DRAFT")
    return ENUM(
        enum_cls,
        name=name,
        create_type=False,
        values_callable=lambda e: [member.value for member in e],
    )


class EventModel(Base):
    """Wiersz tabeli events. Nie zawiera logiki, tylko odwzorowanie kolumn."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Identity(always=True), primary_key=True)
    # Klucze obce fk_organizer_id (users.id) i fk_category_id (categories.id) istnieją
    # w bazie i to ona je pilnuje. Tu są zwykłe kolumny, bo modele User i Category
    # należą do innych modułów. Gdy trafią do tego samego Base, można dopisać
    # ForeignKey("users.id", name="fk_organizer_id") itd.
    organizer_id: Mapped[int] = mapped_column(nullable=False)
    category_id: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[str] = mapped_column(String(200), nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(500))
    price: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default="0"
    )
    registration_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    capacity: Mapped[int | None] = mapped_column()
    status: Mapped[EventStatus] = mapped_column(
        _pg_enum(EventStatus, "event_status"), nullable=False, server_default="draft"
    )
    visibility: Mapped[EventVisibility] = mapped_column(
        _pg_enum(EventVisibility, "event_visibility"),
        nullable=False,
        server_default="public",
    )
    email_for_organization: Mapped[str] = mapped_column(String(254), nullable=False)

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="event_end_time"),
        CheckConstraint("price >= 0", name="event_price"),
        CheckConstraint("capacity > 0", name="event_capacity"),
        Index("idx_start_time", "start_time"),
        Index("idx_category_id", "category_id"),
        Index("idx_organizer_id", "organizer_id"),
        Index("idx_status_start_time", "status", "start_time"),
    )
