"""Wpisuje kategorie z main/domain/category.py do tabeli categories.

Uruchomienie (po alembic upgrade head, z ustawionym DATABASE_URL):
    python -m main.bd.seed

Można uruchamiać wielokrotnie: istniejące wiersze są aktualizowane, a nie dublowane.
Tabela categories należy do innego modułu, więc skrypt sprawdza, czy ma kolumnę
name: jeśli tak, wpisuje id i nazwę, jeśli nie, tylko id.
"""
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from main.bd.session import create_session_factory
from main.config import database_url_from_env
from main.domain.category import CATEGORIES

_HAS_NAME = text(
    "SELECT 1 FROM information_schema.columns "
    "WHERE table_schema = current_schema() "
    "AND table_name = 'categories' AND column_name = 'name'"
)
_UPSERT_WITH_NAME = text(
    "INSERT INTO categories (id, name) OVERRIDING SYSTEM VALUE VALUES (:id, :name) "
    "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"
)
_INSERT_ID_ONLY = text(
    "INSERT INTO categories (id) OVERRIDING SYSTEM VALUE VALUES (:id) "
    "ON CONFLICT (id) DO NOTHING"
)
# po wpisaniu id ręcznie licznik (sekwencja) sam się nie przesuwa; bez tego
# następna kategoria dodana bez podania id dostałaby numer, który już istnieje
_SYNC_SEQUENCE = text(
    "SELECT setval(pg_get_serial_sequence('categories', 'id'), "
    "(SELECT max(id) FROM categories))"
)


async def seed_categories(session: AsyncSession) -> int:
    """Zasila tabelę categories. Nie robi commit. Zwraca liczbę kategorii."""
    has_name = (await session.execute(_HAS_NAME)).first() is not None
    for category in CATEGORIES:
        if has_name:
            await session.execute(
                _UPSERT_WITH_NAME, {"id": category.id, "name": category.name}
            )
        else:
            await session.execute(_INSERT_ID_ONLY, {"id": category.id})
    await session.execute(_SYNC_SEQUENCE)
    return len(CATEGORIES)


async def _main() -> int:
    engine, factory = create_session_factory(database_url_from_env())
    try:
        async with factory() as session:
            count = await seed_categories(session)
            await session.commit()
        print(f"Zapisano kategorie w tabeli categories: {count}")
        return 0
    except DBAPIError as exc:
        print(
            "Nie udało się zapisać kategorii. Tabela categories może mieć dodatkowe "
            "wymagane kolumny. Wtedy wpisz wiersze ręcznie (id i nazwy z "
            f"main/domain/category.py).\nSzczegóły: {exc.orig}",
            file=sys.stderr,
        )
        return 1
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
