"""Fixtury testów.

Testy integracyjne działają na prawdziwym PostgreSQL. Ustaw:
    TEST_DATABASE_URL=postgresql+asyncpg://user:haslo@localhost:5432/events_test
Nazwa bazy MUSI zawierać słowo "test": fixture usuwa i tworzy tabele od zera.
Bez TEST_DATABASE_URL testy z bazą są pomijane, a testy domeny działają.
"""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from main.app import create_app
from main.domain.category import CATEGORIES
from main.notifications.mail import MailSender

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

# Schemat sprzed migracji: tabela events dokładnie z pierwszej wersji projektu
# oraz atrapy users i categories (te tabele należą do innych modułów).
SCHEMA_BEFORE_MIGRATION = [
    "CREATE TABLE users (id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY)",
    "CREATE TABLE categories (id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY)",
    "CREATE TYPE event_status AS ENUM ('draft', 'published', 'archived', 'cancelled')",
    "CREATE TYPE event_visibility AS ENUM ('public', 'logged_in')",
    """CREATE TABLE events (
        ID INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        organizer_id INT NOT NULL,
        category_id INT NOT NULL,
        title VARCHAR(200) NOT NULL,
        description text,
        start_time TIMESTAMP NOT NULL,
        end_time TIMESTAMP NOT NULL,
        location VARCHAR(200) NOT NULL,
        speaker VARCHAR(500),
        price DECIMAL(10, 2) NOT NULL DEFAULT 0,
        registration_required BOOL NOT NULL DEFAULT TRUE,
        capacity INT,
        status event_status NOT NULL DEFAULT 'draft',
        visibility event_visibility NOT NULL DEFAULT 'public',
        CONSTRAINT fk_organizer_id FOREIGN KEY(organizer_id) REFERENCES users(id),
        CONSTRAINT fk_category_id FOREIGN KEY(category_id) REFERENCES categories(id),
        CONSTRAINT event_end_time CHECK (end_time > start_time),
        CONSTRAINT event_price CHECK (price >= 0),
        CONSTRAINT event_capacity CHECK (capacity > 0)
    )""",
    "CREATE INDEX idx_start_time ON events(start_time)",
    "CREATE INDEX idx_category_id ON events(category_id)",
]
DROP_ALL = [
    "DROP TABLE IF EXISTS events CASCADE",
    "DROP TABLE IF EXISTS users CASCADE",
    "DROP TABLE IF EXISTS categories CASCADE",
    "DROP TABLE IF EXISTS alembic_version CASCADE",
    "DROP TYPE IF EXISTS event_status",
    "DROP TYPE IF EXISTS event_visibility",
]


def run_alembic(action: str, revision: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    getattr(command, action)(cfg, revision)


@pytest.fixture(scope="session")
def alembic_run():
    """Alembic uruchamia własną pętlę zdarzeń, więc wołamy go w osobnym wątku."""

    async def runner(action: str, revision: str) -> None:
        await asyncio.to_thread(run_alembic, action, revision)

    return runner


@pytest_asyncio.fixture(scope="session")
async def engine(alembic_run):
    if not TEST_DATABASE_URL:
        pytest.skip("Ustaw TEST_DATABASE_URL, żeby uruchomić testy z bazą PostgreSQL")
    db_name = make_url(TEST_DATABASE_URL).database or ""
    if "test" not in db_name.lower():
        pytest.fail(f"Baza {db_name!r} nie wygląda na testową (brak 'test' w nazwie)")

    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        for statement in DROP_ALL + SCHEMA_BEFORE_MIGRATION:
            await conn.execute(text(statement))
    await alembic_run("upgrade", "head")
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id) OVERRIDING SYSTEM VALUE VALUES (1), (2)")
        )
        values = ", ".join(f"({c.id})" for c in CATEGORIES)  # id z naszego katalogu
        await conn.execute(
            text(f"INSERT INTO categories (id) OVERRIDING SYSTEM VALUE VALUES {values}")
        )
    yield engine
    async with engine.begin() as conn:
        for statement in DROP_ALL:
            await conn.execute(text(statement))
    await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(engine):
    """Każdy test działa w transakcji cofanej na końcu. Commit z serwisu
    zamienia się na zwolnienie savepointu (join_transaction_mode)."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        yield conn
        await transaction.rollback()


@dataclass
class SentMail:
    to: str
    subject: str
    body: str


@dataclass
class FakeMailSender(MailSender):
    sent: list[SentMail] = field(default_factory=list)
    fail: bool = False

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise ConnectionError("SMTP niedostępny")
        self.sent.append(SentMail(to, subject, body))


@pytest.fixture
def mail() -> FakeMailSender:
    return FakeMailSender()


@pytest_asyncio.fixture
async def client(db_connection, mail):
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    app = create_app(session_factory=factory, mail_sender=mail)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def payload():
    """Poprawny JSON do POST /events. make(title="x") nadpisuje pola,
    make(drop=["title"]) usuwa pola."""

    def make(drop=(), **overrides):
        data = {
            "organizer_id": 1,
            "category_id": 1,
            "title": "Konferencja Python",
            "description": "Opis wydarzenia",
            "start_time": "2026-12-01T10:00:00+01:00",
            "end_time": "2026-12-01T16:00:00+01:00",
            "location": "Łódź, Manufaktura",
            "speaker": "Jan Kowalski",
            "price": "49.99",
            "registration_required": True,
            "capacity": 100,
            "status": "draft",
            "visibility": "public",
            "email_for_organization": "org@example.com",
        }
        data.update(overrides)
        for key in drop:
            data.pop(key)
        return data

    return make
