# Events API: moduł Event

REST API do zarządzania wydarzeniami (FastAPI, PostgreSQL, SQLAlchemy 2.0 async)
z powiadomieniami mailowymi dla organizatora. Zgodne z TZ „moduł Event".

Wymaga Pythona 3.10+. Przetestowane na Pythonie 3.13, FastAPI 0.162, pydantic 2.13,
SQLAlchemy 2.1, PostgreSQL 16.

## Struktura

```
main/
  app.py                  # create_app() i app: uvicorn main.app:app
  config.py               # ustawienia ze zmiennych środowiskowych
  domain/event.py         # encja Event (czysty Python, gettery/settery, reguły, przejścia statusów)
  domain/errors.py        # wyjątki domenowe
  domain/category.py      # stały katalog kategorii (id, nazwa): tu ustawiasz kategorie
  router/schemas.py       # kontrakt API: EventCreate, EventUpdate, EventFilters, EventOut, EventList
  router/events.py        # endpointy wydarzeń
  router/categories.py    # GET /categories i GET /categories/{id}
  router/errors.py        # wyjątki -> kody HTTP
  service/event_service.py# scenariusze, transakcje, wybór rodzaju maila
  bd/modle/event.py       # model tabeli events (SQLAlchemy)
  bd/maper/event.py       # EventModel <-> Event
  bd/repo/event.py        # zapytania, tłumaczenie błędów bazy
  bd/session.py           # silnik i fabryka sesji
  bd/seed.py              # python -m main.bd.seed: wpisuje kategorie do tabeli categories
  notifications/mail.py   # MailSender (SMTP / atrapa), szablony, Notifier
migrations/               # Alembic (async)
test/                     # 181 testów: domena, API na prawdziwym PostgreSQL, kategorie, migracja
```

Zależności idą w dół: router -> serwis -> domena. Domena nie importuje niczego z bazy ani z HTTP.

## Uruchomienie

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # uzupełnij DATABASE_URL i SMTP_*

# migracja (zmienne z .env muszą być w środowisku)
set -a; source .env; set +a
alembic upgrade head
python -m main.bd.seed      # wpisuje kategorie z main/domain/category.py do tabeli categories

uvicorn main.app:app --reload --env-file .env
```

Dokumentacja i testowanie w przeglądarce: http://127.0.0.1:8000/docs

**Migracja zakłada, że tabele `users`, `categories` i `events` (schemat z pierwszej wersji
projektu) już istnieją.** Zmienia `events`: dodaje `email_for_organization` (NOT NULL),
ustawia `description` NOT NULL, zmienia `start_time` i `end_time` na `TIMESTAMPTZ`
(stare wartości traktuje jako UTC) i dodaje indeksy `idx_organizer_id` oraz
`idx_status_start_time`. Jeśli w tabeli są już wiersze bez opisu albo bez adresu e-mail,
migracja zatrzymuje się z komunikatem i niczego nie zmienia: uzupełnij dane i uruchom ją
ponownie. Cofnięcie: `alembic downgrade base`.

## Endpointy

| Metoda | Ścieżka | Wejście | Odpowiedź | Kody |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/events` | JSON `EventCreate` | `EventOut` + nagłówek `Location` | 201, 422 |
| GET | `/api/v1/events` | query: `category_id`, `organizer_id`, `starts_from`, `starts_to`, `limit` (1-100, domyślnie 20), `offset` | `{items, total, limit, offset}` | 200, 422 |
| GET | `/api/v1/events/{id}` | | `EventOut` | 200, 404, 422 |
| PATCH | `/api/v1/events/{id}` | JSON `EventUpdate` (część pól) | `EventOut` | 200, 404, 409, 422 |
| GET | `/api/v1/categories` | | `{items: [{id, name}], total}` | 200 |
| GET | `/api/v1/categories/{id}` | | `{id, name}` | 200, 404, 422 |

`DELETE` zwraca 405. Lista zwraca tylko wydarzenia `published`, rosnąco po `start_time`.

