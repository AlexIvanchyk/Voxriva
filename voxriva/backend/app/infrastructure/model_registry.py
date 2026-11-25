"""Import all owned models before schema creation or migration metadata inspection."""

from backend.app.features.deployments.models import DeploymentEvent as DeploymentEvent
from backend.app.features.deployments.models import (
    TemplateDeployment as TemplateDeployment,
)
from backend.app.features.identity.models import Account as Account
from backend.app.features.identity.models import AccountMFA as AccountMFA
from backend.app.features.identity.models import AuditEvent as AuditEvent
from backend.app.features.identity.models import BootstrapLock as BootstrapLock
from backend.app.features.identity.models import DashboardSession as DashboardSession
from backend.app.features.identity.models import MFAChallenge as MFAChallenge
from backend.app.features.management.models import (
    ManagementCredential as ManagementCredential,
)
from backend.app.features.notifications.models import Notification as Notification
from backend.app.features.notifications.models import (
    NotificationAttempt as NotificationAttempt,
)
from backend.app.features.notifications.models import (
    NotificationOutbox as NotificationOutbox,
)
from backend.app.features.notifications.models import WorkerEvent as WorkerEvent
from backend.app.features.notifications.models import WorkerHeartbeat as WorkerHeartbeat
from backend.app.features.projects.models import DeliveryKey as DeliveryKey
from backend.app.features.projects.models import Environment as Environment
from backend.app.features.projects.models import Membership as Membership
from backend.app.features.projects.models import Project as Project
from backend.app.features.providers.models import ProviderBinding as ProviderBinding
from backend.app.features.providers.models import (
    ProviderConfiguration as ProviderConfiguration,
)
from backend.app.features.providers.models import ProviderEvent as ProviderEvent
from backend.app.features.providers.models import ProviderRevision as ProviderRevision
from backend.app.features.templates.models import Template as Template
from backend.app.features.templates.models import TemplateBranch as TemplateBranch
from backend.app.features.templates.models import TemplateProject as TemplateProject
from backend.app.features.templates.models import TemplateVersion as TemplateVersion
from backend.app.infrastructure.database import Base as Base
from backend.app.infrastructure.database import utcnow as utcnow
