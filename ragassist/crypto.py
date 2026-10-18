"""Encrypted credential store (SEC-01, AC-31).

AGENS.md specifies ``termux-keystore`` / ``termux-crypto``. Those are not
published Termux packages, so this module implements the same guarantee with a
real primitive: a single ``keystore.bin`` whose secrets are sealed with
AES-256-GCM. The 256-bit key is derived from a random per-install master key
file with ``scrypt``; both files live inside ``~/.rag-assist`` with mode 600,
inside the Android app sandbox.

The contract that matters for the rest of the codebase is the one in AGENS.md
section 9: ``config.yaml`` stores only a *reference* such as
``api_key: keystore://openai/api_key``, never the secret itself.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from typing import Any

from . import paths

KEY_FILE = "master.key"
KEY_BYTES = 32
SALT_BYTES = 16
NONCE_BYTES = 12
_SCRYPT_N = 2**15

KEYSTORE_PREFIX = "keystore://"  # config.yaml stores only this reference form

_MISSING_BACKEND = (
    "the 'cryptography' package is not installed, so credentials cannot be "
    "encrypted. rag-assist refuses to store API keys in plaintext (SEC-01). "
    "Install it with: pkg install python-cryptography"
)


class CredentialStoreError(RuntimeError):
    """Raised when the keystore cannot be read or written."""


class CryptoUnavailableError(CredentialStoreError):
    """The AEAD backend is not installed.

    Raised instead of falling back to plaintext: SEC-01 forbids storing a
    credential unencrypted, so a missing backend must stop the write rather
    than quietly weaken the guarantee.
    """


def _aesgcm():
    """Import AESGCM on demand.

    ``cryptography`` pulls in a Rust extension worth ~1.8s of import time on the
    ARM64 devices this tool targets, which would otherwise be paid on every
    invocation even when no credential is touched.
    """
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise CryptoUnavailableError(_MISSING_BACKEND) from exc
    return AESGCM


def _scrypt():
    try:
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    except ImportError as exc:
        raise CryptoUnavailableError(_MISSING_BACKEND) from exc
    return Scrypt


def _invalid_tag():
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError as exc:
        raise CryptoUnavailableError(_MISSING_BACKEND) from exc
    return InvalidTag


def is_reference(value: Any) -> bool:
    """True when a config value is a keystore reference, not a plaintext key."""
    return isinstance(value, str) and value.startswith(KEYSTORE_PREFIX)


def make_reference(alias: str) -> str:
    return f"{KEYSTORE_PREFIX}{alias}"


def _key_path():
    return paths.base_dir() / KEY_FILE


def _load_or_create_key() -> bytes:
    """Return the master key, generating it on first use."""
    path = _key_path()
    if path.exists():
        raw = path.read_bytes().strip()
        try:
            return base64.urlsafe_b64decode(raw)
        except (ValueError, TypeError) as exc:
            raise CredentialStoreError(f"master key file is corrupt: {path}") from exc

    raw = secrets.token_bytes(KEY_BYTES)
    # 0600 before the secret ever hits the filesystem.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(base64.urlsafe_b64encode(raw))
    paths.restrict(path)
    return raw


def _derive(master: bytes, salt: bytes) -> bytes:
    kdf = _scrypt()(salt=salt, length=KEY_BYTES, n=_SCRYPT_N, r=8, p=1)
    return kdf.derive(master)


def _load_container() -> dict[str, Any]:
    path = paths.keystore_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        raise CredentialStoreError(f"keystore file is unreadable: {path}") from exc


def _save_container(container: dict[str, Any]) -> None:
    paths.ensure_dirs()
    path = paths.keystore_path()
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(container, handle, indent=2, sort_keys=True)
    os.replace(tmp, path)
    paths.restrict(path)


def set_secret(alias: str, value: str) -> None:
    """Seal ``value`` under ``alias``, replacing any previous value."""
    master = _load_or_create_key()
    salt = secrets.token_bytes(SALT_BYTES)
    nonce = secrets.token_bytes(NONCE_BYTES)
    ciphertext = _aesgcm()(_derive(master, salt)).encrypt(
        nonce, value.encode("utf-8"), alias.encode("utf-8")
    )

    container = _load_container()
    container[alias] = {
        "v": 1,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ciphertext).decode(),
    }
    _save_container(container)


def get_secret(alias: str) -> str | None:
    """Return the plaintext for ``alias``, or ``None`` when unset."""
    entry = _load_container().get(alias)
    if not entry:
        return None
    try:
        master = _load_or_create_key()
        key = _derive(master, base64.b64decode(entry["salt"]))
        plaintext = _aesgcm()(key).decrypt(
            base64.b64decode(entry["nonce"]),
            base64.b64decode(entry["ct"]),
            alias.encode("utf-8"),
        )
    except _invalid_tag() as exc:
        raise CredentialStoreError(
            f"credential '{alias}' failed authentication; the keystore or master "
            "key may have been modified"
        ) from exc
    return plaintext.decode("utf-8")


def delete_secret(alias: str) -> bool:
    container = _load_container()
    if alias in container:
        del container[alias]
        _save_container(container)
        return True
    return False


def list_aliases() -> list[str]:
    return sorted(_load_container())


def store(config_value: Any, alias: str, new_value: str | None) -> str:
    """Write ``new_value`` to the keystore and return the config reference.

    Passing ``new_value=None`` deletes the credential and returns an empty
    string, keeping the "config holds references only" invariant in one place.
    """
    if new_value is None:
        delete_secret(alias)
        return ""
    set_secret(alias, new_value)
    return make_reference(alias)