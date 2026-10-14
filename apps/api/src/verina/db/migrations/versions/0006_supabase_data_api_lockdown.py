"""Lock Verina tables away from Supabase's Data API roles (PostgreSQL only; ADR 009).

Revision ID: 0006_supabase_data_api_lockdown
Revises: 0005_accounts_and_organizations

Supabase exposes the ``public`` schema through its Data API (PostgREST) to the ``anon`` and
``authenticated`` roles, and its default privileges grant those roles access to new tables. The
anon key is public, so without this migration anyone could read or write Verina tables
directly. When either role exists (i.e. on Supabase), this migration:

* enables row level security on every Verina table, with **no policies** (default deny for any
  role that is not the table owner and lacks ``BYPASSRLS``);
* ``REVOKE ALL`` on every Verina table and trigger function from ``anon`` and ``authenticated``
  (trigger functions also from ``PUBLIC``; triggers keep firing because EXECUTE is checked
  only when a trigger is created);
* ``ALTER DEFAULT PRIVILEGES IN SCHEMA <current schema> REVOKE ALL`` on tables, sequences and
  functions from both roles, for objects later created by the migrating role.

RLS is enabled but **not FORCEd**: the API connects as the table owner (``postgres`` on
Supabase). ``FORCE ROW LEVEL SECURITY`` would apply the (empty) policy set to the owner too and
deny the application every row. The owner is trusted application code; the defence here is
against the Data API roles. A future least-privileged application role will need explicit
policies or ``BYPASSRLS`` (security review).

On plain PostgreSQL without those roles (CI, local) and on SQLite this is a no-op. Every
statement runs inside one ``DO`` block, so offline (``--sql``) output is equivalent. Downgrade
disables RLS but deliberately does not restore any grant to the Data API roles.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_supabase_data_api_lockdown"
down_revision: str | Sequence[str] | None = "0005_accounts_and_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERINA_TABLES = (
    "alembic_version",
    "audit_events",
    "audit_chain_head",
    "matters",
    "matter_mutation_receipts",
    "identity_principals",
    "identity_bindings",
    "organizations",
    "platform_admins",
    "directory_accounts",
    "admin_idempotency",
)
VERINA_FUNCTIONS = (
    "verina_audit_reject_change()",
    "verina_audit_head_forward_only()",
    "verina_receipts_reject_change()",
    "verina_admin_idempotency_reject_change()",
)
DATA_API_ROLES = ("anon", "authenticated")


def _array(values: Sequence[str]) -> str:
    # Constant identifiers defined above; never user input.
    return "ARRAY[" + ", ".join(f"'{v}'" for v in values) + "]"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        DO $$
        DECLARE
          api_role text;
          tbl text;
          fn text;
          locked boolean := false;
        BEGIN
          FOREACH api_role IN ARRAY {_array(DATA_API_ROLES)} LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = api_role) THEN
              locked := true;
              FOREACH tbl IN ARRAY {_array(VERINA_TABLES)} LOOP
                EXECUTE format('REVOKE ALL ON TABLE %I FROM %I', tbl, api_role);
              END LOOP;
              FOREACH fn IN ARRAY {_array(VERINA_FUNCTIONS)} LOOP
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', fn, api_role);
              END LOOP;
              EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM %I',
                current_schema(), api_role);
              EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM %I',
                current_schema(), api_role);
              EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM %I',
                current_schema(), api_role);
            END IF;
          END LOOP;
          IF locked THEN
            FOREACH tbl IN ARRAY {_array(VERINA_TABLES)} LOOP
              EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
            END LOOP;
            -- Trigger functions need no caller grants (EXECUTE is checked at CREATE TRIGGER
            -- by the owner only), so PUBLIC loses the PostgreSQL default too.
            FOREACH fn IN ARRAY {_array(VERINA_FUNCTIONS)} LOOP
              EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', fn);
            END LOOP;
          END IF;
        END
        $$
        """  # noqa: S608 - constant identifiers only, quoted with %I
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        f"""
        DO $$
        DECLARE
          tbl text;
        BEGIN
          FOREACH tbl IN ARRAY {_array(VERINA_TABLES)} LOOP
            EXECUTE format('ALTER TABLE %I DISABLE ROW LEVEL SECURITY', tbl);
          END LOOP;
        END
        $$
        """
    )
