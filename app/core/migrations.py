import argparse

from sqlalchemy.engine import make_url
from yoyo import get_backend, read_migrations

from app.core.config import PROJECT_ROOT
from app.core.database import database_url


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage versioned MySQL SQL migrations")
    parser.add_argument("command", choices=["apply", "list", "rollback"])
    parser.add_argument(
        "--confirm", action="store_true", help="Confirm rollback of the latest migration"
    )
    args = parser.parse_args()
    if args.command == "rollback" and not args.confirm:
        parser.error("Rollback can delete data. Pass --confirm to roll back the latest migration.")

    # SQLAlchemy uses mysql+pymysql; Yoyo uses mysql with the same PyMySQL driver.
    url = make_url(database_url()).set(drivername="mysql")
    backend = get_backend(url.render_as_string(hide_password=False))
    migrations = read_migrations(str(PROJECT_ROOT / "db" / "migrations"))
    with backend.lock():
        if args.command == "apply":
            pending = backend.to_apply(migrations)
            backend.apply_migrations(pending)
            print(f"Applied {len(pending)} migration(s).")
        elif args.command == "rollback":
            applied = backend.to_rollback(migrations)
            if applied:
                backend.rollback_migrations(applied[:1])
                print("Rolled back the latest migration.")
            else:
                print("No applied migrations to roll back.")
        else:
            pending_ids = {migration.id for migration in backend.to_apply(migrations)}
            for migration in migrations:
                state = "pending" if migration.id in pending_ids else "applied"
                print(f"{state:7} {migration.id}")


if __name__ == "__main__":
    main()
