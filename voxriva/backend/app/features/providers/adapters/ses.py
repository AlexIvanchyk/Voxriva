"""Amazon SES v2. SDK retries are disabled: the durable worker owns retry policy."""

import base64
import re
from typing import Any, ClassVar, Literal, Self

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    CredentialRetrievalError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
)
from pydantic import Field, SecretStr, model_validator
from pydantic_core import PydanticCustomError

from backend.app.features.identity.schemas import Email
from backend.app.shared.provider_contract import (
    BaseProvider,
    Capabilities,
    EmailMessage,
    ProviderConfig,
    ProviderError,
    ProviderResult,
    RenderedMessage,
)


class SESConfig(ProviderConfig):
    region: str = Field(
        default="us-east-1",
        pattern="^[a-z]{2}(?:-[a-z]+)+-[0-9]+$",
        max_length=40,
        title="AWS region",
    )
    sender: Email = Field(title="Verified sender email")
    auth_mode: Literal["default", "access_keys"] = Field(
        default="default",
        title="Authentication",
        description="Default uses the AWS credential chain, including an IAM workload role. Access keys are encrypted.",
    )
    access_key_id: SecretStr | None = Field(default=None, title="AWS access key ID")
    secret_access_key: SecretStr | None = Field(
        default=None, title="AWS secret access key"
    )
    session_token: SecretStr | None = Field(default=None, title="AWS session token")
    configuration_set: str = Field(
        default="",
        pattern="^[A-Za-z0-9_-]*$",
        max_length=64,
        title="Configuration set",
        description="Enable SES Delivery and Bounce events to the SNS topic below.",
    )
    sns_topic_arn: str = Field(
        default="",
        max_length=256,
        title="SNS topic ARN",
        description="Optional signed delivery events. Subscribe the provider's SES event URL with SNS signature version 2.",
    )
    timeout: int = Field(default=10, ge=1, le=15, title="Network timeout (seconds)")

    @model_validator(mode="after")
    def credentials(self) -> Self:
        values = [
            value.get_secret_value() if value else ""
            for value in [
                self.access_key_id,
                self.secret_access_key,
                self.session_token,
            ]
        ]
        if self.auth_mode == "access_keys" and (not all(values[:2])):
            raise PydanticCustomError(
                "aws_credentials", "AWS credential settings are incomplete"
            )
        if self.auth_mode == "default" and any(values):
            raise PydanticCustomError(
                "aws_credentials", "Remove saved access keys for workload credentials"
            )
        if any(len(value) > 16000 for value in values):
            raise ValueError("Credential is too long")
        if self.sns_topic_arn:
            match = re.fullmatch(
                "arn:(aws|aws-cn|aws-us-gov):sns:([^:]+):[0-9]{12}:[A-Za-z0-9_-]{1,256}",
                self.sns_topic_arn,
            )
            if not match or match[2] != self.region or (not self.configuration_set):
                raise PydanticCustomError(
                    "aws_topic",
                    "SNS topic requires a matching region and configuration set",
                )
        return self


