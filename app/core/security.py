import hashlib
import secrets


def hash_password(raw_password: str) -> str:
    """Return salted SHA256 hash for a raw password."""

    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}{raw_password}".encode("utf-8")).hexdigest()
    return f"{salt}${digest}"


def verify_password(raw_password: str, stored_hash: str) -> bool:
    try:
        salt, checksum = stored_hash.split("$", 1)
    except ValueError:
        return False
    digest = hashlib.sha256(f"{salt}{raw_password}".encode("utf-8")).hexdigest()
    return secrets.compare_digest(digest, checksum)
