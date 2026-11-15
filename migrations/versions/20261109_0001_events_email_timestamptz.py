"""events: email_for_organization, description NOT NULL, TIMESTAMPTZ, indeksy

Zmienia istniejącą tabelę events (schemat z pierwszej wersji projektu):
- dodaje kolumnę email_for_organization VARCHAR(254) NOT NULL,
- ustawia description NOT NULL,
- zmienia start_time i end_time z TIMESTAMP na TIMESTAMPTZ
  (dotychczasowe wartości są traktowane jako UTC),
- dodaje indeksy idx_organizer_id i idx_status_start_time.

Gdy w tabeli są już wiersze z pustym description albo bez adresu e-mail,
migracja zatrzymuje się z czytelnym błędem. Uzupełnij wtedy dane ręcznie
i uruchom ją ponownie (DDL w PostgreSQL jest transakcyjny, więc nic
nie zostaje w połowie zmienione).

Revision ID: 20261109_0001
Revises:
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = "20261109_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events", sa.Column("email_for_organization", sa.String(254), nullable=True)
    )

    # kolumna dopiero co dodana, więc email jest NULL w każdym istniejącym wierszu
    problems = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM events "
            "WHERE description IS NULL OR email_for_organization IS NULL"
        )
    ).scalar_one()
    if problems:
        raise RuntimeError(
            f"events ma {problems} wierszy bez description lub email_for_organization. "
            "Uzupełnij dane (UPDATE events SET ...) i uruchom migrację ponownie."
        )

    op.alter_column("events", "email_for_organization", nullable=False)
    op.alter_column("events", "description", existing_type=sa.Text(), nullable=False)

    for column in ("start_time", "end_time"):
        op.alter_column(
            "events",
            column,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )

    op.create_index("idx_organizer_id", "events", ["organizer_id"])
    op.create_index("idx_status_start_time", "events", ["status", "start_time"])


def downgrade() -> None:
    op.drop_index("idx_status_start_time", table_name="events")
    op.drop_index("idx_organizer_id", table_name="events")

    for column in ("end_time", "start_time"):
        op.alter_column(
            "events",
            column,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=False,
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )

    op.alter_column("events", "description", existing_type=sa.Text(), nullable=True)
    op.drop_column("events", "email_for_organization")
