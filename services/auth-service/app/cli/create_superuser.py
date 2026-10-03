"""
Django `createsuperuser`-equivalent for this project.

Goes through AuthService.create_superuser() — NOT a raw SQL insert — so the
password gets the same bcrypt hashing as normal registration, and stays the
single source of truth for how a User row is built.

Usage (interactive, prompts for email/password):
    uv run python -m app.cli.create_superuser

Usage (non-interactive, e.g. a deploy/bootstrap script):
    uv run python -m app.cli.create_superuser --email admin@example.com --password "SuperSecret123!"
"""
import argparse
import asyncio
import getpass
import sys

from app.db.session import AsyncSessionLocal
from app.exceptions import UserAlreadyExistsError
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService


async def _create(email: str, password: str, full_name: str | None) -> None:
    async with AsyncSessionLocal() as session:
        service = AuthService(UserRepository(session), RefreshTokenRepository(session))
        try:
            user = await service.create_superuser(email=email, password=password, full_name=full_name)
        except UserAlreadyExistsError as e:
            print(f"Error: {e.message}", file=sys.stderr)
            sys.exit(1)
    print(f"Superuser created: {user.email} (id={user.id}, role={user.role})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an admin (superuser) account.")
    parser.add_argument("--email")
    parser.add_argument("--password", help="If omitted, you'll be prompted (hidden input).")
    parser.add_argument("--full-name", default=None)
    args = parser.parse_args()

    email = args.email or input("Email: ").strip()

    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Password (again): ")
        if password != confirm:
            print("Error: passwords do not match", file=sys.stderr)
            sys.exit(1)

    if len(password) < 8:
        print("Error: password must be at least 8 characters", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_create(email, password, args.full_name))


if __name__ == "__main__":
    main()
