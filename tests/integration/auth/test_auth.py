from datetime import datetime, timedelta, timezone
from os import environ
from uuid import uuid4

import jwt

from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition


PASSWORD = "SenhaDeTeste123!"


def send(method: str, endpoint: str, payload=None, headers=None):
    return ClientRequisition.send(
        method,
        endpoint,
        payload=payload,
        headers=headers,
    )


def create_client() -> dict:
    payload = {
        "name": "Cliente de Teste",
        "email": f"cliente.{uuid4().hex}@example.com",
        "document_number": RandomGenerator.generate_cpf(),
        "password": PASSWORD,
    }

    response = send("POST", "/clients", payload=payload)
    assert response.response_status == 201
    return {**payload, "client_key": response.response_json["client_key"]}


def login(email: str, password: str):
    return send(
        "POST",
        "/auth/login",
        payload={"email": email, "password": password},
    )


def test_login_and_access_own_profile():
    client = create_client()

    response = login(client["email"].upper(), PASSWORD)
    assert response.response_status == 200
    assert response.response_json["token_type"] == "bearer"
    assert response.response_json["expires_in"] == 900

    token = response.response_json["access_token"]
    assert isinstance(token, str) and token

    profile = send(
        "GET",
        "/clients/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile.response_status == 200
    assert profile.response_json["client_key"] == client["client_key"]
    assert profile.response_json["email"] == client["email"]
    assert {account["type"] for account in profile.response_json["accounts"]} == {
        "personal",
        "professional",
    }
    assert "password" not in str(profile.response_json)


def test_wrong_password_and_unknown_email_have_same_error():
    client = create_client()

    wrong_password = login(client["email"], "senha-errada")
    unknown_email = login(f"naoexiste.{uuid4().hex}@example.com", PASSWORD)

    for response in (wrong_password, unknown_email):
        assert response.response_status == 401
        assert response.response_json["code"] == "KOD002001"
        assert response.response.headers["WWW-Authenticate"] == "Bearer"

    assert wrong_password.response_json == unknown_email.response_json


def test_profile_requires_bearer_token():
    response = send("GET", "/clients/me")

    assert response.response_status == 401
    assert response.response_json["code"] == "KOD002002"
    assert response.response.headers["WWW-Authenticate"] == "Bearer"


def test_profile_rejects_changed_signature():
    client = create_client()
    token = login(client["email"], PASSWORD).response_json["access_token"]

    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    tampered_token = f"{header}.{payload}.{replacement}{signature[1:]}"

    response = send(
        "GET",
        "/clients/me",
        headers={"Authorization": f"Bearer {tampered_token}"},
    )

    assert response.response_status == 401
    assert response.response_json["code"] == "KOD002002"


def test_profile_rejects_expired_token():
    client = create_client()
    now = datetime.now(timezone.utc)

    expired_token = jwt.encode(
        {
            "sub": client["client_key"],
            "iss": "kodama-bank",
            "aud": "kodama-bank-api",
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(seconds=1),
            "jti": str(uuid4()),
        },
        environ["JWT_SECRET"],
        algorithm="HS256",
    )

    response = send(
        "GET",
        "/clients/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.response_status == 401
    assert response.response_json["code"] == "KOD002002"