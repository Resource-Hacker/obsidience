"""Write-only connection credentials in the workstation's encrypted user store.

Definitions and Source never contain secrets. A credential is bound to an exact
connection and HTTPS origin, so editing a connection cannot forward an old token
to a different provider. systemd owns encryption; this is only its bounded adapter.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit


class CredentialError(ValueError):
    pass


def origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise CredentialError("A valid connection URL is required")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise CredentialError("Invalid connection port") from exc
    return f"{parsed.scheme}://{parsed.hostname.lower()}:{port}"


class CredentialStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path.home() / ".config/obsidience/connections"

    def _path(self, connection_id: str, url: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", connection_id):
            raise CredentialError("Invalid connection identity")
        digest = hashlib.sha256(origin(url).encode()).hexdigest()[:24]
        return self.directory / f"{connection_id}-{digest}.cred"

    def configured(self, connection_id: str, url: str) -> bool:
        return self._path(connection_id, url).is_file()

    def save(self, connection_id: str, url: str, secret: str) -> None:
        if urlsplit(url).scheme != "https":
            raise CredentialError("Credentials require an HTTPS connection")
        if not isinstance(secret, str) or not secret or len(secret) > 8192:
            raise CredentialError("Enter a credential of at most 8192 characters")
        if any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise CredentialError("HTTP credentials must contain printable characters without spaces")
        destination = self._path(connection_id, url)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        fd, temporary = tempfile.mkstemp(prefix=".credential-", dir=self.directory)
        os.close(fd)
        try:
            # Plaintext crosses stdin only, never argv, a file, or logging.
            self._run([
                "encrypt", "--user", "--name=" + destination.stem,
                "-", temporary,
            ], input=secret.encode())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def delete(self, connection_id: str, url: str) -> None:
        self._path(connection_id, url).unlink(missing_ok=True)

    def delete_connection(self, connection_id: str) -> None:
        self._path(connection_id, "https://validation.invalid")
        for path in self.directory.glob(f"{connection_id}-*.cred"):
            if re.fullmatch(re.escape(connection_id) + r"-[0-9a-f]{24}\.cred", path.name):
                path.unlink(missing_ok=True)

    def headers(self, connection_id: str, url: str, mode: str) -> dict[str, str]:
        if mode == "none":
            return {}
        if mode not in {"bearer", "bot"} or urlsplit(url).scheme != "https":
            raise CredentialError("This authentication mode requires an HTTPS connection")
        path = self._path(connection_id, url)
        if not path.is_file():
            raise CredentialError("Add a credential for this connection first")
        secret = self._run([
            "decrypt", "--user", "--refuse-null", "--name=" + path.stem,
            str(path), "-",
        ]).decode("ascii")
        if not secret or len(secret) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in secret):
            raise CredentialError("The stored HTTP credential is invalid")
        return {"Authorization": ("Bot " if mode == "bot" else "Bearer ") + secret}

    @staticmethod
    def _run(arguments: list[str], *, input: bytes | None = None) -> bytes:
        try:
            result = subprocess.run(
                ["/usr/bin/systemd-creds", "--no-ask-password", "--quiet", *arguments],
                input=input, capture_output=True, timeout=15, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CredentialError("The encrypted credential store is unavailable") from exc
        if result.returncode:
            # Never relay credential subprocess output to the pane or trace.
            raise CredentialError("The encrypted credential operation failed")
        return result.stdout
