"""merge external knowledge and smart app marketplace heads

Revision ID: 562552bdf2c7
Revises: b6f9c2e41a7d, f82c5d1a9e37
Create Date: 2026-08-25 14:29:20.332851+08:00

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "562552bdf2c7"
down_revision: Union[str, Sequence[str], None] = ("b6f9c2e41a7d", "f82c5d1a9e37")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
