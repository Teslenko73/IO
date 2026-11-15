"""PATCH /api/v1/events/{id}, DELETE (405) i powiadomienia mailowe."""
import logging

import pytest

API = "/api/v1/events"


async def create(client, payload, **overrides) -> dict:
    r = await client.post(API, json=payload(**overrides))
    assert r.status_code == 201, r.text
    return r.json()


async def patch(client, event_id, **fields):
    return await client.patch(f"{API}/{event_id}", json=fields)


async def test_patch_changes_only_given_fields(client, payload, mail):
    created = await create(client, payload)
    r = await patch(client, created["id"], title="Nowy tytuł", capacity=50)
    assert r.status_code == 200
    updated = r.json()
    assert updated["title"] == "Nowy tytuł"
    assert updated["capacity"] == 50
    unchanged = {k: v for k, v in created.items() if k not in ("title", "capacity")}
    assert {k: v for k, v in updated.items() if k not in ("title", "capacity")} == unchanged
    # zapis jest trwały
    assert (await client.get(f"{API}/{created['id']}")).json() == updated


async def test_patch_sends_one_mail_with_changed_fields(client, payload, mail):
    created = await create(client, payload)
    mail.sent.clear()
    await patch(client, created["id"], title="Nowy tytuł", location="Warszawa")
    assert len(mail.sent) == 1
    sent = mail.sent[0]
    assert sent.subject == "Zmieniono wydarzenie: Nowy tytuł"
    assert "Konferencja Python -> Nowy tytuł" in sent.body
    assert "Łódź, Manufaktura -> Warszawa" in sent.body


async def test_patch_can_set_optional_fields_to_null(client, payload):
    created = await create(client, payload)
    r = await patch(client, created["id"], speaker=None, capacity=None)
    assert r.status_code == 200
    assert r.json()["speaker"] is None
    assert r.json()["capacity"] is None


async def test_patch_empty_body_returns_422(client, payload):
    created = await create(client, payload)
    r = await client.patch(f"{API}/{created['id']}", json={})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "field", ["title", "description", "location", "email_for_organization",
              "start_time", "end_time", "price", "status", "organizer_id"],
)
async def test_patch_rejects_null_for_required_fields(client, payload, field):
    created = await create(client, payload)
    r = await patch(client, created["id"], **{field: None})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize(
    "fields",
    [{"id": 5}, {"foo": "bar"}, {"capacity": "5"}, {"title": ""}, {"description": ""},
     {"start_time": "2026-12-01T10:00:00"}, {"price": "-1"}],
    ids=lambda f: str(f),
)
async def test_patch_rejects_invalid_input(client, payload, fields):
    created = await create(client, payload)
    r = await client.patch(f"{API}/{created['id']}", json=fields)
    assert r.status_code == 422, r.text


async def test_patch_end_time_earlier_than_stored_start_returns_422(client, payload):
    created = await create(client, payload)  # start 09:00Z
    r = await patch(client, created["id"], end_time="2026-12-01T08:00:00Z")
    assert r.status_code == 422
    assert "end_time" in r.json()["detail"]


async def test_patch_start_time_after_stored_end_returns_422(client, payload):
    created = await create(client, payload)  # end 15:00Z
    r = await patch(client, created["id"], start_time="2026-12-01T16:00:00Z")
    assert r.status_code == 422


async def test_patch_moves_both_times_at_once(client, payload):
    created = await create(client, payload)
    r = await patch(client, created["id"], start_time="2026-12-08T09:00:00Z",
                    end_time="2026-12-08T15:00:00Z")
    assert r.status_code == 200
    assert r.json()["start_time"] == "2026-12-08T09:00:00Z"


async def test_patch_nonexistent_reference_returns_422(client, payload):
    created = await create(client, payload)
    r = await patch(client, created["id"], organizer_id=999)
    assert r.status_code == 422
    assert "organizer_id" in r.json()["detail"]  # błąd klucza obcego z bazy


async def test_patch_not_found(client):
    r = await patch(client, 999999, title="x")
    assert r.status_code == 404