class SESProvider(BaseProvider):
    key = "aws_ses"
    name = "Amazon SES"
    channel: ClassVar[Literal["email", "push"]] = "email"
    config_model = SESConfig
    capabilities = Capabilities(delivery_confirmation=True)

    def client(self, service: str = "sesv2") -> Any:
        config = SESConfig.model_validate(self.config)
        credentials = {}
        if config.auth_mode == "access_keys":
            credentials = {
                "aws_access_key_id": config.access_key_id.get_secret_value()
                if config.access_key_id
                else "",
                "aws_secret_access_key": config.secret_access_key.get_secret_value()
                if config.secret_access_key
                else "",
                "aws_session_token": config.session_token.get_secret_value()
                if config.session_token
                else None,
            }
        return boto3.Session(region_name=config.region, **credentials).client(
            service,
            config=Config(
                connect_timeout=config.timeout,
                read_timeout=config.timeout,
                retries={"total_max_attempts": 1},
            ),
        )

    def invoke(self, method: str, **kwargs: Any) -> dict[str, Any]:
        client = None
        started = False
        try:
            client = self.client()
            started = True
            result: dict[str, Any] = getattr(client, method)(**kwargs)
            return result
        except (NoCredentialsError, PartialCredentialsError):
            raise ProviderError("authentication_failed", uncertain=False) from None
        except CredentialRetrievalError:
            raise ProviderError(
                "authentication_failed", True, uncertain=False
            ) from None
        except (EndpointConnectionError, ConnectTimeoutError):
            raise ProviderError("connection_failed", True, uncertain=False) from None
        except ClientError as error:
            code = str(error.response.get("Error", {}).get("Code", ""))
            if code in {
                "TooManyRequestsException",
                "Throttling",
                "ThrottlingException",
                "LimitExceededException",
            }:
                raise ProviderError(
                    "rate_limited", True, uncertain=False, retry_after=60
                ) from None
            if code in {"ServiceUnavailableException", "ServiceUnavailable"}:
                raise ProviderError(
                    "service_unavailable", True, uncertain=False
                ) from None
            if code in {
                "AccessDenied",
                "AccessDeniedException",
                "UnauthorizedException",
            }:
                raise ProviderError("permission_denied", uncertain=False) from None
            if code in {
                "InvalidClientTokenId",
                "SignatureDoesNotMatch",
                "ExpiredToken",
                "UnrecognizedClientException",
            }:
                raise ProviderError("authentication_failed", uncertain=False) from None
            status = int(
                error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400)
            )
            raise ProviderError(
                "send_outcome_unknown" if status >= 500 else "message_rejected",
                uncertain=status >= 500,
            ) from None
        except BotoCoreError:
            raise ProviderError(
                "connection_failed", not started, uncertain=started
            ) from None
        finally:
            if client is not None:
                client.close()

    def test_connection(self) -> ProviderResult:
        result = self.invoke("get_account")
        if not result.get("SendingEnabled"):
            raise ProviderError("sending_disabled", uncertain=False)
        return ProviderResult(
            status="connected",
            message="SES account authentication succeeded and sending is enabled. Sender verification and sandbox recipient restrictions still apply. No email was sent.",
        )

    def send(self, message: RenderedMessage) -> ProviderResult:
        if not isinstance(message, EmailMessage):
            raise ProviderError("unsupported_channel", uncertain=False)
        config = SESConfig.model_validate(self.config)
        content: dict[str, Any] = {
            "Subject": {"Data": message.subject, "Charset": "UTF-8"},
            "Body": {},
        }
        if message.text:
            content["Body"]["Text"] = {"Data": message.text, "Charset": "UTF-8"}
        if message.html:
            content["Body"]["Html"] = {"Data": message.html, "Charset": "UTF-8"}
        if message.images:
            content["Attachments"] = [
                {
                    "RawContent": base64.b64decode(image.content_base64, validate=True),
                    "ContentType": image.media_type,
                    "ContentDisposition": "INLINE",
                    "ContentId": image.cid,
                    "FileName": image.cid.split("@")[0]
                    + "."
                    + image.media_type.split("/")[1],
                    "ContentTransferEncoding": "BASE64",
                }
                for image in message.images
            ]
        args: dict[str, Any] = {
            "FromEmailAddress": config.sender,
            "Destination": {"ToAddresses": [message.recipient]},
            "Content": {"Simple": content},
        }
        if config.configuration_set:
            args["ConfigurationSetName"] = config.configuration_set
        response = self.invoke("send_email", **args)
        identifier = response.get("MessageId")
        if not isinstance(identifier, str) or not re.fullmatch(
            "[A-Za-z0-9_-]{1,200}", identifier
        ):
            raise ProviderError("send_outcome_unknown")
        return ProviderResult(
            status="accepted",
            message="Amazon SES accepted the email. Inbox delivery is not yet confirmed.",
            message_id=identifier,
        )

    def confirm_subscription(self, topic: str, token: str) -> None:
        client = None
        try:
            client = self.client("sns")
            client.confirm_subscription(
                TopicArn=topic, Token=token, AuthenticateOnUnsubscribe="true"
            )
        except Exception:
            raise ProviderError("subscription_failed", uncertain=False) from None
        finally:
            if client is not None:
                client.close()
