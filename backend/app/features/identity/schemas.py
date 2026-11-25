from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from backend.app.features.identity.models import Account

Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=254,
        pattern="^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$",
    ),
]
Password = Annotated[str, StringConstraints(min_length=12, max_length=256)]


class Credentials(BaseModel):
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]


class NewAccount(BaseModel):
    email: Email
    password: Password


class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    platform_admin: bool


class SessionView(BaseModel):
    account: AccountView
    csrf_token: str


@dataclass(frozen=True)
class Principal:
    account: Account
    token: str


class MFAChallengeView(BaseModel):
    mfa_required: bool = True
    challenge: str
    expires_in: int = 300
    enrollment_required: bool = False


class MFAVerification(BaseModel):
    challenge: Annotated[str, StringConstraints(min_length=43, max_length=43)]
    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class MFAProof(BaseModel):
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    code: Annotated[str, StringConstraints(max_length=64)] = ""


class MFACode(BaseModel):
    code: Annotated[str, StringConstraints(min_length=1, max_length=64)]


class MFAEnrollment(BaseModel):
    challenge: Annotated[str, StringConstraints(min_length=43, max_length=43)]
