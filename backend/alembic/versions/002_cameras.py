"""add cameras table

Revision ID: 002_cameras
Revises: 001_initial
Create Date: 2026-02-05
"""
from alembic import op
import sqlalchemy as sa

revision = "002_cameras"
down_revision = "001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("camera_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("rtsp_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_cameras_camera_id", "cameras", ["camera_id"], unique=True)

def downgrade():
    op.drop_index("ix_cameras_camera_id", table_name="cameras")
    op.drop_table("cameras")
