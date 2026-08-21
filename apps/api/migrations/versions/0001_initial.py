from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from elyon_api.models import Base

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from elyon_api.models import Base

    Base.metadata.drop_all(bind=op.get_bind())