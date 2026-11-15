"""Stały katalog kategorii wydarzeń.

To jest jedno miejsce, w którym ustawiasz kategorie: id i nazwa. Przykładowa lista
poniżej jest do zmiany. Id musi być liczbą dodatnią (1, 2, 3...) i nie wolno go
zmieniać ani używać ponownie dla innej kategorii, bo wydarzenia w bazie wskazują
kategorię po id. Nową kategorię dopisz na końcu z kolejnym numerem.

Po zmianie listy zasil tabelę categories w bazie: python -m main.bd.seed
"""
from dataclasses import dataclass

from main.domain.event import INT_MAX


@dataclass(frozen=True)
class Category:
    id: int
    name: str


CATEGORIES: tuple[Category, ...] = (
    Category(1, "Naukowe"),
    Category(2, "Konferencja"),
    Category(3, "Warsztat"),
    Category(4, "Szkolenie"),
    Category(5, "Spotkanie"),
    Category(6, "Kulturalne"),
    Category(7, "Sportowe"),
    Category(8, "Inne"),
)

_BY_ID = {c.id: c for c in CATEGORIES}

# błąd w liście kategorii ma wyjść od razu przy starcie, a nie dopiero w produkcji
if len(_BY_ID) != len(CATEGORIES):
    raise RuntimeError("Powtórzone id w CATEGORIES (main/domain/category.py)")
if any(not 0 < c.id <= INT_MAX or not c.name.strip() for c in CATEGORIES):
    raise RuntimeError("Każda kategoria musi mieć id > 0 i niepustą nazwę")


def all_categories() -> tuple[Category, ...]:
    return tuple(sorted(CATEGORIES, key=lambda c: c.id))


def get_category(category_id: int) -> Category | None:
    return _BY_ID.get(category_id)


def available_ids_text() -> str:
    return ", ".join(str(c.id) for c in all_categories())
