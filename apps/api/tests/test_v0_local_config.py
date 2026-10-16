import sqlite3
import threading

import pytest

from app.v0.local_config import ACCOUNT, SERVICE, ConfigError, LocalConfigStore
from app.v0.storage import FactStore


class FakeKeyring:
    def __init__(self):
        self.password = None
        self.fail = None
        self.after_write_failure = False

    def get_password(self, service, account):
        assert (service, account) == (SERVICE, ACCOUNT)
        if self.fail == "read":
            raise RuntimeError("secret should never leak")
        return self.password

    def set_password(self, service, account, password):
        assert (service, account) == (SERVICE, ACCOUNT)
        if self.fail == "write" and not self.after_write_failure:
            raise RuntimeError("secret should never leak")
        self.password = password
        if self.fail == "write" and self.after_write_failure:
            raise RuntimeError("secret should never leak")

    def delete_password(self, service, account):
        assert (service, account) == (SERVICE, ACCOUNT)
        if self.fail == "delete":
            raise RuntimeError("secret should never leak")
        self.password = None


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "facts.sqlite3"
    keyring = FakeKeyring()
    store = LocalConfigStore(path, keyring_backend=keyring)
    return store, keyring, path


def test_save_update_replace_clear_and_restart(config):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")
    assert store.status().configured is True
    assert store.require_credentials() == ("deepseek-flash", "secret-one")
    store.save(model="deepseek-v4-pro", api_key=None)
    assert keyring.password == "secret-one"
    store.save(model="deepseek-v4-pro", api_key="secret-two")
    assert LocalConfigStore(path, keyring_backend=keyring).require_credentials() == (
        "deepseek-v4-pro", "secret-two"
    )
    assert "secret-one" not in path.read_bytes().decode(errors="ignore")
    assert "secret-two" not in path.read_bytes().decode(errors="ignore")
    store.clear()
    assert store.status().configured is False
    assert keyring.password is None


def test_migration_repeatable_and_single_row(config):
    store, _, path = config
    FactStore(path).migrate()
    FactStore(path).migrate()
    assert FactStore(path).schema_version() == 11
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO local_llm_config(id, provider, model, state) "
                "VALUES (2, 'deepseek', 'deepseek-flash', 'ready')"
            )


def test_invalid_input_never_changes_secret(config):
    store, keyring, _ = config
    with pytest.raises(ValueError):
        store.save(model="other", api_key="secret-one")
    assert keyring.password is None


def test_non_native_default_keyring_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr("keyring.get_keyring", lambda: object())
    store = LocalConfigStore(tmp_path / "facts.sqlite3")
    assert store.status().error == "keyring_unavailable"
    with pytest.raises(ConfigError, match="keyring_unavailable"):
        store.save("deepseek-flash", "secret-one")


@pytest.mark.parametrize("failure", ["read", "write"])
def test_keyring_save_failure_stays_unconfigured(config, failure):
    store, keyring, path = config
    keyring.fail = failure
    with pytest.raises(ConfigError) as error:
        store.save(model="deepseek-flash", api_key="secret-one")
    assert "secret-one" not in str(error.value)
    keyring.fail = None
    assert LocalConfigStore(path, keyring_backend=keyring).status().configured is False


def test_keyring_partial_write_failure_stays_invalid_after_restart(config):
    store, keyring, path = config
    keyring.fail = "write"
    keyring.after_write_failure = True
    with pytest.raises(ConfigError):
        store.save(model="deepseek-flash", api_key="secret-one")
    keyring.fail = None
    assert keyring.password == "secret-one"
    assert LocalConfigStore(path, keyring_backend=keyring).status().configured is False


def test_keyring_read_failure_returns_safe_status(config):
    store, keyring, _ = config
    store.save(model="deepseek-flash", api_key="secret-one")
    keyring.fail = "read"
    status = store.status()
    assert status.configured is False
    assert status.error == "keyring_unavailable"
    with pytest.raises(ConfigError, match="keyring_unavailable"):
        store.require_credentials()


def test_clear_failure_remains_invalid(config):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")
    keyring.fail = "delete"
    with pytest.raises(ConfigError):
        store.clear()
    keyring.fail = None
    assert LocalConfigStore(path, keyring_backend=keyring).status().configured is False


def test_metadata_prepare_failure_never_touches_keyring(config, monkeypatch):
    store, keyring, _ = config
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(store, "_prepare", fail)
    with pytest.raises(ConfigError):
        store.save(model="deepseek-flash", api_key="secret-one")
    assert keyring.password is None


def test_metadata_commit_failure_restores_key_and_invalidates(config, monkeypatch):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(store, "_commit_metadata", fail)
    with pytest.raises(ConfigError):
        store.save(model="deepseek-v4-pro", api_key="secret-two")
    assert keyring.password == "secret-one"
    assert LocalConfigStore(path, keyring_backend=keyring).status().configured is False


def test_restore_failure_still_invalid_after_restart(config, monkeypatch):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")

    def fail_commit(*args, **kwargs):
        keyring.fail = "write"
        keyring.after_write_failure = True
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "_commit_metadata", fail_commit)
    with pytest.raises(ConfigError, match="config_needs_repair"):
        store.save(model="deepseek-v4-pro", api_key="secret-two")
    keyring.fail = None
    assert LocalConfigStore(path, keyring_backend=keyring).status().error == (
        "config_needs_repair"
    )


def test_clear_metadata_failure_still_invalid_after_restart(config, monkeypatch):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(store, "_commit_metadata", fail)
    with pytest.raises(ConfigError, match="config_needs_repair"):
        store.clear()
    assert keyring.password is None
    assert LocalConfigStore(path, keyring_backend=keyring).status().error == (
        "config_needs_repair"
    )


