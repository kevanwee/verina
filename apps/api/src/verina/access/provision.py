"""Local/dev provisioning of synthetic principals and token bindings (ADR 007).

Usage (``VERINA_DATABASE_URL`` selects the database; migrations must be applied)::

    python -m verina.access.provision principal --tenant t-demo --actor a-lawyer \
        --roles lawyer --display-name "Synthetic Lawyer"
    python -m verina.access.provision bind --issuer https://idp.example.test \
        --subject synthetic-sub-1 --tenant t-demo --actor a-lawyer
    python -m verina.access.provision deactivate --tenant t-demo --actor a-lawyer
    python -m verina.access.provision unbind --issuer https://idp.example.test \
        --subject synthetic-sub-1

Refuses to run unless ``VERINA_ENV`` is explicitly set to ``local`` or ``test`` (the
settings default is not enough). Each write is audited atomically in the tenant's chain.
Output never echoes names, subjects, issuers or e-mail addresses.

Platform-admin bootstrap (ADR 009)::

    python -m verina.access.provision bootstrap-platform-admin --email admin@example.com

invites (or finds) the Supabase user for that address via the Auth admin API and grants the
platform-admin role to its verified ``(issuer, subject)``. It refuses if any platform admin
already exists, and runs only when ``VERINA_ENV`` is explicitly ``local``, ``test`` or
``development`` with ``VERINA_AUTH_ISSUER``, ``VERINA_SUPABASE_URL`` and
``VERINA_SUPABASE_SECRET_KEY`` configured. Further platform admins are not creatable over HTTP.
"""

import argparse
import sys
from collections.abc import Callable, Sequence

from sqlalchemy.exc import SQLAlchemyError

from verina.access.accounts import AccountsError, bootstrap_platform_admin
from verina.access.auth_admin import AuthAdminError, AuthAdminPort, SupabaseAuthAdmin
from verina.access.domain import InvalidIdentifierError
from verina.access.sql_identity import IdentityDirectory
from verina.access.subject_hmac import derive_subject_key
from verina.audit.store import SqlAuditStore
from verina.config import Settings, get_settings
from verina.db import make_engine


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m verina.access.provision")
    sub = parser.add_subparsers(dest="command", required=True)

    principal = sub.add_parser("principal", help="create or update a synthetic principal")
    principal.add_argument("--tenant", required=True)
    principal.add_argument("--actor", required=True)
    principal.add_argument("--roles", default="", help="comma-separated role values")
    principal.add_argument("--display-name", default=None)

    for name in ("deactivate", "activate"):
        state = sub.add_parser(name, help=f"{name} a principal (profile is retained)")
        state.add_argument("--tenant", required=True)
        state.add_argument("--actor", required=True)

    bind = sub.add_parser("bind", help="bind a verified (issuer, subject) to a principal")
    bind.add_argument("--issuer", required=True)
    bind.add_argument("--subject", required=True)
    bind.add_argument("--tenant", required=True)
    bind.add_argument("--actor", required=True)

    unbind = sub.add_parser("unbind", help="remove an (issuer, subject) binding")
    unbind.add_argument("--issuer", required=True)
    unbind.add_argument("--subject", required=True)

    bootstrap = sub.add_parser(
        "bootstrap-platform-admin", help="invite the first platform administrator"
    )
    bootstrap.add_argument("--email", required=True)
    return parser


def _explicit_env(settings: Settings, allowed: tuple[str, ...]) -> bool:
    # The default env is "local"; provisioning must not rely on that default.
    return "env" in settings.model_fields_set and settings.env in allowed


def _supabase_admin(settings: Settings) -> AuthAdminPort:
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        raise AuthAdminError("misconfigured")
    return SupabaseAuthAdmin(
        settings.supabase_url, settings.supabase_secret_key, issuer=settings.auth_issuer
    )


def _bootstrap(
    args: argparse.Namespace,
    settings: Settings,
    auth_admin_factory: Callable[[Settings], AuthAdminPort],
) -> int:
    if not _explicit_env(settings, ("local", "test", "development")):
        print(
            "bootstrap requires VERINA_ENV explicitly set to local, test or development",
            file=sys.stderr,
        )
        return 2
    if not settings.auth_issuer:
        print("bootstrap requires VERINA_AUTH_ISSUER", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url)
    store = SqlAuditStore(
        engine,
        head_key=(
            settings.audit_head_key.get_secret_value().encode("utf-8")
            if settings.audit_head_key is not None
            else None
        ),
    )
    try:
        bootstrap_platform_admin(
            engine,
            store,
            auth_admin_factory(settings),
            issuer=settings.auth_issuer,
            email=args.email,
            redirect_to=settings.auth_invite_redirect_url,
            subject_key=derive_subject_key(settings.audit_head_key),
        )
    except AccountsError:
        print("rejected: a platform administrator already exists", file=sys.stderr)
        return 1
    except ValueError:
        print("rejected: invalid e-mail address", file=sys.stderr)
        return 1
    except AuthAdminError as exc:
        print(f"rejected: identity provider call failed ({exc.kind})", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("rejected: directory unavailable (are migrations applied?)", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print("ok: platform administrator invited; they sign in from the invitation e-mail")
    return 0


def run(
    argv: Sequence[str],
    settings: Settings,
    *,
    auth_admin_factory: Callable[[Settings], AuthAdminPort] = _supabase_admin,
) -> int:
    args = _parser().parse_args(list(argv))
    if args.command == "bootstrap-platform-admin":
        return _bootstrap(args, settings, auth_admin_factory)
    if not _explicit_env(settings, ("local", "test")):
        print("provisioning requires VERINA_ENV explicitly set to local or test", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url)
    key = settings.audit_head_key
    directory = IdentityDirectory(
        engine,
        audit=SqlAuditStore(
            engine, head_key=key.get_secret_value().encode("utf-8") if key is not None else None
        ),
        subject_key=derive_subject_key(key),
    )
    try:
        if args.command == "principal":
            roles = [r.strip() for r in args.roles.split(",") if r.strip()]
            revision = directory.upsert_principal(
                args.tenant, args.actor, roles, display_name=args.display_name
            )
            print(f"ok revision={revision}")
        elif args.command in ("deactivate", "activate"):
            revision = directory.set_active(args.tenant, args.actor, args.command == "activate")
            print(f"ok revision={revision}")
        elif args.command == "bind":
            directory.bind(args.issuer, args.subject, args.tenant, args.actor)
            print("ok")
        else:
            removed = directory.unbind(args.issuer, args.subject)
            print("ok" if removed else "not found")
            return 0 if removed else 1
    except (InvalidIdentifierError, ValueError, LookupError):
        print("rejected: invalid or conflicting provisioning input", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("rejected: directory unavailable (are migrations applied?)", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


def main() -> int:  # pragma: no cover - thin process entry point
    return run(sys.argv[1:], get_settings())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
