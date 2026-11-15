"""Konwersja między modelem bazy (EventModel) a encją domenową (Event)."""
from main.bd.modle.event import EventModel
from main.domain.event import Event


def to_domain(model: EventModel) -> Event:
    return Event(
        id=model.id,
        organizer_id=model.organizer_id,
        category_id=model.category_id,
        title=model.title,
        description=model.description,
        start_time=model.start_time,
        end_time=model.end_time,
        location=model.location,
        speaker=model.speaker,
        price=model.price,
        registration_required=model.registration_required,
        capacity=model.capacity,
        status=model.status,
        visibility=model.visibility,
        email_for_organization=model.email_for_organization,
    )


def apply_to_model(event: Event, model: EventModel) -> None:
    """Przepisuje pola encji do modelu (bez id, nadaje je baza)."""
    model.organizer_id = event.get_organizer_id()
    model.category_id = event.get_category_id()
    model.title = event.get_title()
    model.description = event.get_description()
    model.start_time = event.get_start_time()
    model.end_time = event.get_end_time()
    model.location = event.get_location()
    model.speaker = event.get_speaker()
    model.price = event.get_price()
    model.registration_required = event.get_registration_required()
    model.capacity = event.get_capacity()
    model.status = event.get_status()
    model.visibility = event.get_visibility()
    model.email_for_organization = event.get_email_for_organization()


def to_model(event: Event) -> EventModel:
    model = EventModel()
    apply_to_model(event, model)
    return model
