import hashlib
import secrets
from typing import Tuple

from passlib.context import CryptContext

PWD_CONTEXT = CryptContext(schemes=["argon2"], deprecated="auto")


def _legacy_hash(raw_password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{raw_password}".encode("utf-8")).hexdigest()


def hash_password(raw_password: str) -> str:
    """Return Argon2 hash for a raw password."""
    return PWD_CONTEXT.hash(raw_password)


def verify_and_update_password(raw_password: str, stored_hash: str) -> Tuple[bool, str | None]:
    """Verify a password and return optional upgraded hash.

    Supports legacy salted SHA256 hashes in format ``salt$checksum``.
    """
    if not stored_hash:
        return False, None

    # Legacy format support for in-place migration.
    if stored_hash.count("$") == 1 and not stored_hash.startswith("$argon2"):
        try:
            salt, checksum = stored_hash.split("$", 1)
        except ValueError:
            return False, None
        digest = _legacy_hash(raw_password, salt)
        verified = secrets.compare_digest(digest, checksum)
        if not verified:
            return False, None
        return True, hash_password(raw_password)

    try:
        verified, replacement_hash = PWD_CONTEXT.verify_and_update(raw_password, stored_hash)
    except Exception:
        return False, None
    return bool(verified), replacement_hash


def verify_password(raw_password: str, stored_hash: str) -> bool:
    verified, _ = verify_and_update_password(raw_password, stored_hash)
    return verified
