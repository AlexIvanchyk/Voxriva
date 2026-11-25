"""Initialize a persistent key for the local Compose installation; never overwrite it."""

import os
from pathlib import Path

from cryptography.fernet import Fernet

if __name__ == "__main__":
    folder = Path("/secrets")
    folder.mkdir(exist_ok=True)
    os.chown(folder, 10001, 10001)
    folder.chmod(0o700)
    path = folder / "providers.key"
    if not path.exists():
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
        with os.fdopen(descriptor, "wb") as output:
            output.write(Fernet.generate_key())
    os.chown(path, 10001, 10001)
    path.chmod(0o400)