def test_concurrent_saves_keep_model_and_key_together(tmp_path):
    path = tmp_path / "facts.sqlite3"
    keyring = FakeKeyring()
    first = LocalConfigStore(path, keyring_backend=keyring)
    second = LocalConfigStore(path, keyring_backend=keyring)
    done = threading.Event()
    errors = []

    def save_second():
        try:
            second.save(model="deepseek-v4-pro", api_key="secret-two")
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    original_set = keyring.set_password
    worker = None

    def interleave(service, account, password):
        nonlocal worker
        original_set(service, account, password)
        if password == "secret-one":
            worker = threading.Thread(target=save_second)
            worker.start()
            done.wait(timeout=0.2)

    keyring.set_password = interleave
    first.save(model="deepseek-flash", api_key="secret-one")
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert errors == []
    assert LocalConfigStore(path, keyring_backend=keyring).require_credentials() == (
        "deepseek-v4-pro", "secret-two"
    )


def test_clear_absent_key_does_not_delete(config):
    store, keyring, path = config

    def missing(service, account):
        raise RuntimeError("PasswordDeleteError")

    keyring.delete_password = missing
    store.clear()
    store.clear()
    assert LocalConfigStore(path, keyring_backend=keyring).status().configured is False


def test_credential_read_does_not_mix_concurrent_model_and_key(config):
    store, keyring, path = config
    store.save(model="deepseek-flash", api_key="secret-one")
    second = LocalConfigStore(path, keyring_backend=keyring)
    done = threading.Event()
    original_get = keyring.get_password
    worker = None

    def get_with_interleave(service, account):
        nonlocal worker
        key = original_get(service, account)
        if worker is None and threading.current_thread() is threading.main_thread():
            worker = threading.Thread(
                target=lambda: (
                    second.save(model="deepseek-v4-pro", api_key="secret-two"),
                    done.set(),
                )
            )
            worker.start()
            done.wait(timeout=0.2)
        return key

    keyring.get_password = get_with_interleave
    model, key = store.require_credentials()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert (model, key) in {
        ("deepseek-flash", "secret-one"),
        ("deepseek-v4-pro", "secret-two"),
    }


def test_stale_prepare_cannot_leave_partial_key_as_ready(config, monkeypatch):
    first, keyring, path = config
    second = LocalConfigStore(path, keyring_backend=keyring)
    second_prepared = threading.Event()
    first_done = threading.Event()
    errors = []
    second_prepare = second._prepare
    original_set = keyring.set_password

    def prepare_second(model):
        result = second_prepare(model)
        second_prepared.set()
        assert first_done.wait(timeout=3)
        return result

    def partial_set(service, account, password):
        original_set(service, account, password)
        if password == "secret-two":
            raise RuntimeError("secret should never leak")

    def save_second():
        try:
            second.save(model="deepseek-v4-pro", api_key="secret-two")
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(second, "_prepare", prepare_second)
    monkeypatch.setattr(keyring, "set_password", partial_set)
    worker = threading.Thread(target=save_second)
    worker.start()
    assert second_prepared.wait(timeout=3)
    first.save(model="deepseek-flash", api_key="secret-one")
    first_done.set()
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ConfigError)
    assert str(errors[0]) == "config_superseded"
    assert keyring.password == "secret-one"
    assert LocalConfigStore(path, keyring_backend=keyring).require_credentials() == (
        "deepseek-flash", "secret-one"
    )


def test_v6_metadata_migrates_to_v8_without_losing_ready(config):
    store, keyring, path = config
    store.save(model="deepseek-v4-pro", api_key="secret-one")
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE local_llm_config DROP COLUMN operation_token")
        connection.execute("PRAGMA user_version=6")
    facts = FactStore(path)
    facts.migrate()
    facts.migrate()
    assert facts.schema_version() == 11
    assert LocalConfigStore(path, keyring_backend=keyring).require_credentials() == (
        "deepseek-v4-pro", "secret-one"
    )


def test_two_prepares_then_partial_key_write_remains_repair(config, monkeypatch):
    first, keyring, path = config
    second = LocalConfigStore(path, keyring_backend=keyring)
    first_prepared = threading.Event()
    second_prepared = threading.Event()
    first_done = threading.Event()
    errors = []
    first_prepare = first._prepare
    second_prepare = second._prepare
    original_set = keyring.set_password

    def prepare_first(model):
        token = first_prepare(model)
        first_prepared.set()
        assert second_prepared.wait(timeout=3)
        return token

    def prepare_second(model):
        token = second_prepare(model)
        second_prepared.set()
        assert first_done.wait(timeout=3)
        return token

    def partial_set(service, account, password):
        original_set(service, account, password)
        if password == "secret-two":
            raise RuntimeError("secret should never leak")

    def save_first():
        try:
            first.save(model="deepseek-flash", api_key="secret-one")
        except Exception as exc:
            errors.append(exc)
        finally:
            first_done.set()

    monkeypatch.setattr(first, "_prepare", prepare_first)
    monkeypatch.setattr(second, "_prepare", prepare_second)
    monkeypatch.setattr(keyring, "set_password", partial_set)
    worker = threading.Thread(target=save_first)
    worker.start()
    assert first_prepared.wait(timeout=3)
    with pytest.raises(ConfigError, match="keyring_unavailable"):
        second.save(model="deepseek-v4-pro", api_key="secret-two")
    worker.join(timeout=3)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], ConfigError)
    assert str(errors[0]) == "config_superseded"
    assert keyring.password == "secret-two"
    assert LocalConfigStore(path, keyring_backend=keyring).status().error == (
        "config_needs_repair"
    )
