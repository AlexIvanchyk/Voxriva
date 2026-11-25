import base64
import smtplib
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from email import policy
from email.headerregistry import HeaderRegistry, MessageIDHeader
from email.message import EmailMessage as MIMEMessage
from email.utils import formatdate, make_msgid
from typing import Annotated, ClassVar, Literal, Self, cast

from pydantic import Field, SecretStr, StringConstraints, model_validator
from pydantic_core import PydanticCustomError

from backend.app.features.identity.schemas import Email
from backend.app.shared.provider_contract import (
    BaseProvider,
    EmailMessage,
    ProviderConfig,
    ProviderError,
    ProviderResult,
    RenderedMessage,
)


class SMTPConfig(ProviderConfig):
    host: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=253,
            pattern="^[a-zA-Z0-9.:-]+$",
        ),
    ] = Field(title="SMTP host", description="Use mailpit for the local inbox.")
    port: int = Field(default=587, ge=1, le=65535, title="Port")
    tls: Literal["starttls", "ssl", "none"] = Field(
        default="starttls", title="Transport security"
    )
    username: str = Field(default="", max_length=254, title="Username")
    password: SecretStr | None = Field(
        default=None, title="Password", json_schema_extra={"writeOnly": True}
    )
    sender: Email = Field(title="Sender email")
    timeout: int = Field(default=5, ge=1, le=15, title="Timeout (seconds)")

    @model_validator(mode="after")
    def authentication(self) -> Self:
        has_password = bool(self.password and self.password.get_secret_value())
        if bool(self.username) != has_password:
            raise PydanticCustomError(
                "smtp_auth_pair", "Username and password must be configured together"
            )
        if self.username and self.tls == "none":
            raise PydanticCustomError(
                "smtp_auth_tls", "SMTP authentication requires TLS"
            )
        if self.password and len(self.password.get_secret_value()) > 8192:
            raise PydanticCustomError(
                "smtp_secret_length", "Password exceeds the supported length"
            )
        return self


class SMTPProvider(BaseProvider):
    key = "smtp"
    name = "SMTP"
    channel: ClassVar[Literal["email", "push"]] = "email"
    config_model = SMTPConfig

    @contextmanager
    def connection(self) -> Iterator[smtplib.SMTP]:
        config = SMTPConfig.model_validate(self.config)
        self._message_in_flight = False
        client: smtplib.SMTP | None = None
        try:
            context = ssl.create_default_context()
            if config.tls == "ssl":
                client = smtplib.SMTP_SSL(
                    config.host, config.port, timeout=config.timeout, context=context
                )
            else:
                client = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
            client.ehlo_or_helo_if_needed()
            if config.tls == "starttls":
                client.starttls(context=context)
                client.ehlo()
            if config.username and config.password:
                client.login(config.username, config.password.get_secret_value())
            yield client
        except smtplib.SMTPAuthenticationError as error:
            raise ProviderError(
                "authentication_failed", 400 <= error.smtp_code < 500, uncertain=False
            ) from None
        except ssl.SSLError:
            raise ProviderError("tls_failed", uncertain=False) from None
        except smtplib.SMTPNotSupportedError:
            raise ProviderError("capability_unavailable", uncertain=False) from None
        except smtplib.SMTPRecipientsRefused as error:
            raise ProviderError(
                "recipient_rejected",
                any(400 <= value[0] < 500 for value in error.recipients.values()),
                uncertain=False,
            ) from None
        except smtplib.SMTPResponseException as error:
            raise ProviderError(
                "smtp_rejected", 400 <= error.smtp_code < 500, uncertain=False
            ) from None
        except (OSError, smtplib.SMTPException):
            raise ProviderError(
                "connection_failed", True, uncertain=self._message_in_flight
            ) from None
        finally:
            if client is not None:
                client.close()

    def test_connection(self) -> ProviderResult:
        with self.connection() as client:
            code, _ = client.noop()
            if code != 250:
                raise ProviderError("connection_failed", True)
        return ProviderResult(
            status="connected",
            message="SMTP connection and configured authentication succeeded. No email was sent.",
        )

    def send(self, message: RenderedMessage) -> ProviderResult:
        if not isinstance(message, EmailMessage):
            raise ProviderError("unsupported_channel")
        config = SMTPConfig.model_validate(self.config)
        # Content-ID has msg-id syntax. Treating a long CID as unstructured text
        # lets the email package RFC 2047-encode it, which breaks cid: references
        # in clients that correctly compare the literal MIME identifier.
        headers = HeaderRegistry()
        # HeaderRegistry combines this stdlib mixin with BaseHeader at runtime.
        headers.map_to_type("content-id", MessageIDHeader)  # type: ignore[arg-type]
        email = MIMEMessage(policy=policy.SMTP.clone(header_factory=headers))
        email["From"] = config.sender
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email["Date"] = formatdate(localtime=False)
        email["Message-ID"] = make_msgid(domain="voxriva.local")
        email.set_content(message.text)
        if message.html:
            email.add_alternative(message.html, subtype="html")
            for image in message.images:
                cast(MIMEMessage, email.get_payload(-1)).add_related(
                    base64.b64decode(image.content_base64, validate=True),
                    maintype="image",
                    subtype=image.media_type.split("/")[1],
                    cid="<" + image.cid + ">",
                    disposition="inline",
                )
        with self.connection() as client:
            self._message_in_flight = True
            refused = client.send_message(
                email, from_addr=config.sender, to_addrs=[message.recipient]
            )
            if refused:
                raise ProviderError("recipient_rejected", uncertain=False)
        return ProviderResult(
            status="accepted",
            message="The SMTP server accepted the test email. This does not confirm inbox delivery.",
            message_id=str(email["Message-ID"]),
        )
