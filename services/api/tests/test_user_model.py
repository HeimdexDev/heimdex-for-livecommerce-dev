import pytest
from sqlalchemy import UniqueConstraint

from app.modules.users.models import User


class TestUserModelConstraints:

    def test_unique_constraint_on_org_id_email(self):
        """(org_id, email) must be unique — prevents duplicate accounts per org."""
        constraints = [
            c for c in User.__table_args__
            if isinstance(c, UniqueConstraint)
        ]
        names = [c.name for c in constraints]
        assert "uq_users_org_id_email" in names

    def test_unique_constraint_columns(self):
        """The constraint must cover exactly org_id and email."""
        constraint = next(
            c for c in User.__table_args__
            if isinstance(c, UniqueConstraint) and c.name == "uq_users_org_id_email"
        )
        col_names = [col.name for col in constraint.columns]
        assert col_names == ["org_id", "email"]
