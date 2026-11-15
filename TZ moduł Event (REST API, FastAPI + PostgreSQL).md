# TZ: moduł Event (REST API, FastAPI + PostgreSQL)

Nov 9, 2026 · @Dima

## Cel i zakres

Moduł Event dostarcza REST API do tworzenia, edycji i publikowania wydarzeń z zapisem w PostgreSQL oraz mailem do organizatora przy ważnych zmianach.

W zakresie:

- tworzenie wydarzenia, lista, odczyt jednego rekordu i częściowa edycja (PATCH); zamiast usuwania zmiana statusu na `archived` lub `cancelled`,
- ścisła walidacja wejścia: schemat pydantic odrzuca wszystko, czego sam nie opisuje,
- powiadomienia mailowe do organizatora, wysyłane w tle,
- encja domenowa `Event` w czystym Pythonie, mapper i repozytorium w SQLAlchemy 2.0 async.

Poza zakresem: użytkownicy, kategorie, rejestracja uczestników, autoryzacja i formularz po stronie klienta (robi go ktoś inny i wysyła JSON). Tabele `users` i `categories` istnieją tylko jako cele kluczy obcych.

## Stos i architektura

Architektura jest warstwowa, a zależności idą tylko w dół: router zna schematy i serwis, serwis zna domenę, domena nie importuje niczego z bazy ani z HTTP.

&#91;embedded content: warstwy i zależności · 8 elementów\]

Strzałki pokazują, kto kogo wywołuje: baza i powiadomienia są podpięte do serwisu, nie do routera.

**Stos:** Python 3.11+, FastAPI, pydantic v2 (z `email-validator` dla `EmailStr`), SQLAlchemy 2.0 async z asyncpg, Alembic do migracji, aiosmtplib do maili, pytest + pytest-asyncio + httpx do testów.

| Warstwa | Katalog | Odpowiada za |
| --- | --- | --- |
| Router | `main/router` | HTTP, schematy pydantic (`EventCreate`, `EventUpdate`, `EventOut`), kody odpowiedzi |
| Serwis | `main/service` | scenariusze: utworzenie, zmiana, przejście statusu, wywołanie powiadomienia |
| Domena | `main/domain` | encja `Event`, enumy, reguły biznesowe, przejścia statusów |
| Baza | `main/bd` | model SQLAlchemy (`modle`), mapper (`maper`), repozytorium (`repo`), sesja |
| Powiadomienia | `main/notifications` | wysyłka SMTP i szablony maili |

`service` i `notifications` to nowe katalogi względem obecnej struktury (`bd`, `domain`, `router`).

```text
main/
  app.py                  # FastAPI(), lifespan, podpięcie routera
  config.py               # ustawienia z env (baza, SMTP)
  domain/event.py         # Event, EventStatus, EventVisibility
  router/events.py        # endpointy
  router/schemas.py       # EventCreate, EventUpdate, EventOut, EventList
  service/event_service.py
  bd/session.py           # engine, async_sessionmaker
  bd/modle/event.py       # EventModel (SQLAlchemy)
  bd/maper/event.py       # EventModel <-> Event
  bd/repo/event.py        # EventRepository
  notifications/mail.py   # klient SMTP + szablony
test/
```

Przepływ `POST /api/v1/events`:

1. Router waliduje JSON schematem `EventCreate`; błąd kończy się 422, zanim cokolwiek się wykona.
2. Serwis tworzy encję `Event` (jej settery sprawdzają reguły jeszcze raz).
3. Repozytorium przez mapper zapisuje wiersz, a `id` nadaje baza (`RETURNING`).
4. Serwis zleca wysyłkę maila w tle (`BackgroundTasks`).
5. Router zwraca `EventOut` ze statusem 201.

## Model danych

Tabela `events` zostaje bez zmian poza nową kolumną `email_for_organization` i zmianą description na NOT NULL; dwa indeksy i typ czasu to rekomendacje do potwierdzenia.

