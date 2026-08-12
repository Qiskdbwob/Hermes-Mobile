"""Encrypted app-private storage for remote backend credentials."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class _EncryptedSecretStore:
    """Persist small credentials encrypted inside one app-private namespace.

    Android's application sandbox protects both files from other apps.  Keeping
    the Fernet key separate prevents credentials from appearing as plaintext in
    settings exports, logs, crash dumps, or routine configuration inspection.
    """

    def __init__(self, data_dir: str | Path, namespace: str) -> None:
        root = Path(data_dir).expanduser() / namespace
        root.mkdir(parents=True, exist_ok=True)
        self._key_path = root / ".credential-key"
        self._data_path = root / "credentials.bin"
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            key = self._key_path.read_bytes().strip()
            Fernet(key)
            return key
        key = Fernet.generate_key()
        fd, raw_tmp = tempfile.mkstemp(prefix="credential-key-", dir=self._key_path.parent)
        try:
            os.write(fd, key)
            os.fchmod(fd, 0o600)
            os.close(fd)
            fd = -1
            os.replace(raw_tmp, self._key_path)
            try:
                self._key_path.chmod(0o600)
            except OSError:
                pass
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                Path(raw_tmp).unlink(missing_ok=True)
            except OSError:
                pass
        return key

    def load(self) -> dict[str, str]:
        if not self._data_path.exists():
            return {}
        try:
            raw = self._fernet.decrypt(self._data_path.read_bytes())
            value = json.loads(raw.decode("utf-8"))
        except (OSError, InvalidToken, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(k): str(v) for k, v in value.items() if isinstance(v, str)}

    def save(self, **secrets: str) -> None:
        current = self.load()
        for key, value in secrets.items():
            if value:
                current[str(key)] = str(value)
            else:
                current.pop(str(key), None)
        encrypted = self._fernet.encrypt(
            json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8")
        )
        fd, raw_tmp = tempfile.mkstemp(prefix="credentials-", dir=self._data_path.parent)
        try:
            os.write(fd, encrypted)
            os.fchmod(fd, 0o600)
            os.close(fd)
            fd = -1
            os.replace(raw_tmp, self._data_path)
            try:
                self._data_path.chmod(0o600)
            except OSError:
                pass
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                Path(raw_tmp).unlink(missing_ok=True)
            except OSError:
                pass

    def clear(self) -> None:
        try:
            self._data_path.unlink(missing_ok=True)
        except OSError:
            pass


class RemoteSecretStore(_EncryptedSecretStore):
    """Encrypted password/token storage for a Hermes Remote connection."""

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir, "remote")


class GatewaySecretStore(_EncryptedSecretStore):
    """Encrypted token storage for the local messaging gateway.

    Holds the Telegram bot token entered from the in-app Messaging view so the
    gateway keeps working across restarts without a .env file on device.
    """

    _TOKEN_KEY = "telegram_bot_token"

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir, "gateway")

    def get_token(self) -> str:
        return self.load().get(self._TOKEN_KEY, "")

    def save_token(self, token: str) -> None:
        self.save(**{self._TOKEN_KEY: str(token).strip()})


class ProviderSecretStore(_EncryptedSecretStore):
    """Encrypted API-key storage keyed by canonical local provider slug."""

    def __init__(self, data_dir: str | Path) -> None:
        super().__init__(data_dir, "providers")

    def get_key(self, provider: str) -> str:
        return self.load().get(str(provider).strip().lower(), "")

    def save_key(self, provider: str, api_key: str) -> None:
        slug = str(provider).strip().lower()
        if not slug:
            raise ValueError("provider is required")
        self.save(**{slug: str(api_key).strip()})
