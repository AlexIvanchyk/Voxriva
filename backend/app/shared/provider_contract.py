from abc import ABC, abstractmethod
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

PushToken = Annotated[
    str,
    StringConstraints(
        min_length=16, max_length=4096, pattern=r"^[A-Za-z0-9:._%~+=-]+$"
    ),
]


class Capabilities(BaseModel):
    test_connection: bool = True
    test_send: bool = True
    delivery_confirmation: bool = False
    validate_only: bool = False


class InlineImage(BaseModel):
    cid: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    content_base64: str


class EmailMessage(BaseModel):
    recipient: str
    subject: str
    text: str
    html: str = ""
    images: list[InlineImage] = []


class PushMessage(BaseModel):
    token: str
    title: str
    body: str
    data: dict[str, str] = {}


type RenderedMessage = EmailMessage | PushMessage


class ProviderResult(BaseModel):
    status: Literal["connected", "accepted"]
    message: str
    message_id: str | None = None


class ProviderError(Exception):
    """Only fixed, adapter-owned error codes may cross the transport boundary."""

    def __init__(
        self,
        code: str,
        retryable: bool = False,
        *,
        uncertain: bool = True,
        retry_after: float | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.uncertain = uncertain
        self.retry_after = retry_after
        super().__init__(code)


class ProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BaseProvider(ABC):
    interface_version: ClassVar[int] = 1
    key: ClassVar[str]
    name: ClassVar[str]
    channel: ClassVar[Literal["email", "push"]]
    config_model: ClassVar[type[ProviderConfig]]
    capabilities: ClassVar[Capabilities] = Capabilities()

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    def test_connection(self) -> ProviderResult: ...

    def validate(self, message: RenderedMessage) -> ProviderResult:
        raise ProviderError("capability_unavailable", uncertain=False)

    @abstractmethod
    def send(self, message: RenderedMessage) -> ProviderResult: ...