| Kolumna | Typ | NULL | Domyślnie | Uwagi |
| --- | --- | --- | --- | --- |
| `id` | INT identity | nie |  | PK, nadaje baza (`GENERATED ALWAYS`) |
| `organizer_id` | INT | nie |  | FK `users(id)` |
| `category_id` | INT | nie |  | FK `categories(id)` |
| `title` | VARCHAR(200) | nie |  |  |
| `description` | TEXT | nie |  |  |
| `start_time` | TIMESTAMP | nie |  |  |
| `end_time` | TIMESTAMP | nie |  | CHECK `end_time > start_time` |
| `location` | VARCHAR(200) | nie |  |  |
| `speaker` | VARCHAR(500) | tak |  |  |
| `price` | DECIMAL(10, 2) | nie | 0 | CHECK `price >= 0` |
| `registration_required` | BOOL | nie | TRUE |  |
| `capacity` | INT | tak |  | CHECK `capacity > 0` |
| `status` | `event_status` | nie | `draft` | `draft`, `published`, `archived`, `cancelled` |
| `visibility` | `event_visibility` | nie | `public` | `public`, `logged_in` |
| `email_for_organization` | VARCHAR(254) | nie |  | **nowa**, adres do powiadomień |

Migracja (Alembic):

```sql
-- gdy tabela ma już wiersze: dodaj kolumnę bez NOT NULL, uzupełnij dane, potem ustaw NOT NULL
ALTER TABLE events ADD COLUMN email_for_organization VARCHAR(254) NOT NULL;
ALTER TABLE events ALTER COLUMN description SET NOT NULL;
CREATE INDEX idx_organizer_id ON events(organizer_id);
CREATE INDEX idx_status_start_time ON events(status, start_time);
```

Indeks na `organizer_id` jest potrzebny, bo Postgres nie tworzy go sam dla klucza obcego. Indeks `(status, start_time)` obsługuje główne zapytanie: opublikowane wydarzenia po terminie.

**Rekomendacja:** zmienić `start_time` i `end_time` z `TIMESTAMP` na `TIMESTAMPTZ`. API przyjmuje i zwraca daty ISO 8601 ze strefą, a baza trzyma UTC. Bez tego ten sam termin da się zapisać w różnych strefach i nie da się ich potem rozróżnić.

## Walidacja

JSON od klienta musi mieć dokładnie pola ze schematu pydantic: nieznane pole albo brak pola wymaganego kończy się odpowiedzią 422, zanim kod aplikacji się wykona.

Zasady kontraktu wejścia (`extra="forbid"`):

- nieznane pole jest odrzucane, w tym `id` (nadaje je baza),
- `StrictInt` i `StrictBool` dla liczb całkowitych i flag: wartości `"1"` czy `"true"` w cudzysłowie są odrzucane,
- daty tylko w formacie ISO 8601 ze strefą czasową,
- `PATCH` wymaga co najmniej jednego pola, a `null` jest dozwolony wyłącznie dla pól opcjonalnych w bazie (`speaker`, `capacity`); `description` i `email_for_organization` są wymagane i nie mogą być `null` ani puste.

| Pole | Typ | Przy tworzeniu | Reguły |
| --- | --- | --- | --- |
| `organizer_id` | int | wymagane | > 0 |
| `category_id` | int | wymagane | > 0 |
| `title` | str | wymagane | 1–200 znaków, nie same spacje |
| `description` | str | wymagane | min. 1 znak |
| `start_time` | datetime | wymagane | ISO 8601 ze strefą |
| `end_time` | datetime | wymagane | późniejszy niż `start_time` |
| `location` | str | wymagane | 1–200 znaków |
| `speaker` | str lub null | opcjonalne | do 500 znaków |
| `price` | Decimal | opcjonalne (0) | ≥ 0, do 2 miejsc po przecinku, poniżej 100 000 000 |
| `registration_required` | bool | opcjonalne (true) |  |
| `capacity` | int lub null | opcjonalne | > 0 |
| `status` | enum | opcjonalne (`draft`) | przy tworzeniu tylko `draft` lub `published` |
| `visibility` | enum | opcjonalne (`public`) | `public`, `logged_in` |
| `email_for_organization` | EmailStr | wymagane | poprawny adres, do 254 znaków |

Reguły są sprawdzane w trzech warstwach, bo każda chroni się sama:

| Warstwa | Co sprawdza | Skutek przy błędzie |
| --- | --- | --- |
| Schemat pydantic (router) | format, typy, zakresy, brak nadmiarowych pól | 422 z listą błędów per pole |
| Encja `Event` (domena) | te same reguły w setterach, przejścia statusów | `ValueError`, router zamienia na 422 lub 409 |
| Baza | `CHECK`, `NOT NULL`, klucze obce, `ENUM` | `IntegrityError`, router zamienia na 422 |

## Endpointy REST

Zasób `events` ma cztery operacje pod prefiksem `/api/v1`, a usuwania nie ma: `DELETE` zwróci 405.

