"""Add the Hearth & Spoon workflow and immutable recipe history."""
from alembic import op

from mealie.db.models._model_base import SqlAlchemyBase
from mealie.hearth.models import TABLES

revision = "hearth001"
down_revision = "f3a1ae61d772"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    SqlAlchemyBase.metadata.create_all(connection, tables=TABLES)
    if connection.dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION hearth_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'Published kitchen history is immutable'; END; $$""")
        for table in ("hearth_revisions", "hearth_audit"):
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION hearth_immutable()")
    elif connection.dialect.name == "sqlite":
        for table in ("hearth_revisions", "hearth_audit"):
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'Published kitchen history is immutable'); END")


def downgrade() -> None:
    # Never silently erase a recipe archive through a migration rollback.
    raise RuntimeError("Restore a pre-upgrade backup to remove the kitchen schema")
