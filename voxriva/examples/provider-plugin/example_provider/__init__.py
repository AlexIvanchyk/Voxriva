"""An external, explicitly installed provider using Voxriva's version 1 contract."""
from backend.app.features.providers.adapters.smtp import SMTPProvider


class ExampleSMTPProvider(SMTPProvider):
    key = "example_smtp"
    name = "Example SMTP plugin"
