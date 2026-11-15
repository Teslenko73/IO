"""GET /api/v1/events i GET /api/v1/events/{id}"""
import pytest

API = "/api/v1/events"


async def create(client, payload, **overrides) -> dict:
    r = await client.post(API, json=payload(**overrides))
    assert r.status_code == 201, r.text
    return r.json()


async def test_list_returns_only_published_sorted_by_start_time(client, payload):
    late = await create(client, payload, title="Późne", status="published",
                        start_time="2026-12-20T10:00:00Z", end_time="2026-12-20T12:00:00Z")
    early = await create(client, payload, title="Wczesne", status="published",
                         start_time="2026-12-02T10:00:00Z", end_time="2026-12-02T12:00:00Z")
    await create(client, payload, title="Szkic", status="draft")

    r = await client.get(API)
    assert r.status_code == 200
    body = r.json()
    assert [e["id"] for e in body["items"]] == [early["id"], late["id"]]
    assert body["total"] == 2
    assert (body["limit"], body["offset"]) == (20, 0)


async def test_list_excludes_archived_and_cancelled(client, payload):
    a = await create(client, payload, status="published")
    b = await create(client, payload, status="published")
    await client.patch(f"{API}/{a['id']}", json={"status": "archived"})
    await client.patch(f"{API}/{b['id']}", json={"status": "cancelled"})
    assert (await client.get(API)).json()["items"] == []


async def test_list_filters(client, payload):
    e1 = await create(client, payload, status="published", category_id=1, organizer_id=1,
                      start_time="2026-12-01T10:00:00Z", end_time="2026-12-01T11:00:00Z")
    e2 = await create(client, payload, status="published", category_id=2, organizer_id=2,
                      start_time="2026-12-10T10:00:00Z", end_time="2026-12-10T11:00:00Z")

    def ids(r):
        return [e["id"] for e in r.json()["items"]]

    assert ids(await client.get(API, params={"category_id": 2})) == [e2["id"]]
    assert ids(await client.get(API, params={"organizer_id": 1})) == [e1["id"]]
    assert ids(await client.get(API, params={"starts_from": "2026-12-05T00:00:00Z"})) == [e2["id"]]
    assert ids(await client.get(API, params={"starts_to": "2026-12-05T00:00:00Z"})) == [e1["id"]]
    # znak + w offsecie strefy: httpx koduje go jako %2B
    assert ids(await client.get(API, params={"starts_from": "2026-12-05T00:00:00+01:00"})) == [e2["id"]]


async def test_list_pagination(client, payload):
    for day in (1, 2, 3):
        await create(client, payload, status="published",
                     start_time=f"2026-12-0{day}T10:00:00Z", end_time=f"2026-12-0{day}T11:00:00Z")
    r = await client.get(API, params={"limit": 2, "offset": 1})
    body = r.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert [e["start_time"][:10] for e in body["items"]] == ["2026-12-02", "2026-12-03"]


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"limit": 0},
        {"offset": -1},
        {"limit": "abc"},
        {"category_id": 0},
        {"category_id": 999},  # spoza katalogu kategorii
        {"starts_from": "2026-12-05T00:00:00"},  # bez strefy
        {"starts_from": "2026-12-10T00:00:00Z", "starts_to": "2026-12-01T00:00:00Z"},
        {"nieznany": "x"},
    ],
    ids=lambda p: str(p),
)
async def test_list_rejects_bad_query(client, params):
    r = await client.get(API, params=params)
    assert r.status_code == 422, r.text


async def test_get_one_returns_event_in_any_status(client, payload):
    draft = await create(client, payload, status="draft")
    r = await client.get(f"{API}/{draft['id']}")
    assert r.status_code == 200
    assert r.json() == draft
    assert "email_for_organization" not in r.json()


async def test_get_one_not_found(client):
    r = await client.get(f"{API}/999999")
    assert r.status_code == 404
    assert r.json() == {"detail": "Nie znaleziono wydarzenia"}


@pytest.mark.parametrize("bad_id", ["abc", "0", "-1", str(2**31), "1.5"])
async def test_get_one_rejects_bad_id(client, bad_id):
    r = await client.get(f"{API}/{bad_id}")
    assert r.status_code == 422
