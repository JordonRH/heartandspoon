"""Operator-only, interactive account setup. Passwords are never echoed or printed."""
from getpass import getpass
from uuid import UUID

from sqlalchemy import select

from mealie.core.security import hash_password
from mealie.db.db_setup import session_context
from mealie.db.models.users.users import User
from mealie.hearth.models import Audit, OAuthGrant, WebSession


def main() -> None:
    email = input("Owner email: ").strip()
    name = input("Display name: ").strip()
    password = getpass("New password (at least 14 characters): ")
    confirm = getpass("Repeat password: ")
    if "@" not in email or not name or password != confirm or len(password) < 14 or len(password.encode()) > 72:
        raise SystemExit("Email, name or password validation failed; no changes made.")
    with session_context() as session:
        user = session.scalar(select(User).where(User.admin == True).order_by(User.created_at).limit(1))  # noqa E712
        if not user:
            raise SystemExit("Start the application and initialize its database first.")
        user.email = email
        user.username = email
        user.full_name = name
        user.password = hash_password(password)
        user.locked_at = None
        user.login_attemps = 0
        for model in (WebSession, OAuthGrant):
            for row in session.scalars(select(model).where(model.owner == str(user.id))):
                session.delete(row)
        session.add(Audit(owner=str(user.id), action="owner_configured", target=str(user.id)))
        session.commit()
    print("Owner account configured. Browser sessions and AI connections were revoked.")


if __name__ == "__main__":
    main()
