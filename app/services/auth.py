"""Operadores, senhas (Argon2) e sessões do painel.

O bloqueio por tentativas fica em memória do processo: suficiente para um único processo;
com vários processos, cada um conta separadamente (documentado no README).
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.clock import Clock
from app.domain.operators import Operator, Role, Session
from app.repositories.base import Database, Tx

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,40}$")
MIN_PASSWORD_LENGTH = 10


class LoginError(Exception):
    """Falha de login. A mensagem ao usuário é sempre genérica."""


class OperatorError(ValueError):
    pass


@dataclass(frozen=True)
class AuthContext:
    operator: Operator
    session: Session


@dataclass
class _Failures:
    count: int = 0
    locked_until: datetime | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class AuthService:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        *,
        session_ttl: timedelta,
        max_failures: int,
        lockout: timedelta,
    ) -> None:
        self._db = db
        self._clock = clock
        self._session_ttl = session_ttl
        self._max_failures = max_failures
        self._lockout = lockout
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(16))
        self._failures: dict[str, _Failures] = {}

    # ── operadores ──────────────────────────────────────────────────────────

    @staticmethod
    def normalize_username(username: str) -> str:
        return username.strip().lower()

    def _validate_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise OperatorError(f"a senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres")

    async def create_operator(self, username: str, password: str, role: Role) -> Operator:
        username = self.normalize_username(username)
        if not USERNAME_RE.fullmatch(username):
            raise OperatorError("usuário: 3 a 40 caracteres entre a-z, 0-9, ponto, hífen e _")
        self._validate_password(password)
        operator = Operator(
            username=username,
            password_hash=self._hasher.hash(password),
            role=role,
            created_at=self._clock.now(),
        )
        async with self._db.transaction() as tx:
            await tx.add_operator(operator)
        return operator

    async def set_password(self, username: str, password: str) -> None:
        self._validate_password(password)
        async with self._db.transaction() as tx:
            operator = await self._require(tx, username)
            operator.password_hash = self._hasher.hash(password)
            await tx.save_operator(operator)
            await tx.delete_operator_sessions(operator.id)

    async def set_active(self, username: str, active: bool) -> None:
        async with self._db.transaction() as tx:
            operator = await self._require(tx, username)
            operator.active = active
            await tx.save_operator(operator)
            if not active:
                await tx.delete_operator_sessions(operator.id)

    async def _require(self, tx: Tx, username: str) -> Operator:
        operator = await tx.get_operator_by_username(self.normalize_username(username))
        if operator is None:
            raise OperatorError("operador não encontrado")
        return operator

    # ── login e sessão ──────────────────────────────────────────────────────

    def _is_locked(self, key: str, now: datetime) -> bool:
        state = self._failures.get(key)
        return bool(state and state.locked_until and state.locked_until > now)

    def _register_failure(self, key: str, now: datetime) -> None:
        state = self._failures.setdefault(key, _Failures())
        if state.locked_until and state.locked_until <= now:
            state.count, state.locked_until = 0, None
        state.count += 1
        if state.count >= self._max_failures:
            state.locked_until = now + self._lockout

    async def login(self, username: str, password: str) -> tuple[str, AuthContext]:
        """Devolve (token do cookie, contexto). O token só existe em memória e no cookie."""
        now = self._clock.now()
        key = self.normalize_username(username)
        if self._is_locked(key, now):
            raise LoginError("bloqueado")

        async with self._db.transaction() as tx:
            operator = await tx.get_operator_by_username(key)
            stored_hash = operator.password_hash if operator else self._dummy_hash
            try:
                self._hasher.verify(stored_hash, password)
                valid = operator is not None
            except (VerificationError, InvalidHashError):
                valid = False
            if not valid or operator is None or not operator.active:
                self._register_failure(key, now)
                raise LoginError("credenciais")

            self._failures.pop(key, None)
            if self._hasher.check_needs_rehash(operator.password_hash):
                operator.password_hash = self._hasher.hash(password)
            operator.last_login_at = now
            await tx.save_operator(operator)

            token = secrets.token_urlsafe(32)
            session = Session(
                token_hash=hash_token(token),
                operator_id=operator.id,
                csrf_token=secrets.token_urlsafe(32),
                created_at=now,
                expires_at=now + self._session_ttl,
            )
            await tx.add_session(session)
        return token, AuthContext(operator=operator, session=session)

    async def resolve(self, token: str | None) -> AuthContext | None:
        if not token:
            return None
        now = self._clock.now()
        async with self._db.transaction() as tx:
            session = await tx.get_session(hash_token(token))
            if session is None:
                return None
            if session.expires_at <= now:
                await tx.delete_session(session.token_hash)
                return None
            operator = await tx.get_operator(session.operator_id)
            if operator is None or not operator.active:
                return None
            return AuthContext(operator=operator, session=session)

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        async with self._db.transaction() as tx:
            await tx.delete_session(hash_token(token))
