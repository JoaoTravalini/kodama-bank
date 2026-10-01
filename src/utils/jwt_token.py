from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt

from constants import JWT_SECRET

ALGORITHM = "HS256"
ISSUER = "kodama-bank"
AUDIENCE = "kodama-bank-api"
ACCESS_TOKEN_SECONDS = 15 * 60


def create_access_token(client_key: str) -> str:
    now = datetime.now(timezone.utc)

    claims = {
        "sub": client_key,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=ACCESS_TOKEN_SECONDS),
        "jti": str(uuid4()),
    }

    return jwt.encode(claims, JWT_SECRET, algorithm=ALGORITHM)


def read_access_token(token: str) -> UUID:
    claims = jwt.decode(
        token,
        JWT_SECRET,
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["sub", "iss", "aud", "iat", "exp", "jti"]},
    )

    # Além de validar a assinatura e o prazo, exigimos que o sujeito
    # seja uma chave pública de cliente válida.
    return UUID(claims["sub"])