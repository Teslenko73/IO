"""Wyjątki domenowe. Router zamienia je na kody HTTP (main/router/errors.py)."""


class DomainError(Exception):
    """Bazowy wyjątek logiki biznesowej."""


class EventValidationError(DomainError, ValueError):
    """Dane łamią regułę encji Event (długość, zakres, kolejność dat itd.) -> 422."""


class EventNotEditable(DomainError):
    """Wydarzenie w statusie archived lub cancelled jest tylko do odczytu -> 409."""


class InvalidStatusTransition(DomainError):
    """Niedozwolone przejście statusu, np. cancelled -> published -> 409."""


class EventNotFound(DomainError):
    """Brak wydarzenia o podanym id -> 404."""


class ReferenceNotFound(DomainError):
    """organizer_id lub category_id wskazuje na nieistniejący rekord -> 422."""


class ConstraintViolation(DomainError):
    """Baza odrzuciła dane (CHECK, NOT NULL, ENUM) -> 422."""
