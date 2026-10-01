import base64
import hashlib
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from tests.utils.db_utils import DbUtils
from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition


def valid_payload() -> dict:
    """Cria dados novos para cada teste poder rodar mais de uma vez."""
    return {
        "name": "Maria Silva",
        "email": f"maria.{uuid4().hex}@example.com",
        "document_number": RandomGenerator.generate_cpf(),
        "password": "SenhaDeTeste123!",
    }


def post_client(payload: dict):
    """Envia uma requisição real para a API que está no Docker."""
    response = ClientRequisition.send(
        "POST",
        "/clients",
        payload=payload,
    )
    return response.response_status, response.response_json


def test_creates_client_and_two_accounts():
    payload = valid_payload()

    status, response = post_client(payload)

    assert status == 201
    UUID(response["client_key"])

    accounts = response["accounts"]
    assert len(accounts) == 2
    assert {account["type"] for account in accounts} == {
        "personal",
        "professional",
    }
    assert len({account["account_key"] for account in accounts}) == 2

    for account in accounts:
        UUID(account["account_key"])

    # Dados internos e sensíveis não devem aparecer na resposta.
    assert "id" not in response
    assert "password" not in response
    assert "password_hash" not in response
    assert payload["password"] not in str(response)

    # Confere o resultado persistido, além da resposta HTTP.
    engine = create_engine(DbUtils.database_url())

    try:
        with engine.connect() as connection:
            client = connection.execute(
                text(
                    "SELECT id, document_number, password_hash "
                    "FROM clients WHERE email = :email"
                ),
                {"email": payload["email"]},
            ).one()

            saved_accounts = connection.execute(
                text(
                    "SELECT type, balance "
                    "FROM accounts WHERE client_id = :client_id"
                ),
                {"client_id": client.id},
            ).all()

        assert client.document_number.strip() == (
            payload["document_number"].replace(".", "").replace("-", "")
        )
        assert client.password_hash != payload["password"]

        # Recalcula o hash para demonstrar que a senha cadastrada confere.
        algorithm, iterations, salt, digest = client.password_hash.split("$")
        assert algorithm == "pbkdf2_sha256"

        calculated = hashlib.pbkdf2_hmac(
            "sha256",
            payload["password"].encode("utf-8"),
            base64.b64decode(salt),
            int(iterations),
        )
        assert calculated == base64.b64decode(digest)

        assert len(saved_accounts) == 2
        assert {account.type for account in saved_accounts} == {
            "personal",
            "professional",
        }
        assert all(account.balance == 0 for account in saved_accounts)
    finally:
        engine.dispose()


def test_refuses_duplicate_cpf():
    original = valid_payload()
    assert post_client(original)[0] == 201

    another_client = valid_payload()
    another_client["document_number"] = original["document_number"]

    status, response = post_client(another_client)

    assert status == 409
    assert response["code"] == "KOD001002"


def test_refuses_duplicate_email_ignoring_case():
    original = valid_payload()
    assert post_client(original)[0] == 201

    another_client = valid_payload()
    another_client["email"] = original["email"].upper()

    status, response = post_client(another_client)

    assert status == 409
    assert response["code"] == "KOD001003"


def test_refuses_invalid_cpf():
    payload = valid_payload()
    payload["document_number"] = "111.111.111-11"

    status, response = post_client(payload)

    assert status == 422
    assert response["code"] == "KOD001001"


def test_refuses_invalid_body():
    payload = valid_payload()
    payload["password"] = "curta"

    status, response = post_client(payload)

    assert status == 400
    assert response["code"] == "QIT000001"