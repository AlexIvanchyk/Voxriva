from datetime import UTC, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_populated_organization_migration_preserves_projects_users_keys_sessions_and_shared_templates(
    tmp_path,
):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    now = datetime.now(UTC)
    (
        org_a,
        org_b,
        proj_a,
        proj_b,
        account,
        template_a,
        template_b,
        env,
        key,
        audit_id,
    ) = [uuid4().hex for _ in range(10)]
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        for name in ["0002_dashboard_access", "0003_templates"]:
            import_module(f"migrations.versions.{name}").upgrade()
        metadata = sa.MetaData()

        def insert(table, rows):
            db.execute(sa.Table(table, metadata, autoload_with=db).insert(), rows)

        insert(
            "accounts",
            [
                {
                    "id": account,
                    "email": "synthetic@example.test",
                    "password_hash": "preserved-hash",
                    "platform_admin": False,
                }
            ],
        )
        insert(
            "dashboard_sessions",
            [
                {
                    "token_hash": "s" * 64,
                    "account_id": account,
                    "expires_at": now + timedelta(days=1),
                }
            ],
        )
        insert(
            "organizations",
            [{"id": org_a, "name": "Old A"}, {"id": org_b, "name": "Old B"}],
        )
        insert(
            "projects",
            [
                {"id": proj_a, "organization_id": org_a, "name": "App"},
                {"id": proj_b, "organization_id": org_a, "name": "Other app"},
            ],
        )
        insert(
            "memberships",
            [{"organization_id": org_a, "account_id": account, "role": "org_admin"}],
        )
        insert(
            "environments", [{"id": env, "project_id": proj_a, "name": "production"}]
        )
        insert(
            "delivery_keys",
            [
                {
                    "id": key,
                    "environment_id": env,
                    "name": "Integration",
                    "prefix": "vxk_example",
                    "token_hash": "k" * 64,
                    "created_at": now,
                    "expires_at": None,
                    "revoked_at": None,
                }
            ],
        )
        insert(
            "templates",
            [
                {
                    "id": template_a,
                    "organization_id": org_a,
                    "key": "welcome",
                    "name": "Shared welcome",
                    "channel": "email",
                    "draft": {"subject": "Preserve this"},
                    "draft_revision": 4,
                    "updated_at": now,
                },
                {
                    "id": template_b,
                    "organization_id": org_b,
                    "key": "welcome",
                    "name": "Orphan welcome",
                    "channel": "push",
                    "draft": {"title": "Preserve push"},
                    "draft_revision": 2,
                    "updated_at": now,
                },
            ],
        )
        insert(
            "audit_events",
            [
                {
                    "id": audit_id,
                    "actor_id": account,
                    "organization_id": org_a,
                    "action": "membership.create",
                    "target_id": account,
                    "created_at": now,
                }
            ],
        )
        import_module("migrations.versions.0004_project_workspaces").upgrade()
        inspector = sa.inspect(db)
        assert "organizations" not in inspector.get_table_names()
        for table in ["projects", "memberships", "templates", "audit_events"]:
            assert "organization_id" not in {
                column["name"] for column in inspector.get_columns(table)
            }
        fresh = sa.MetaData()

        def rows(table):
            return list(
                db.execute(
                    sa.select(sa.Table(table, fresh, autoload_with=db))
                ).mappings()
            )

        assert (
            len(rows("projects")) == 3
        )  # The second library's otherwise-unassigned template is preserved.
        assert rows("accounts")[0]["password_hash"] == "preserved-hash"
        assert rows("dashboard_sessions")[0]["token_hash"] == "s" * 64
        assert rows("delivery_keys")[0]["token_hash"] == "k" * 64
        assert rows("environments")[0]["id"] == env
        assert {row["role"] for row in rows("memberships")} == {"project_admin"}
        assert len(rows("memberships")) == 2
        assert (
            len(rows("templates")) == 2
            and len({row["key"] for row in rows("templates")}) == 2
        )
        assert (
            next(row for row in rows("templates") if row["id"] == template_a)[
                "draft_revision"
            ]
            == 4
        )
        bindings = rows("template_projects")
        assert {
            row["project_id"] for row in bindings if row["template_id"] == template_a
        } == {proj_a, proj_b}
        assert rows("audit_events")[0]["legacy_scope"]["organization_name"] == "Old A"
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


def test_lifecycle_migration_preserves_existing_drafts_without_publishing_or_deploying(
    tmp_path,
):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}")
    identifier = uuid4().hex
    now = datetime.now(UTC)
    with engine.begin() as db, Operations.context(MigrationContext.configure(db)):
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        for name in [
            "0002_dashboard_access",
            "0003_templates",
            "0004_project_workspaces",
        ]:
            import_module(f"migrations.versions.{name}").upgrade()
        table = sa.Table("templates", sa.MetaData(), autoload_with=db)
        db.execute(
            table.insert().values(
                id=identifier,
                key="existing",
                name="Existing",
                channel="email",
                draft={"subject": "Keep existing draft"},
                draft_revision=9,
                updated_at=now,
            )
        )
        import_module("migrations.versions.0005_template_lifecycle").upgrade()
        branches = list(
            db.execute(
                sa.select(
                    sa.Table("template_branches", sa.MetaData(), autoload_with=db)
                )
            ).mappings()
        )
        assert len(branches) == 1 and branches[0]["template_id"] == identifier
        assert branches[0]["name"] == "main" and branches[0]["locale"] == "en"
        assert (
            branches[0]["draft_revision"] == 9
            and branches[0]["draft"]["subject"] == "Keep existing draft"
        )
        for name in [
            "template_versions",
            "template_deployments",
            "template_deployment_events",
        ]:
            assert (
                db.execute(
                    sa.select(sa.func.count()).select_from(
                        sa.Table(name, sa.MetaData(), autoload_with=db)
                    )
                ).scalar()
                == 0
            )
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()