@pytest.mark.parametrize("bad_id", ["abc", "0"])
async def test_patch_rejects_bad_id(client, bad_id):
    r = await client.patch(f"{API}/{bad_id}", json={"title": "x"})
    assert r.status_code == 422


# ---------- cykl życia statusu ----------
@pytest.mark.parametrize(
    "start,target,subject_prefix",
    [
        ("draft", "published", "Opublikowano wydarzenie"),
        ("draft", "cancelled", "Anulowano wydarzenie"),
        ("published", "archived", "Zarchiwizowano wydarzenie"),
        ("published", "cancelled", "Anulowano wydarzenie"),
    ],
)
async def test_allowed_status_transitions_send_status_mail(
    client, payload, mail, start, target, subject_prefix
):
    created = await create(client, payload, status=start)
    mail.sent.clear()
    r = await patch(client, created["id"], status=target)
    assert r.status_code == 200
    assert r.json()["status"] == target
    assert len(mail.sent) == 1
    assert mail.sent[0].subject.startswith(subject_prefix)


@pytest.mark.parametrize(
    "start,target",
    [("draft", "archived"), ("published", "draft")],
)
async def test_forbidden_status_transitions_return_409(client, payload, mail, start, target):
    created = await create(client, payload, status=start)
    mail.sent.clear()
    r = await patch(client, created["id"], status=target)
    assert r.status_code == 409
    assert mail.sent == []
    assert (await client.get(f"{API}/{created['id']}")).json()["status"] == start


@pytest.mark.parametrize("final", ["archived", "cancelled"])
async def test_terminal_events_are_read_only(client, payload, final):
    created = await create(client, payload, status="published")
    assert (await patch(client, created["id"], status=final)).status_code == 200
    for change in ({"title": "Zmiana"}, {"status": "published"}, {"status": final}):
        r = await client.patch(f"{API}/{created['id']}", json=change)
        assert r.status_code == 409, change
    assert (await client.get(f"{API}/{created['id']}")).json()["title"] == "Konferencja Python"


async def test_same_status_is_noop_without_mail(client, payload, mail):
    created = await create(client, payload, status="published")
    mail.sent.clear()
    r = await patch(client, created["id"], status="published")
    assert r.status_code == 200
    assert mail.sent == []


async def test_patch_without_real_change_sends_no_mail(client, payload, mail):
    created = await create(client, payload)
    mail.sent.clear()
    r = await patch(client, created["id"], title=created["title"])
    assert r.status_code == 200
    assert mail.sent == []


async def test_fields_and_status_together_send_one_status_mail(client, payload, mail):
    created = await create(client, payload)
    mail.sent.clear()
    r = await patch(client, created["id"], title="Nowy tytuł", status="published")
    assert r.status_code == 200
    assert len(mail.sent) == 1
    assert mail.sent[0].subject == "Opublikowano wydarzenie: Nowy tytuł"
    assert "Tytuł:" in mail.sent[0].body


async def test_mail_goes_to_new_address_after_change(client, payload, mail):
    created = await create(client, payload)
    mail.sent.clear()
    await patch(client, created["id"], email_for_organization="nowy@example.com")
    assert [m.to for m in mail.sent] == ["nowy@example.com"]


# ---------- DELETE ----------
async def test_delete_returns_405(client, payload):
    created = await create(client, payload)
    r = await client.delete(f"{API}/{created['id']}")
    assert r.status_code == 405
    assert (await client.get(f"{API}/{created['id']}")).status_code == 200


# ---------- błędy wysyłki maila ----------
async def test_smtp_failure_does_not_change_api_response_and_is_logged(
    client, payload, mail, caplog
):
    mail.fail = True
    with caplog.at_level(logging.ERROR, logger="main.notifications"):
        r = await client.post(API, json=payload())
    assert r.status_code == 201
    event_id = r.json()["id"]
    errors = [rec for rec in caplog.records if rec.levelno == logging.ERROR]
    assert len(errors) == 1
    assert f"event_id={event_id}" in errors[0].getMessage()
    # rekord został zapisany mimo błędu maila
    assert (await client.get(f"{API}/{event_id}")).status_code == 200