| Metoda | Ścieżka | Wejście | Odpowiedź | Kody |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/events` | JSON `EventCreate` | `EventOut` + nagłówek `Location` | 201, 422 |
| GET | `/api/v1/events` | query: `category_id`, `organizer_id`, `starts_from`, `starts_to`, `limit`, `offset` | `{items, total, limit, offset}` | 200, 422 |
| GET | `/api/v1/events/{id}` |  | `EventOut` | 200, 404 |
| PATCH | `/api/v1/events/{id}` | JSON `EventUpdate` (część pól) | `EventOut` | 200, 404, 409, 422 |

Reguły:

- Lista zwraca tylko wydarzenia o statusie `published`, posortowane rosnąco po `start_time`. Filtr po `visibility` dojdzie z modułem użytkowników.
- `limit` ma zakres 1–100 (domyślnie 20), `offset` ≥ 0.
- `GET /events/{id}` zwraca wydarzenie w każdym statusie, żeby dało się nim zarządzać.
- `PATCH` wysyła tylko zmieniane pola; zmiana `status` podlega regułom z sekcji o cyklu życia.
- Wydarzenia w statusie `archived` i `cancelled` są tylko do odczytu: `PATCH` zwraca 409.

Format odpowiedzi `EventOut`: wszystkie pola tabeli plus `id`. Daty są w ISO 8601 ze strefą, `price` jako napis (`"49.99"`), żeby uniknąć błędów zaokrągleń liczb zmiennoprzecinkowych. Pole `email_for_organization` nie jest zwracane, bo bez autoryzacji lista jest publiczna (do potwierdzenia w otwartych pytaniach).

## Cykl życia statusu

Status wydarzenia zmienia się tylko do przodu, a `archived` i `cancelled` kończą jego życie; rekordów się nie usuwa.

&#91;embedded content: przejścia statusu · 4 stany, 4 przejścia\]

Z `draft` można przejść do `published` albo `cancelled`, a z `published` do `archived` albo `cancelled`.

- Nowe wydarzenie zaczyna jako `draft` albo od razu jako `published`.
- Niedozwolone przejście, np. `cancelled` → `published`, zwraca 409 z opisem.
- Reguły przejść siedzą w encji `Event` (metoda zmiany statusu), nie w routerze, więc działają tak samo z każdego miejsca w kodzie.
- Każda zmiana statusu uruchamia powiadomienie mailowe opisane w następnej sekcji.

## Powiadomienia mailowe

Serwer wysyła mail na adres `email_for_organization` po utworzeniu wydarzenia, po zmianie jego pól i po każdej zmianie statusu; wysyłka idzie w tle, a jej błąd nie psuje odpowiedzi API.

| Zdarzenie | Kiedy | Temat (propozycja) | Treść |
| --- | --- | --- | --- |
| Utworzone | po `POST` | Utworzono wydarzenie: {title} | tytuł, termin, miejsce, status |
| Zmienione | po `PATCH` bez zmiany statusu | Zmieniono wydarzenie: {title} | zmienione pola: wartość przed i po |
| Opublikowane | status → `published` | Opublikowano wydarzenie: {title} | tytuł, termin, miejsce |
| Zarchiwizowane | status → `archived` | Zarchiwizowano wydarzenie: {title} | tytuł, termin |
| Anulowane | status → `cancelled` | Anulowano wydarzenie: {title} | tytuł, termin, miejsce |

Jedno żądanie to najwyżej jeden mail; gdy `PATCH` zmienia pola i status naraz, wysyłany jest mail o zmianie statusu.

Zasady wysyłki:

- Odbiorca to `email_for_organization` po zmianie. Adres jest wymagany, więc każde wydarzenie ma odbiorcę.
- Serwis zatwierdza transakcję w bazie, a dopiero potem zleca wysyłkę przez `BackgroundTasks` (aiosmtplib).
- Błąd SMTP jest logowany na poziomie ERROR z `id` wydarzenia; żądanie kończy się sukcesem. W pierwszej wersji nie ma ponowień.
- Konfiguracja ze zmiennych środowiskowych: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TLS`.
- Maile są tekstowe i po polsku, bez HTML.
- Wysyłka stoi za interfejsem `MailSender`, więc w testach podmieniamy ją atrapą.

## Obsługa błędów

Każdy błąd ma jeden stabilny kod HTTP i ciało `{"detail": ...}`, żeby osoba robiąca formularz mogła na nich polegać.

