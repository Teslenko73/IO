# AGENTS.md: kontekst projektu dla asystentów AI i nowych osób

Moduł **Event** większego projektu zespołowego. Inne osoby robią moduły User i Category.
Pełny opis w `README.md` (uruchomienie, kontrakt API). Ten plik to skrót zasad i decyzji.

## Stos
Python 3.10+, FastAPI, pydantic v2, SQLAlchemy 2.x async + asyncpg, PostgreSQL, Alembic, aiosmtplib.
Testy: pytest + pytest-asyncio na prawdziwym PostgreSQL (`TEST_DATABASE_URL`, nazwa bazy zawiera "test").

## Architektura (zależności tylko w dół)
router -> service -> domain; bd (model, maper, repo) implementuje dostęp do danych.
- `main/domain/`: czysty Python, bez importów z HTTP i bazy. `Event` z `get_*`/`set_*` (bez `@property`).
  Reguły i przejścia statusów są tu. `category.py` to stały katalog kategorii.
- `main/router/`: endpointy i schematy pydantic (`schemas.py`), mapowanie wyjątków na HTTP (`errors.py`).
- `main/service/event_service.py`: transakcje, decyzja o mailu.
- `main/bd/`: `modle/` (SQLAlchemy), `maper/` (model <-> domena), `repo/` (zapytania), `seed.py`.
- `main/notifications/mail.py`: `Notifier`, `SmtpMailSender`, `NullMailSender`.
- Nazwy katalogów `bd`, `modle`, `maper` są celowe (struktura zespołu). Nie zmieniaj ich.

## Zasady, których nie łam
- **Ścisła walidacja wejścia:** `extra="forbid"`, brak koercji typów (`"5"` nie jest liczbą), daty tylko ISO 8601
  ze strefą. Nieznane pole (także `id`) = 422. `EventUpdate` nie przyjmuje `null` poza `speaker` i `capacity`.
- **Brak DELETE** (405). Wydarzenia nie są usuwane, tylko `archived` lub `cancelled`.
- **Statusy:** draft -> published | cancelled; published -> archived | cancelled; archived i cancelled są
  końcowe i tylko do odczytu (409). Ten sam status w PATCH = brak zmiany i brak maila. POST: tylko draft lub published.
- **Id nadaje baza** (`GENERATED ALWAYS AS IDENTITY`), klient nie wysyła `id`.
- **Czas:** w bazie `TIMESTAMPTZ` (UTC), w odpowiedziach UTC z `Z`. Cena jako napis (`"49.99"`).
- **Maile:** po commit, w `BackgroundTasks`; błąd SMTP tylko loguje ERROR z `event_id` i nie zmienia odpowiedzi.
  Jedno żądanie = najwyżej jeden mail (mail o statusie ma priorytet). `email_for_organization` nie wychodzi w API.
- **Klucze obce:** model ORM celowo nie ma `ForeignKey` (tabele `users`/`categories` należą do innych);
  FK pilnuje baza, błąd 23503 tłumaczy repo na 422.
- **Kategorie:** stały katalog w `main/domain/category.py` (id od 1, nie zmieniać i nie używać ponownie id).
  Po zmianie listy uruchom `python -m main.bd.seed`.

## Kody błędów
422 walidacja (`{"detail":[{loc,msg,type}]}`) lub błąd domenowy/FK (`{"detail":"..."}`), 404, 409, 405, 503 (baza niedostępna), 500 ogólny
(szczegóły tylko w logu `main.api`).

## Uruchomienie i testy (skrót)
```bash
pip install -r requirements-dev.txt
cp .env.example .env                 # DATABASE_URL, SMTP_*
set -a; source .env; set +a
alembic upgrade head && python -m main.bd.seed
uvicorn main.app:app --reload --env-file .env      # http://127.0.0.1:8000/docs
TEST_DATABASE_URL=postgresql+asyncpg://user:haslo@localhost:5432/baza_test pytest
```
Migracja zakłada, że tabele `users`, `categories`, `events` już istnieją. Tabele muszą należeć do użytkownika z `DATABASE_URL`.

## Znane ograniczenia (etap bez autoryzacji)
- Brak uwierzytelniania: `organizer_id` pochodzi z body, więc każdy może zmienić dowolne wydarzenie.
  Do dodania razem z modułem User (organizer z tokenu, sprawdzanie właściciela w PATCH).
- Brak limitu żądań; CORS wyłączony, dopóki nie ustawisz `CORS_ORIGINS`.
- Lista `GET /events` zwraca tylko `published`; szkice czyta się po id.

## Przy zmianach
Zmieniasz pole lub regułę: zaktualizuj `domain/event.py`, `router/schemas.py`, `bd/modle` + migrację Alembic,
`bd/maper`, testy i `README.md`. Uruchom `pytest` na prawdziwym PostgreSQL przed oddaniem zmian.
Pamiętaj o plikach ukrytych (`.env.example`, `.gitignore`) przy kopiowaniu projektu.
