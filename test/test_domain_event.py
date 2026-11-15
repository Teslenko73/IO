"""Testy jednostkowe encji Event (bez bazy)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from main.domain.errors import EventNotEditable, EventValidationError, InvalidStatusTransition
from main.domain.event import Event, EventStatus

START = datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=6)


def make(**overrides) -> Event:
    data = dict(
        organizer_id=1,
        category_id=1,
        title="Konferencja",
        description="Opis",
        start_time=START,
        end_time=END,
        location="Łódź",
        email_for_organization="org@example.com",
    )
    data.update(overrides)
    return Event(**data)


def test_defaults():
    e = make()
    assert e.get_id() is None
    assert e.get_status() is EventStatus.DRAFT
    assert e.get_price() == Decimal("0.00")
    assert e.get_registration_required() is True
    assert e.get_capacity() is None
    assert e.get_speaker() is None


def test_times_are_normalized_to_utc():
    plus_one = timezone(timedelta(hours=1))
    e = make(start_time=datetime(2026, 12, 1, 11, 0, tzinfo=plus_one),
             end_time=datetime(2026, 12, 1, 17, 0, tzinfo=plus_one))
    assert e.get_start_time() == START
    assert e.get_start_time().utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"organizer_id": 0},
        {"organizer_id": True},
        {"organizer_id": 2**31},
        {"category_id": "1"},
        {"title": "   "},
        {"title": "x" * 201},
        {"description": ""},
        {"description": None},
        {"location": ""},
        {"speaker": ""},
        {"speaker": "x" * 501},
        {"price": -1},
        {"price": "10.123"},
        {"price": True},
        {"price": 10**8},
        {"capacity": 0},
        {"capacity": 1.5},
        {"registration_required": "true"},
        {"status": "nieznany"},
        {"visibility": "private"},
        {"email_for_organization": None},
        {"email_for_organization": "bez-malpy"},
        {"start_time": datetime(2026, 12, 1, 10, 0)},  # bez strefy
        {"end_time": START},  # równe start_time
        {"end_time": START - timedelta(hours=1)},
    ],
)
def test_constructor_rejects_invalid_values(overrides):
    with pytest.raises(EventValidationError):
        make(**overrides)


def test_setters_validate():
    e = make()
    with pytest.raises(EventValidationError):
        e.set_title("")
    with pytest.raises(EventValidationError):
        e.set_end_time(START)
    assert e.get_title() == "Konferencja"  # nieudany setter nic nie zmienił
    e.set_title("Nowy tytuł")
    assert e.get_title() == "Nowy tytuł"


def test_set_times_moves_both_at_once():
    e = make()
    week = timedelta(days=7)
    e.set_times(START + week, END + week)  # osobne settery rzuciłyby błąd po drodze
    assert e.get_start_time() == START + week
    assert e.get_end_time() == END + week


def test_price_is_quantized():
    assert make(price="49.9").get_price() == Decimal("49.90")
    assert str(make(price=5).get_price()) == "5.00"


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        ("draft", "published", True),
        ("draft", "cancelled", True),
        ("draft", "archived", False),
        ("published", "archived", True),
        ("published", "cancelled", True),
        ("published", "draft", False),
        ("archived", "published", False),
        ("cancelled", "published", False),
    ],
)
def test_status_transitions(current, target, allowed):
    e = make(status=current)
    if allowed:
        assert e.change_status(target) is True
        assert e.get_status() is EventStatus(target)
    else:
        with pytest.raises(InvalidStatusTransition):
            e.change_status(target)
        assert e.get_status() is EventStatus(current)


def test_same_status_is_noop():
    e = make(status="published")
    assert e.change_status("published") is False


def test_apply_changes_returns_only_real_diff():
    e = make()
    diff = e.apply_changes({"title": "Nowy", "location": "Łódź"})  # location bez zmiany
    assert list(diff) == ["title"]
    assert diff["title"] == ("Konferencja", "Nowy")


def test_apply_changes_with_only_end_time_checks_against_stored_start():
    e = make()
    with pytest.raises(EventValidationError):
        e.apply_changes({"end_time": START - timedelta(hours=1)})


def test_apply_changes_status_is_checked_before_other_fields():
    e = make()  # draft
    with pytest.raises(InvalidStatusTransition):
        e.apply_changes({"title": "Zmiana", "status": "archived"})
    assert e.get_title() == "Konferencja"


@pytest.mark.parametrize("status", ["archived", "cancelled"])
def test_terminal_events_are_read_only(status):
    e = make(status=status)
    assert e.is_editable() is False
    with pytest.raises(EventNotEditable):
        e.apply_changes({"title": "Zmiana"})


def test_apply_changes_rejects_unknown_field():
    with pytest.raises(EventValidationError):
        make().apply_changes({"id": 5})
