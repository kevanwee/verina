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
settings default is not enough). There is no self-signup and no
HTTP administration route; production provisioning is a separate, unreviewed design.
Output never echoes names, subjects or issuers.
"""

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy.exc import SQLAlchemyError

from verina.access.domain import InvalidIdentifierError
from verina.access.sql_identity import IdentityDirectory
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
    return parser


def run(argv: Sequence[str], settings: Settings) -> int:
    args = _parser().parse_args(list(argv))
    if "env" not in settings.model_fields_set or settings.env not in ("local", "test"):
        # The default env is "local"; provisioning must not rely on that default.
        print("provisioning requires VERINA_ENV explicitly set to local or test", file=sys.stderr)
        return 2
    engine = make_engine(settings.database_url)
    directory = IdentityDirectory(engine)
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
