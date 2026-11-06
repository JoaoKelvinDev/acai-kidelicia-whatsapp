"""Comandos de operação.

    uv run python -m app.cli migrate
    uv run python -m app.cli create-operator --username joao --role admin
    uv run python -m app.cli set-password --username joao
    uv run python -m app.cli deactivate-operator --username joao
    uv run python -m app.cli purge [--dry-run]

A senha é pedida no terminal (sem eco). Para automação, --password-stdin lê da entrada padrão.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict

from alembic import command

from app.core.config import Settings
from app.core.container import Container, build_container
from app.db.engine import alembic_config
from app.domain.operators import Role
from app.repositories.base import DuplicateError
from app.services.auth import OperatorError


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Senha: ")
    if getpass.getpass("Repita a senha: ") != first:
        raise OperatorError("as senhas não conferem")
    return first


def _run(settings: Settings, action: Callable[[Container], Awaitable[None]]) -> None:
    async def runner() -> None:
        container = build_container(settings)
        try:
            await action(container)
        finally:
            await container.aclose()

    asyncio.run(runner())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="aplica as migrações do banco")

    create = sub.add_parser("create-operator", help="cria um operador do painel")
    create.add_argument("--username", required=True)
    create.add_argument("--role", choices=[r.value for r in Role], required=True)
    create.add_argument("--password-stdin", action="store_true")

    password = sub.add_parser("set-password", help="troca a senha e encerra as sessões")
    password.add_argument("--username", required=True)
    password.add_argument("--password-stdin", action="store_true")

    deactivate = sub.add_parser("deactivate-operator", help="desativa e encerra as sessões")
    deactivate.add_argument("--username", required=True)

    purge = sub.add_parser("purge", help="aplica a política de retenção")
    purge.add_argument("--dry-run", action="store_true", help="só conta, sem alterar nada")

    args = parser.parse_args(argv)
    settings = Settings()

    try:
        if args.command == "migrate":
            command.upgrade(alembic_config(settings.database_url), "head")
            print("Banco atualizado.")
        elif args.command == "create-operator":
            secret = _read_password(args.password_stdin)
            _run(
                settings,
                lambda c: _discard(c.auth.create_operator(args.username, secret, Role(args.role))),
            )
            print(f"Operador criado: {args.username.strip().lower()} ({args.role})")
        elif args.command == "set-password":
            secret = _read_password(args.password_stdin)
            _run(settings, lambda c: c.auth.set_password(args.username, secret))
            print("Senha alterada; sessões abertas foram encerradas.")
        elif args.command == "deactivate-operator":
            _run(settings, lambda c: c.auth.set_active(args.username, False))
            print("Operador desativado.")
        elif args.command == "purge":
            reports = []

            async def do_purge(c: Container) -> None:
                reports.append(await c.retention.purge(dry_run=args.dry_run))

            _run(settings, do_purge)
            for key, value in asdict(reports[0]).items():
                print(f"{key}: {value}")
    except (OperatorError, DuplicateError) as exc:
        message = f"operador já existe: {exc}" if isinstance(exc, DuplicateError) else str(exc)
        print(f"Erro: {message}", file=sys.stderr)
        return 1
    return 0


async def _discard(awaitable: Awaitable[object]) -> None:
    await awaitable


if __name__ == "__main__":
    raise SystemExit(main())
