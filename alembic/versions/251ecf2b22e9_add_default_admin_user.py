"""Add default admin user

Revision ID: 251ecf2b22e9
Revises: 3f5c8b09eab6
Create Date: 2025-06-06 19:17:10.166931

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import secrets
from uuid import uuid4


# revision identifiers, used by Alembic.
revision: str = '251ecf2b22e9'
down_revision: Union[str, None] = '3f5c8b09eab6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    admin_id = str(uuid4())
    api_key = secrets.token_urlsafe(32)[:43]
    
    op.execute(
        f"""
        INSERT INTO users (id, name, role, api_key, created_at)
        VALUES ('{admin_id}', 'admin', 'ADMIN', '{api_key}', NOW())
        ON CONFLICT (api_key) DO NOTHING
        """
    )

def downgrade():
    op.execute("DELETE FROM users WHERE name = 'admin'")
