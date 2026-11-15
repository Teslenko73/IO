from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Wspólna baza modeli ORM. Pozostałe moduły (user, category) dziedziczą po niej."""
