"""POST /api/v1/events"""
import pytest
from sqlalchemy import text

API = "/api/v1/events"


async def test_create_returns_201_with_id_location_and_one_mail(client, payload, mail):
    r = await client.post(API, json=payload())
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], int)
    assert r.headers["location"] == f"{API}/{body['id']}"
    assert body["title"] == "Konferencja Python"
    assert body["price"] == "49.99"  # Decimal jako napis
    assert body["start_time"] == "2026-12-01T09:00:00Z"  # zapisane w UTC
    assert body["status"] == "draft"
    assert "email_for_organization" not in body

    assert len(mail.sent) == 1
    assert mail.sent[0].to == "org@example.com"
    assert mail.sent[0].subject == "Utworzono wydarzenie: Konferencja Python"


async def test_create_applies_defaults(client, payload):
    data = payload(drop=["speaker", "price", "registration_required", "capacity",
                         "status", "visibility"])
    r = await client.post(API, json=data)
    assert r.status_code == 201
    body = r.json()
    assert body["speaker"] is None
    assert body["price"] == "0.00"
    assert body["registration_required"] is True
    assert body["capacity"] is None
    assert body["status"] == "draft"
    assert body["visibility"] == "public"


async def test_create_can_publish_immediately(client, payload):
    r = await client.post(API, json=payload(status="published"))
    assert r.status_code == 201
    assert r.json()["status"] == "published"


@pytest.mark.parametrize("extra", [{"id": 5}, {"foo": "bar"}, {"created_at": "2026-01-01"}])
async def test_create_rejects_unknown_fields(client, payload, extra):
    r = await client.post(API, json=payload(**extra))
    assert r.status_code == 422
    assert r.json()["detail"][0]["type"] == "extra_forbidden"


@pytest.mark.parametrize(
    "field",
    ["organizer_id", "category_id", "title", "description", "start_time", "end_time",
     "location", "email_for_organization"],
)
async def test_create_rejects_missing_required_field(client, payload, field):
    r = await client.post(API, json=payload(drop=[field]))
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    "overrides",
    [
        {"capacity": "5"},  # liczba w cudzysłowie
        {"capacity": 5.0},
        {"capacity": 0},
        {"capacity": 2**31},
        {"organizer_id": "1"},
        {"organizer_id": 0},
        {"organizer_id": True},
        {"registration_required": "true"},
        {"registration_required": 1},
        {"title": 123},
        {"title": "   "},
        {"title": "x" * 201},
        {"location": ""},
        {"speaker": "x" * 501},
        {"speaker": ""},
        {"description": None},
        {"description": ""},
        {"price": "-1"},
        {"price": "10.123"},
        {"price": True},
        {"price": "abc"},
        {"price": "100000000"},
        {"email_for_organization": None},
        {"email_for_organization": "to-nie-email"},
        {"email_for_organization": "a" * 250 + "@example.com"},
        {"start_time": "2026-12-01T10:00:00"},  # bez strefy
        {"start_time": 1796119200},  # timestamp zamiast napisu ISO
        {"start_time": "jutro"},
        {"end_time": "2026-12-01T10:00:00+01:00"},  # równe start_time
        {"end_time": "2026-12-01T09:00:00+01:00"},  # przed start_time
        {"status": "archived"},
        {"status": "cancelled"},
        {"status": "nieznany"},
        {"visibility": "private"},
    ],
    ids=lambda o: str(o)[:60],
)
async def test_create_rejects_invalid_values(client, payload, overrides):
    r = await client.post(API, json=payload(**overrides))
    assert r.status_code == 422, r.text


async def test_create_rejects_non_json_body(client):
    r = await client.post(API, content="to nie jest json",
                          headers={"content-type": "application/json"})
    assert r.status_code == 422


async def test_validation_errors_have_loc_msg_type_only(client, payload):
    r = await client.post(API, json=payload(title=""))
    (error,) = r.json()["detail"]
    assert set(error) == {"loc", "msg", "type"}
    assert error["loc"] == ["body", "title"]


async def test_create_with_nonexistent_organizer_returns_422(client, payload):
    r = await client.post(API, json=payload(organizer_id=999))
    assert r.status_code == 422
    assert "organizer_id" in r.json()["detail"]  # błąd klucza obcego z bazy


async def test_create_with_unknown_category_returns_422_with_available_ids(client, payload):
    r = await client.post(API, json=payload(category_id=999))
    assert r.status_code == 422
    (error,) = r.json()["detail"]
    assert error["loc"] == ["body", "category_id"]
    assert "nieznana kategoria" in error["msg"]
    assert "1, 2, 3" in error["msg"]  # lista dostępnych id w komunikacie


async def test_create_with_category_missing_in_database_returns_422(
    client, payload, db_connection
):
    # kategoria jest w katalogu, ale tabela categories nie ma jeszcze takiego wiersza
    await db_connection.execute(text("DELETE FROM categories WHERE id = 8"))
    r = await client.post(API, json=payload(category_id=8))
    assert r.status_code == 422
    assert "category_id" in r.json()["detail"]


async def test_create_returns_category_name(client, payload):
    r = await client.post(API, json=payload(category_id=3))
    assert r.json()["category_id"] == 3
    assert r.json()["category_name"] == "Warsztat"


async def test_failed_create_sends_no_mail(client, payload, mail):
    await client.post(API, json=payload(organizer_id=999))
    assert mail.sent == []


async def test_delete_on_collection_returns_405(client):
    r = await client.delete(API)
    assert r.status_code == 405
