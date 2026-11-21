"""grades: lesson key, surrogate PK

Revision ID: 2026_11_21_grades_v2
Revises: 217e8389fd0e
Create Date: 2026-11-21

Фаза 2, задача 2.1 (docs/ARCHITECTURE.md §8):

* `grades.id` — суррогатный `BIGSERIAL`, а не `dateID` из edu-tpi;
* `edu_lesson_id` — информационное поле (`dateID`);
* `hour_number` — номер пары, вторая часть ключа урока;
* `UNIQUE (user_id, journal_id, date, hour_number)`;
* индексы `(user_id, journal_id, date)` и `(journal_id)`;
* старые `uq_user_lesson_journal` и `idx_user_lesson` удалены.

Если в таблице уже есть строки, `hour_number` взять неоткуда (старая схема его не
хранила), а `DEFAULT 0` склеил бы разные пары одного дня. Поэтому миграция явно
останавливается с понятным сообщением: сначала нужно перенести данные вручную.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2026_11_21_grades_v2"
down_revision: Union[str, None] = "217e8389fd0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GRADES_BACKFILL_MESSAGE = (
    "Таблица grades не пуста: для UNIQUE(user_id, journal_id, date, hour_number) нужен "
    "hour_number, которого старая схема не хранила. Перенесите строки вручную "
    "(hour_number можно восстановить из ответа Journal: journalDates[].hourNumber) "
    "или очистите таблицу перед миграцией."
)


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT count(*) FROM grades")).scalar_one()
    if rows:
        raise RuntimeError(GRADES_BACKFILL_MESSAGE)

    op.drop_constraint("uq_user_lesson_journal", "grades", type_="unique")
    op.drop_constraint("grades_id_key", "grades", type_="unique")
    op.drop_index("idx_user_lesson", table_name="grades")

    # serial -> bigserial: тип колонки и тип последовательности меняются вместе,
    # иначе sequence остаётся INTEGER и упирается в 2^31.
    op.execute("ALTER TABLE grades ALTER COLUMN id DROP DEFAULT")
    op.alter_column(
        "grades",
        "id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        autoincrement=True,
    )
    op.execute("ALTER SEQUENCE grades_id_seq AS BIGINT")
    op.execute("ALTER TABLE grades ALTER COLUMN id SET DEFAULT nextval('grades_id_seq'::regclass)")

    op.add_column("grades", sa.Column("edu_lesson_id", sa.BigInteger(), nullable=True))
    op.add_column("grades", sa.Column("hour_number", sa.SmallInteger(), nullable=False))

    op.create_unique_constraint(
        "uq_grades_user_journal_date_hour",
        "grades",
        ["user_id", "journal_id", "date", "hour_number"],
    )
    # Индекс `idx_user_journal_date` уже создан миграцией 217e8389fd0e на те же
    # колонки (user_id, journal_id, date) — второй такой же не нужен.


def downgrade() -> None:
    op.drop_constraint("uq_grades_user_journal_date_hour", "grades", type_="unique")
    op.drop_column("grades", "hour_number")
    op.drop_column("grades", "edu_lesson_id")

    op.execute("ALTER TABLE grades ALTER COLUMN id DROP DEFAULT")
    op.alter_column(
        "grades",
        "id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        autoincrement=True,
    )
    op.execute("ALTER SEQUENCE grades_id_seq AS INTEGER")
    op.execute("ALTER TABLE grades ALTER COLUMN id SET DEFAULT nextval('grades_id_seq'::regclass)")

    op.create_unique_constraint("grades_id_key", "grades", ["id"])
    op.create_unique_constraint("uq_user_lesson_journal", "grades", ["id", "user_id", "journal_id"])
    op.create_index("idx_user_lesson", "grades", ["id", "user_id"], unique=False)
