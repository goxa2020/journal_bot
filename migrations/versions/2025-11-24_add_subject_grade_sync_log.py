"""add_subject_grade_sync_log

Revision ID: c67b204d61fa
Revises: e4b7e8c165c1
Create Date: 2025-11-24 01:15:21.137480

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = 'c67b204d61fa'
down_revision: Union[str, None] = 'e4b7e8c165c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('subjects',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('teacher', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=text("TIMEZONE('utc+3', now())"), nullable=False),
        sa.UniqueConstraint('user_id', 'code', name='unique_user_subject_code'),
    )
    op.create_table('grades',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True, primary_key=True),
        sa.Column('subject_id', sa.Integer(), sa.ForeignKey('subjects.id'), nullable=False, index=True),
        sa.Column('date', sa.DateTime(), nullable=False),
        sa.Column('value', sa.String(length=20), nullable=False),
        sa.Column('type_', sa.String(length=50), nullable=False),
        sa.Column('comment', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=text("TIMEZONE('utc+3', now())"), nullable=False),
    )
    op.create_table('sync_logs',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True, primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=text("TIMEZONE('utc+3', now())")),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('error_msg', sa.String(length=1000), nullable=True),
        sa.Column('grades_count', sa.Integer(), server_default=text('0'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('sync_logs')
    op.drop_table('grades')
    op.drop_table('subjects')
