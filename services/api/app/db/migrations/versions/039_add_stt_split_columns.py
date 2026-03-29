"""Add stt_result_s3_key and stt_requested_at to drive_files.

Supports two-phase STT-then-split pipeline: drive-worker uploads audio,
STT worker transcribes on GPU, drive-worker runs speech-aware scene
detection with the result.
"""

import sqlalchemy as sa
from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "drive_files",
        sa.Column("stt_result_s3_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "drive_files",
        sa.Column(
            "stt_requested_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("drive_files", "stt_requested_at")
    op.drop_column("drive_files", "stt_result_s3_key")
