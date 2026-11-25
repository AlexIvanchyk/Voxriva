"""Compatibility path for provider plugins and existing imports."""

from backend.app.shared.provider_contract import (
    BaseProvider as BaseProvider,
)
from backend.app.shared.provider_contract import (
    Capabilities as Capabilities,
)
from backend.app.shared.provider_contract import (
    EmailMessage as EmailMessage,
)
from backend.app.shared.provider_contract import (
    ProviderConfig as ProviderConfig,
)
from backend.app.shared.provider_contract import (
    ProviderError as ProviderError,
)
from backend.app.shared.provider_contract import (
    ProviderResult as ProviderResult,
)
from backend.app.shared.provider_contract import (
    PushMessage as PushMessage,
)
from backend.app.shared.provider_contract import (
    PushToken as PushToken,
)
from backend.app.shared.provider_contract import (
    RenderedMessage as RenderedMessage,
)
