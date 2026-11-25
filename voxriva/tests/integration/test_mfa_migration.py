"""The additive MFA migration preserves existing identity rows byte for byte."""

from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def test_mfa_upgrade_preserves_existing_accounts_and_sessions(store):
    engine, _ = store
    migration = import_module("migrations.versions.0013_account_mfa")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        account = connection.execute(text("SELECT id FROM accounts")).scalar_one()
        connection.execute(
            text(
                "INSERT INTO dashboard_sessions (token_hash, account_id, expires_at) VALUES (:token, :account, :expires)"
            ),
            {"token": "f" * 64, "account": account, "expires": "2099-01-01 00:00:00"},
        )
        before_accounts = connection.execute(text("SELECT * FROM accounts")).all()
        before_sessions = connection.execute(
            text("SELECT * FROM dashboard_sessions")
        ).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert (
            connection.execute(text("SELECT * FROM accounts")).all() == before_accounts
        )
        assert (
            connection.execute(text("SELECT * FROM dashboard_sessions")).all()
            == before_sessions
        )
        assert {"account_mfa", "mfa_challenges"} <= set(
            inspect(connection).get_table_names()
        )
        assert (
            connection.execute(text("SELECT count(*) FROM account_mfa")).scalar_one()
            == 0
        )