Przykład:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events -H "Content-Type: application/json" -d '{
  "organizer_id": 1, "category_id": 1, "title": "Konferencja Python",
  "description": "Opis", "location": "Łódź",
  "start_time": "2026-12-01T10:00:00+01:00", "end_time": "2026-12-01T16:00:00+01:00",
  "price": "49.99", "email_for_organization": "org@example.com"
}'
```

### Kontrakt wejścia (dla osoby robiącej formularz)

- Pola dokładnie jak w `EventCreate`. **Nieznane pole (także `id`) = 422.**
- Wymagane: `organizer_id`, `category_id`, `title`, `description`, `start_time`, `end_time`,
  `location`, `email_for_organization`.
- Opcjonalne: `speaker` (null), `price` (0), `registration_required` (true),
  `capacity` (null), `status` (`draft`), `visibility` (`public`).
- Liczby całkowite i flagi muszą być prawdziwymi liczbami i boolami: `"5"` i `"true"`
  w cudzysłowie są odrzucane.
- Daty: napis ISO 8601 **ze strefą czasową** (`2026-12-01T10:00:00+01:00` lub `...Z`).
  Odpowiedzi zawsze w UTC (`Z`). W parametrach query znak `+` trzeba zakodować jako `%2B`.
- `price`: do 2 miejsc po przecinku, odpowiedź zwraca go jako napis (`"49.99"`).
- Przy tworzeniu `status` może być tylko `draft` lub `published`.
- W `PATCH` `null` wolno tylko dla `speaker` i `capacity`; `description` i
  `email_for_organization` są zawsze wymagane.
- `email_for_organization` nie jest zwracany w odpowiedziach.

Błędy walidacji to 422 z listą `{loc, msg, type}` per pole, pozostałe błędy to `{"detail": "opis"}`.

### Kategorie

Kategorie są stałe i ustawia się je w jednym miejscu: `main/domain/category.py` (id i nazwa).
Przykładowa lista (1 Naukowe, 2 Konferencja, 3 Warsztat, 4 Szkolenie, 5 Spotkanie,
6 Kulturalne, 7 Sportowe, 8 Inne) jest do zmiany.

- `GET /api/v1/categories` zwraca wszystkie kategorie, a `GET /api/v1/categories/{id}` jedną
  po id (404, gdy jej nie ma). Z tej listy formularz bierze id do wydarzenia.
- `category_id` w `POST`, `PATCH` i w filtrze listy musi być z katalogu. Inne id to 422
  z listą dostępnych.
- Odpowiedź z wydarzeniem zawiera `category_name`, czyli nazwę dla `category_id`.
- Id zaczynają się od 1 (0 jest niedozwolone). Nie zmieniaj i nie używaj ponownie id
  istniejącej kategorii, bo wydarzenia wskazują ją po id. Nowe kategorie dopisuj na końcu.
- Klucz obcy w bazie nadal wymaga wiersza w tabeli `categories`. Po każdej zmianie listy
  uruchom `python -m main.bd.seed`: wpisuje id (i nazwę, jeśli tabela ma kolumnę `name`),
  można go uruchamiać wielokrotnie. Gdy tabela ma inne wymagane kolumny, skrypt wypisze
  błąd i wiersze trzeba wpisać ręcznie.

### Cykl życia statusu

`draft` -> `published` lub `cancelled`; `published` -> `archived` lub `cancelled`.
`archived` i `cancelled` są końcowe, a takie wydarzenie jest tylko do odczytu.
Niedozwolone przejście lub edycja wydarzenia końcowego to 409. `PATCH` z takim samym
statusem jak obecny nic nie zmienia i nie wysyła maila.

### Maile

Po utworzeniu, zmianie pól i każdej zmianie statusu serwer wysyła mail na
`email_for_organization` (po zmianie). Jedno żądanie = najwyżej jeden mail; gdy `PATCH`
zmienia pola i status naraz, wychodzi mail o statusie z listą zmienionych pól.
Wysyłka idzie w tle po zatwierdzeniu transakcji, a błąd SMTP jest tylko logowany (ERROR)
z `event_id`, bez wpływu na odpowiedź API. Bez `SMTP_HOST` maile są pomijane z ostrzeżeniem w logu.

## Testy

```bash
export TEST_DATABASE_URL=postgresql+asyncpg://user:haslo@localhost:5432/mojabaza_test
pytest
```

Nazwa bazy testowej musi zawierać „test": testy tworzą w niej tabele od zera i kasują je
na końcu. Każdy test działa w transakcji cofanej po teście. Bez `TEST_DATABASE_URL`
działają tylko testy domeny, a reszta jest pomijana.

## Decyzje poza dosłownym TZ

- **Klucze obce w modelu ORM**: `organizer_id` i `category_id` to zwykłe kolumny `int`,
  bo SQLAlchemy nie flushuje wiersza z `ForeignKey` do tabeli, której nie zna, a `users`
  i `categories` robią inni uczestnicy. Klucze obce nadal istnieją w bazie i to ona je
  pilnuje; błąd tłumaczymy na 422 z nazwą pola. Gdy modele `User` i `Category` trafią do
  tego samego `Base`, można dopisać `ForeignKey(...)`.
- **Nazwy katalogów** `bd`, `modle`, `maper` zostały takie, jak w Twojej strukturze.
  Zmiana na `db`, `model`, `mapper` to samo przenazwanie katalogów i importów.
- **CORS** jest wyłączony, dopóki nie ustawisz `CORS_ORIGINS` (potrzebne, gdy formularz
  działa na innej domenie).
- **Strefa dat w mailach**: `MAIL_TIMEZONE`, domyślnie `Europe/Warsaw`.
