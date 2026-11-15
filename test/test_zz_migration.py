"""Migracja Alembic: w górę i w dół. Nazwa pliku zaczyna się od zz_, żeby
działał na końcu, bo zmienia schemat bazy testowej."""
import pytest
from sqlalchemy import text


async def columns(engine) -> dict[str, tuple[str, str]]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns WHERE table_name = 'events'"
            )
        )
        return {name: (dtype, nullable) for name, dtype, nullable in rows}


async def indexes(engine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'events'")
        )
        return {r[0] for r in rows}


async def test_upgrade_state(engine):
    cols = await columns(engine)
    assert cols["email_for_organization"] == ("character varying", "NO")
    assert cols["description"] == ("text", "NO")
    assert cols["start_time"][0] == "timestamp with time zone"
    assert cols["end_time"][0] == "timestamp with time zone"
    assert {"idx_organizer_id", "idx_status_start_time",
            "idx_start_time", "idx_category_id"} <= await indexes(engine)


async def test_downgrade_and_upgrade_again_on_empty_table(engine, alembic_run):
    await alembic_run("downgrade", "base")
    cols = await columns(engine)
    assert "email_for_organization" not in cols
    assert cols["description"][1] == "YES"
    assert cols["start_time"][0] == "timestamp without time zone"
    idx = await indexes(engine)
    assert "idx_organizer_id" not in idx and "idx_status_start_time" not in idx
    assert {"idx_start_time", "idx_category_id"} <= idx  # indeksy z oryginalnego schematu zostają

    await alembic_run("upgrade", "head")
    cols = await columns(engine)
    assert cols["email_for_organization"] == ("character varying", "NO")
    assert cols["start_time"][0] == "timestamp with time zone"


async def test_upgrade_converts_existing_timestamps_as_utc_and_refuses_incomplete_rows(
    engine, alembic_run
):
    await alembic_run("downgrade", "base")
    insert = (
        "INSERT INTO events (organizer_id, category_id, title, description, start_time, "
        "end_time, location) VALUES (1, 1, 'Stare', :description, "
        "'2026-12-01 10:00', '2026-12-01 12:00', 'Łódź')"
    )
    try:
        # wiersz bez email_for_organization (kolumny jeszcze nie ma) => migracja ma się zatrzymać
        async with engine.begin() as conn:
            await conn.execute(text(insert), {"description": "Opis"})
        with pytest.raises(RuntimeError, match="Uzupełnij dane"):
            await alembic_run("upgrade", "head")
        assert "email_for_organization" not in await columns(engine)  # nic nie zostało w połowie
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM events"))
        await alembic_run("upgrade", "head")
    assert (await columns(engine))["email_for_organization"][1] == "NO"
