"""Operadores do painel e sessões de login."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.domain.models import new_id


class Role(StrEnum):
    ADMIN = "admin"  # tudo, inclusive configuração da loja e pausa global
    ATTENDANT = "atendente"  # assumir, pausar, retomar e encerrar conversas


class Operator(BaseModel):
    id: str = Field(default_factory=new_id)
    username: str
    password_hash: str
    role: Role
    active: bool = True
    created_at: datetime
    last_login_at: datetime | None = None

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


class Session(BaseModel):
    token_hash: str  # sha256 do token do cookie; o token em si nunca é gravado
    operator_id: str
    csrf_token: str
    created_at: datetime
    expires_at: datetime
