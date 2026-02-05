"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-02-04

"""
from alembic import op
import sqlalchemy as sa

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("camera_id", sa.String(length=100), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
    )

    op.create_table(
        "detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capture_id", sa.Integer(), sa.ForeignKey("captures.id"), nullable=False, index=True),
        sa.Column("crop_path", sa.Text(), nullable=False),
        sa.Column("det_conf", sa.Float(), nullable=False, server_default="0"),
        sa.Column("bbox", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "plate_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("detection_id", sa.Integer(), sa.ForeignKey("detections.id"), nullable=False, index=True),
        sa.Column("plate_text", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("plate_text_norm", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("province", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.Enum("PENDING", "VERIFIED", name="readstatus"), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "verification_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("read_id", sa.Integer(), sa.ForeignKey("plate_reads.id"), nullable=False, unique=True),
        sa.Column("assigned_to", sa.String(length=100), nullable=True),
        sa.Column("corrected_text", sa.String(length=32), nullable=True),
        sa.Column("corrected_province", sa.String(length=64), nullable=True),
        sa.Column("result_type", sa.Enum("ALPR", "MLPR", name="verifyresulttype"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "master_plates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plate_text_norm", sa.String(length=32), nullable=False, unique=True, index=True),
        sa.Column("display_text", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("province", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("count_seen", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("editable", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "feedback_samples",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crop_path", sa.Text(), nullable=False),
        sa.Column("corrected_text", sa.String(length=32), nullable=False),
        sa.Column("corrected_province", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=100), nullable=False, server_default="MLPR"),
        sa.Column("used_in_train", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

def downgrade():
    op.drop_table("feedback_samples")
    op.drop_table("master_plates")
    op.drop_table("verification_jobs")
    op.drop_table("plate_reads")
    op.drop_table("detections")
    op.drop_table("captures")
    op.execute("DROP TYPE IF EXISTS verifyresulttype")
    op.execute("DROP TYPE IF EXISTS readstatus")