| Sytuacja | Kod | Ciało |
| --- | --- | --- |
| Zły JSON, nieznane lub brakujące pole, zły typ albo zakres | 422 | standardowa lista błędów FastAPI: `loc`, `msg`, `type` per pole |
| Złamana reguła domeny, np. `PATCH` ustawia `end_time` wcześniej niż zapisany `start_time` | 422 | `{"detail": "opis"}` |
| `organizer_id` lub `category_id` nie istnieje (klucz obcy) | 422 | `{"detail": "organizer_id lub category_id wskazuje na nieistniejący rekord"}` |
| Złe `id` w ścieżce (nie liczba dodatnia) | 422 | lista błędów FastAPI |
| Wydarzenie nie istnieje | 404 | `{"detail": "Nie znaleziono wydarzenia"}` |
| Niedozwolone przejście statusu albo edycja wydarzenia `archived` lub `cancelled` | 409 | `{"detail": "opis"}` |
| Metoda `DELETE` | 405 | domyślna odpowiedź FastAPI |
| Błąd serwera, niedostępna baza | 500 lub 503 | `{"detail": "Błąd serwera"}`, bez szczegółów technicznych |

Szczegóły błędów bazy i SMTP trafiają tylko do logów, nigdy do odpowiedzi.

## Założenia i otwarte pytania

Poniższe punkty przyjąłem na czas pisania TZ; każdy można zmienić bez przebudowy architektury.

Przyjęte z Twoich odpowiedzi: SQLAlchemy 2.0 async, mail jako powiadomienia wysyłane przez serwer, brak endpointu `DELETE`, brak autoryzacji w tym etapie (lista zwraca tylko `published`).

Do potwierdzenia:

- [ ] Przejścia statusów: `draft` → `published` lub `cancelled`, `published` → `archived` lub `cancelled`, reszta zabroniona. Wybrałeś brak usuwania, ale nie doprecyzowałeś przejść.
- [ ] `email_for_organization` nie jest zwracane w odpowiedziach GET, bo lista jest publiczna. Czy formularz potrzebuje go odczytywać?
- [ ] `GET /events/{id}` zwraca także szkice (`draft`), bo bez autoryzacji nie ma innej drogi do zarządzania nimi. Szkic jest wtedy widoczny dla każdego, kto zna `id`.
- [ ] Zmiana `start_time` i `end_time` na `TIMESTAMPTZ` (rekomendacja z sekcji o modelu danych).
- [ ] Poprawa nazw katalogów, zanim inni zaczną pisać importy: `modle` → `model`, `maper` → `mapper`, `bd` → `db`.
- [ ] Powiadomienia bez ponowień: błąd SMTP tylko w logu. Czy potrzebna jest kolejka lub tabela outbox?
- [ ] Kolumny `created_at` i `updated_at` (zwykle się przydają, w tabeli ich nie ma).

Nie obejmujemy powiadamiania uczestników: anulowanie wydarzenia wysyła mail wyłącznie do organizatora, bo rejestracji uczestników jeszcze nie ma.

## Kryteria akceptacji i testy

Moduł jest gotowy, gdy wszystkie poniższe testy przechodzą na testowej bazie PostgreSQL, a maile są sprawdzane na atrapie `MailSender`.

Testy jednostkowe (domena, bez bazy) sprawdzają encję `Event`: settery, `set_times` i przejścia statusów. Testy integracyjne używają `httpx.AsyncClient` i Postgresa w kontenerze, a każdy test działa w transakcji cofanej na końcu.

- [ ] `POST` z poprawnym JSON-em zwraca 201, `id` z bazy, nagłówek `Location` i wysyła jeden mail.
- [ ] `POST` z nieznanym polem (także `id`) zwraca 422.
- [ ] `POST` bez pola wymaganego, ze złym typem (`"capacity": "5"`) albo z `end_time` nie późniejszym niż `start_time` zwraca 422.
- [ ] `POST` z nieistniejącym `organizer_id` lub `category_id` zwraca 422.
- [ ] `GET /events` zwraca tylko `published`, rosnąco po `start_time`; `limit=101` zwraca 422.
- [ ] `GET /events/{id}`: istniejące 200, nieistniejące 404.
- [ ] `PATCH` zmienia tylko podane pola, pozostałe zostają bez zmian.
- [ ] `PATCH` z pustym ciałem zwraca 422, a z samym `end_time` wcześniejszym niż zapisany start też 422.
- [ ] `PATCH` z niedozwolonym przejściem statusu albo na wydarzeniu `cancelled` zwraca 409.
- [ ] `DELETE` zwraca 405.
- [ ] Błąd SMTP nie zmienia odpowiedzi API i trafia do logu.
- [ ] Brak `email_for_organization` w POST zwraca 422, bo pole jest wymagane.
- [ ] Migracja Alembic działa w górę i w dół na pustej bazie.
