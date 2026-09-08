"""Explicitly initialize or upgrade the configured local SQLite system."""

from app.core.lifecycle import initialize_database


if __name__ == "__main__":
    initialize_database()
    print("Database migration and protected admin initialization completed.")
