"""Google sign-in for the open-source edition: the owner's own OAuth app, one account.

Flow:

1. The owner creates an OAuth client ("Desktop app") in Google Cloud and
   downloads its JSON (see ``docs/google-setup.md``).
2. ``m3allema google connect --client-secret client.json`` copies it into the
   workspace and opens Google's consent page in the browser.
3. The resulting token is encrypted with a key kept in the workspace ``.env``
   (``M3ALLEMA_SECRET_KEY``) and stored in ``.m3allema/google_token.enc``.

The model never sees the token; tools only receive ready API clients.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
)
"""Gmail (read, draft, label, send; no permanent delete), Calendar events, Sheets."""

SECRET_KEY_ENV = "M3ALLEMA_SECRET_KEY"  # noqa: S105 - the variable's name, not a secret


class GoogleAuthError(Exception):
    """Google is not connected, or the stored sign-in can no longer be used."""


class TokenVault:
    """Encrypts and stores one token on disk.

    Args:
        path: Where the encrypted token lives.
        key: A Fernet key (URL-safe base64, 32 bytes).

    """

    def __init__(self, path: Path, key: str) -> None:
        self._path = path
        self._fernet = Fernet(key.encode())

    @staticmethod
    def new_key() -> str:
        """Generate a fresh encryption key."""
        return Fernet.generate_key().decode()

    def save(self, token_json: str) -> None:
        """Encrypt and write ``token_json``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_bytes(self._fernet.encrypt(token_json.encode()))

    def load(self) -> str | None:
        """Decrypt the stored token, or return ``None`` if there is none.

        Raises:
            GoogleAuthError: The file exists but the key cannot decrypt it.

        """
        if not self._path.is_file():
            return None
        try:
            return self._fernet.decrypt(self._path.read_bytes()).decode()
        except InvalidToken as exc:
            raise GoogleAuthError(
                f"cannot decrypt {self._path.name}: {SECRET_KEY_ENV} changed. "
                "Run 'm3allema google connect' again."
            ) from exc

    def delete(self) -> bool:
        """Remove the stored token. Returns whether one existed."""
        if self._path.is_file():
            self._path.unlink()
            return True
        return False


class GoogleAuth:
    """Connects a workspace to one Google account and hands out fresh credentials.

    Args:
        state_dir: The workspace's ``.m3allema`` folder.
        env_file: The workspace ``.env``, where the encryption key is kept.

    """

    def __init__(self, state_dir: Path, env_file: Path) -> None:
        self._state_dir = state_dir
        self._env_file = env_file
        self._client_secret = state_dir / "google_client_secret.json"
        self._token_path = state_dir / "google_token.enc"

    @property
    def is_connected(self) -> bool:
        """Whether a token has been stored."""
        return self._token_path.is_file()

    def connect(self, client_secret: Path, *, open_browser: bool = True) -> str:
        """Run Google's consent flow in the browser and store the token.

        Returns:
            A short description of what was connected.

        Raises:
            GoogleAuthError: The client-secret file is missing or invalid.

        """
        if not client_secret.is_file():
            raise GoogleAuthError(f"client secret file not found: {client_secret}")
        self._state_dir.mkdir(parents=True, exist_ok=True)
        if client_secret.resolve() != self._client_secret.resolve():
            shutil.copyfile(client_secret, self._client_secret)
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(self._client_secret), SCOPES)
        except (ValueError, KeyError) as exc:
            raise GoogleAuthError(
                f"{client_secret.name} is not a Google OAuth client file"
            ) from exc
        credentials = flow.run_local_server(port=0, open_browser=open_browser)
        self._vault(create_key=True).save(credentials.to_json())
        return f"Connected Google with access to {', '.join(_short(s) for s in SCOPES)}"

    def credentials(self) -> Credentials:
        """Return valid credentials, refreshing and re-saving them when expired.

        Raises:
            GoogleAuthError: Not connected, or the refresh failed.

        """
        vault = self._vault(create_key=False)
        token_json = vault.load()
        if token_json is None:
            raise GoogleAuthError("Google is not connected. Run 'm3allema google connect'.")
        credentials: Credentials = Credentials.from_authorized_user_info(
            json.loads(token_json), SCOPES
        )
        if not credentials.valid:
            if not credentials.refresh_token:
                raise GoogleAuthError("the Google sign-in expired. Run 'm3allema google connect'.")
            try:
                credentials.refresh(Request())
            except RefreshError as exc:
                raise GoogleAuthError(
                    "Google rejected the stored sign-in. Run 'm3allema google connect'."
                ) from exc
            vault.save(credentials.to_json())
        return credentials

    def disconnect(self) -> bool:
        """Forget the stored token. Returns whether one existed."""
        key = self._read_key()
        if key is None:
            return False
        return TokenVault(self._token_path, key).delete()

    def _vault(self, *, create_key: bool) -> TokenVault:
        key = self._read_key()
        if key is None:
            if not create_key:
                raise GoogleAuthError("Google is not connected. Run 'm3allema google connect'.")
            key = TokenVault.new_key()
            self._append_env(SECRET_KEY_ENV, key)
            os.environ[SECRET_KEY_ENV] = key
        return TokenVault(self._token_path, key)

    def _read_key(self) -> str | None:
        if value := os.environ.get(SECRET_KEY_ENV):
            return value
        if not self._env_file.is_file():
            return None
        for line in self._env_file.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == SECRET_KEY_ENV and value.strip():
                return value.strip()
        return None

    def _append_env(self, name: str, value: str) -> None:
        existing = self._env_file.read_text(encoding="utf-8") if self._env_file.is_file() else ""
        separator = "" if not existing or existing.endswith("\n") else "\n"
        comment = "# Encrypts the stored Google sign-in. Keep it secret; never commit .env.\n"
        self._env_file.write_text(f"{existing}{separator}{comment}{name}={value}\n", "utf-8")


def _short(scope: str) -> str:
    return scope.rsplit("/", 1)[-1]
