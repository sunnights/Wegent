# SPDX-FileCopyrightText: 2026 Weibo, Inc.
# SPDX-License-Identifier: Apache-2.0

"""Merge external knowledge and execution sentinel migration heads.

Revision ID: b6f9c2e41a7d
Revises: c9d8e7f6a5b4, a3b4c5d6e7f8
Create Date: 2026-08-19
"""

from typing import Sequence, Union

revision: str = "b6f9c2e41a7d"
down_revision: Union[str, Sequence[str], None] = (
    "c9d8e7f6a5b4",
    "a3b4c5d6e7f8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
