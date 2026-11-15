"""Katalog kategorii: endpointy, walidacja category_id i zasilanie tabeli."""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from main.bd.seed import seed_categories
from main.domain.category import CATEGORIES, all_categories, get_category

EVENTS = "/api/v1/events"
CATEGORIES_API = "/api/v1/categories"


# ---------- katalog (bez bazy) ----------
def test_catalogue_ids_are_unique_positive_and_start_at_one():
    ids = [c.id for c in CATEGORIES]
    assert len(ids) == len(set(ids))
    assert min(ids) == 1  # id 0 nie jest dozwolone


def test_get_category():
    assert get_category(1).name == "Naukowe"
    assert get_category(0) is None
    assert get_category(999) is None


def test_all_categories_sorted_by_id():
    ids = [c.id for c in all_categories()]
    assert ids == sorted(ids)


# ---------- endpointy ----------
async def test_list_categories(client):
    r = await client.get(CATEGORIES_API)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == len(CATEGORIES)
    assert body["items"][0] == {"id": 1, "name": "Naukowe"}
    assert [c["id"] for c in body["items"]] == sorted(c.id for c in CATEGORIES)


async def test_get_category_by_id(client):
    r = await client.get(f"{CATEGORIES_API}/2")
    assert r.status_code == 200
    assert r.json() == {"id": 2, "name": "Konferencja"}


async def test_get_unknown_category_returns_404(client):
    r = await client.get(f"{CATEGORIES_API}/999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Nie znaleziono kategorii"}


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", str(2**31)])
async def test_get_category_rejects_bad_id(client, bad_id):
    r = await client.get(f"{CATEGORIES_API}/{bad_id}")
    assert r.status_code == 422


async def test_categories_are_read_only(client):
    for method in ("post", "patch", "put", "delete"):
        r = await getattr(client, method)(f"{CATEGORIES_API}/1")
        assert r.status_code == 405, method


# ---------- kategoria w wydarzeniach ----------
async def test_patch_category_changes_name_and_validates(client, payload):
    created = (await client.post(EVENTS, json=payload(category_id=1))).json()
    assert created["category_name"] == "Naukowe"

    r = await client.patch(f"{EVENTS}/{created['id']}", json={"category_id": 4})
    assert r.status_code == 200
    assert (r.json()["category_id"], r.json()["category_name"]) == (4, "Szkolenie")

    r = await client.patch(f"{EVENTS}/{created['id']}", json={"category_id": 999})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "category_id"]


async def test_event_read_shows_category_name(client, payload):
    created = (await client.post(EVENTS, json=payload(category_id=5, status="published"))).json()
    one = (await client.get(f"{EVENTS}/{created['id']}")).json()
    listed = (await client.get(EVENTS)).json()["items"][0]
    assert one["category_name"] == listed["category_name"] == "Spotkanie"


# ---------- skrypt zasilający tabelę categories ----------
async def _rows(conn):
    result = await conn.execute(text("SELECT id FROM categories ORDER BY id"))
    return [r[0] for r in result]


async def test_seed_fills_missing_ids_and_is_idempotent(db_connection):
    await db_connection.execute(text("DELETE FROM categories"))
    async with AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        assert await seed_categories(session) == len(CATEGORIES)
        await seed_categories(session)  # drugi raz nic nie dubluje
        await session.commit()
    assert await _rows(db_connection) == sorted(c.id for c in CATEGORIES)


async def test_seed_writes_names_when_table_has_name_column(db_connection):
    # DDL w PostgreSQL jest transakcyjne, więc zmiana cofnie się razem z testem
    await db_connection.execute(text("DELETE FROM categories"))
    await db_connection.execute(text("ALTER TABLE categories ADD COLUMN name text"))
    async with AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        await seed_categories(session)
        await session.commit()
    rows = (await db_connection.execute(text("SELECT id, name FROM categories ORDER BY id"))).all()
    assert rows == [(c.id, c.name) for c in all_categories()]


async def test_seed_moves_sequence_so_next_insert_gets_free_id(db_connection):
    await db_connection.execute(text("DELETE FROM categories"))
    async with AsyncSession(
        bind=db_connection, join_transaction_mode="create_savepoint"
    ) as session:
        await seed_categories(session)
        await session.commit()
    new_id = (
        await db_connection.execute(text("INSERT INTO categories DEFAULT VALUES RETURNING id"))
    ).scalar_one()
    assert new_id == max(c.id for c in CATEGORIES) + 1
