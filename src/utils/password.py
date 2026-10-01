import base64
import binascii
import hashlib
import secrets

ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS,
    )

    return "pbkdf2_sha256${}${}${}".format(
        ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, digest = encoded.split("$")

        if algorithm != "pbkdf2_sha256" or not 1 <= int(iterations) <= 2_000_000:
            return False

        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            base64.b64decode(salt, validate=True),
            int(iterations),
        )

        return secrets.compare_digest(
            calculated,
            base64.b64decode(digest, validate=True),
        )
    except (ValueError, TypeError, binascii.Error):
        return False