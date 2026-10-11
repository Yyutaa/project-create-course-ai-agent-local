"""One local DeepSeek setting; secrets live only in the OS credential store."""

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from app.v0.storage import FactStore

SERVICE = "ai-course-studio-deepseek"
ACCOUNT = "default"
MODELS = frozenset({"deepseek-flash", "deepseek-v4-pro"})


class ConfigError(Exception):
    """Safe error code; never include credential-store exception text."""


@dataclass(frozen=True)
class ConfigStatus:
    provider: str = "deepseek"
    model: str = "deepseek-flash"
    configured: bool = False
    error: str | None = None


class LocalConfigStore:
    def __init__(self, path: Path, keyring_backend=None):
        if keyring_backend is None:
            import keyring
            try:
                if sys.platform == "darwin":
                    from keyring.backends.macOS import Keyring as NativeKeyring
                elif sys.platform == "win32":
                    from keyring.backends.Windows import WinVaultKeyring as NativeKeyring
                else:
                    NativeKeyring = None
                keyring_backend = (
                    keyring if NativeKeyring is not None
                    and isinstance(keyring.get_keyring(), NativeKeyring) else None
                )
            except Exception:
                keyring_backend = None
        self.facts = FactStore(Path(path))
        self.facts.migrate()
        self.keyring = keyring_backend

    def _row(self):
        with self.facts.connect() as connection:
            return connection.execute(
                "SELECT model, state FROM local_llm_config WHERE id=1"
            ).fetchone()

    def _read_credentials(self) -> tuple[ConfigStatus, str | None]:
        if self.keyring is None:
            return ConfigStatus(error="keyring_unavailable"), None
        try:
            with self.facts.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT model, state FROM local_llm_config WHERE id=1"
                ).fetchone()
                if row is None:
                    return ConfigStatus(), None
                model = row["model"]
                if row["state"] != "ready":
                    return ConfigStatus(model=model, error="config_needs_repair"), None
                try:
                    key = self.keyring.get_password(SERVICE, ACCOUNT)
                except Exception:
                    return ConfigStatus(model=model, error="keyring_unavailable"), None
                return (
                    ConfigStatus(
                        model=model,
                        configured=bool(key),
                        error=None if key else "key_missing",
                    ),
                    key,
                )
        except sqlite3.Error:
            return ConfigStatus(error="metadata_unavailable"), None

    def status(self) -> ConfigStatus:
        return self._read_credentials()[0]

    def require_credentials(self) -> tuple[str, str]:
        status, key = self._read_credentials()
        if not status.configured:
            raise ConfigError(status.error or "config_missing")
        assert key is not None
        return status.model, key

    def _prepare(self, model: str) -> str:
        token = uuid4().hex
        with self.facts.connect() as connection:
            connection.execute(
                "INSERT INTO local_llm_config(id, provider, model, state, operation_token) "
                "VALUES (1, 'deepseek', ?, 'repair', ?) "
                "ON CONFLICT(id) DO UPDATE SET state='repair', "
                "operation_token=excluded.operation_token",
                (model, token),
            )
        return token

    @staticmethod
    def _check_token(connection: sqlite3.Connection, token: str) -> None:
        row = connection.execute(
            "SELECT state, operation_token FROM local_llm_config WHERE id=1"
        ).fetchone()
        if row is None or row["state"] != "repair" or row["operation_token"] != token:
            raise ConfigError("config_superseded")

    def _commit_metadata(self, connection: sqlite3.Connection, model: str | None) -> None:
        if model is None:
            connection.execute("DELETE FROM local_llm_config WHERE id=1")
        else:
            connection.execute(
                "UPDATE local_llm_config SET model=?, state='ready', "
                "operation_token=NULL WHERE id=1",
                (model,),
            )

    def save(self, model: str, api_key: str | None) -> None:
        if self.keyring is None:
            raise ConfigError("keyring_unavailable")
        if model not in MODELS or api_key == "" or (
            api_key is not None and len(api_key) > 4096
        ):
            raise ValueError("invalid_configuration")
        try:
            token = self._prepare(model)
        except sqlite3.Error:
            raise ConfigError("metadata_unavailable") from None
        try:
            with self.facts.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check_token(connection, token)
                try:
                    old_key = self.keyring.get_password(SERVICE, ACCOUNT)
                except Exception:
                    raise ConfigError("keyring_unavailable") from None
                if api_key is None and not old_key:
                    raise ConfigError("key_missing")
                if api_key is not None:
                    try:
                        self.keyring.set_password(SERVICE, ACCOUNT, api_key)
                    except Exception:
                        raise ConfigError("keyring_unavailable") from None
                try:
                    self._commit_metadata(connection, model)
                    connection.commit()
                except sqlite3.Error:
                    if api_key is not None:
                        try:
                            if old_key is None:
                                self.keyring.delete_password(SERVICE, ACCOUNT)
                            else:
                                self.keyring.set_password(SERVICE, ACCOUNT, old_key)
                        except Exception:
                            pass  # Persistent repair state still blocks use after restart.
                    raise ConfigError("config_needs_repair") from None
        except sqlite3.Error:
            raise ConfigError("metadata_unavailable") from None

    def clear(self) -> None:
        if self.keyring is None:
            raise ConfigError("keyring_unavailable")
        row = self._row()
        try:
            token = self._prepare(row["model"] if row else "deepseek-flash")
        except sqlite3.Error:
            raise ConfigError("metadata_unavailable") from None
        try:
            with self.facts.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._check_token(connection, token)
                try:
                    old_key = self.keyring.get_password(SERVICE, ACCOUNT)
                    if old_key is not None:
                        self.keyring.delete_password(SERVICE, ACCOUNT)
                except Exception:
                    raise ConfigError("keyring_unavailable") from None
                try:
                    self._commit_metadata(connection, None)
                    connection.commit()
                except sqlite3.Error:
                    raise ConfigError("config_needs_repair") from None
        except sqlite3.Error:
            raise ConfigError("metadata_unavailable") from None
