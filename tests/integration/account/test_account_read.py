from uuid import uuid4

from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition


PASSWORD = "SenhaDeTeste123!"


def send(method: str, endpoint: str, headers=None, payload=None):
    return ClientRequisition.send(
        method,
        endpoint,
        headers=headers,
        payload=payload,
    )


def create_client_and_token() -> tuple[dict, str]:
    payload = {
        "name": "Cliente de Teste",
        "email": f"contas.{uuid4().hex}@example.com",
        "document_number": RandomGenerator.generate_cpf(),
        "password": PASSWORD,
    }

    created = send("POST", "/clients", payload=payload)
    assert created.response_status == 201

    login = send(
        "POST",
        "/auth/login",
        payload={"email": payload["email"], "password": PASSWORD},
    )
    assert login.response_status == 200

    return created.response_json, login.response_json["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_lists_only_the_authenticated_clients_accounts():
    created, token = create_client_and_token()

    response = send("GET", "/accounts", headers=bearer(token))

    assert response.response_status == 200
    accounts = response.response_json["accounts"]
    assert len(accounts) == 2
    assert {item["account_key"] for item in accounts} == {
        item["account_key"] for item in created["accounts"]
    }
    assert {item["type"] for item in accounts} == {
        "personal",
        "professional",
    }
    assert all(item["balance"] == "0.00" for item in accounts)
    assert "password" not in str(response.response_json)
    assert "client_id" not in str(response.response_json)


def test_reads_each_own_account():
    created, token = create_client_and_token()

    for expected in created["accounts"]:
        response = send(
            "GET",
            f"/accounts/{expected['account_key']}",
            headers=bearer(token),
        )

        assert response.response_status == 200
        assert response.response_json == {
            "account_key": expected["account_key"],
            "type": expected["type"],
            "balance": "0.00",
        }


def test_foreign_account_looks_like_nonexistent_account():
    _, owner_token = create_client_and_token()
    other_client, other_token = create_client_and_token()
    foreign_key = other_client["accounts"][0]["account_key"]

    foreign = send(
        "GET",
        f"/accounts/{foreign_key}",
        headers=bearer(owner_token),
    )
    missing = send(
        "GET",
        f"/accounts/{uuid4()}",
        headers=bearer(owner_token),
    )
    owners_account = send(
        "GET",
        f"/accounts/{foreign_key}",
        headers=bearer(other_token),
    )

    assert foreign.response_status == 404
    assert foreign.response_json["code"] == "KOD003001"
    assert foreign.response_json == missing.response_json
    assert owners_account.response_status == 200


def test_accounts_require_a_valid_jwt():
    created, _ = create_client_and_token()
    key = created["accounts"][0]["account_key"]

    for endpoint in ("/accounts", f"/accounts/{key}"):
        no_token = send("GET", endpoint)
        bad_token = send(
            "GET",
            endpoint,
            headers=bearer("token-invalido"),
        )

        for response in (no_token, bad_token):
            assert response.response_status == 401
            assert response.response_json["code"] == "KOD002002"
            assert response.response.headers["WWW-Authenticate"] == "Bearer"


def test_rejects_malformed_account_key():
    _, token = create_client_and_token()

    response = send(
        "GET",
        "/accounts/not-a-uuid",
        headers=bearer(token),
    )

    assert response.response_status == 400
    assert response.response_json["code"] == "QIT000010"