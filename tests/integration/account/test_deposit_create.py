from decimal import Decimal
from os import environ
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils.db_utils import DbUtils
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


def internal_headers() -> dict:
    return {"INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")}


def create_account_and_token() -> tuple[str, str]:
    email = f"deposito.{uuid4().hex}@example.com"

    created = send(
        "POST",
        "/clients",
        payload={
            "name": "Cliente de Teste",
            "email": email,
            "document_number": RandomGenerator.generate_cpf(),
            "password": PASSWORD,
        },
    )
    assert created.response_status == 201

    login = send(
        "POST",
        "/auth/login",
        payload={"email": email, "password": PASSWORD},
    )
    assert login.response_status == 200

    account_key = created.response_json["accounts"][0]["account_key"]
    token = login.response_json["access_token"]
    return account_key, token


def read_account(account_key: str, token: str):
    return send(
        "GET",
        f"/accounts/{account_key}",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_deposit_updates_balance_and_records_one_entry():
    account_key, token = create_account_and_token()
    reference = f"pagamento-{uuid4().hex}"

    response = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={"amount": "125.50", "external_reference": reference},
        headers=internal_headers(),
    )

    assert response.response_status == 201
    assert response.response_json["status"] == "COMPLETED"
    assert response.response_json["amount"] == "125.50"
    assert response.response_json["balance_after"] == "125.50"

    account = read_account(account_key, token)
    assert account.response_status == 200
    assert account.response_json["balance"] == "125.50"

    engine = create_engine(DbUtils.database_url())
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT t.amount, e.amount AS entry_amount, "
                    "e.balance_after "
                    "FROM transactions t "
                    "JOIN account_entries e ON e.transaction_id = t.id "
                    "WHERE t.external_reference = :reference"
                ),
                {"reference": reference},
            ).all()

        assert len(rows) == 1
        assert rows[0].amount == Decimal("125.50")
        assert rows[0].entry_amount == Decimal("125.50")
        assert rows[0].balance_after == Decimal("125.50")
    finally:
        engine.dispose()


def test_repeating_reference_does_not_credit_twice():
    account_key, token = create_account_and_token()
    payload = {
        "amount": "10.25",
        "external_reference": f"pagamento-{uuid4().hex}",
    }

    first = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload=payload,
        headers=internal_headers(),
    )
    repeated = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload=payload,
        headers=internal_headers(),
    )

    assert first.response_status == 201
    assert repeated.response_status == 201
    assert repeated.response_json == first.response_json
    assert read_account(account_key, token).response_json["balance"] == "10.25"


def test_reference_cannot_be_reused_with_different_data():
    first_account, _ = create_account_and_token()
    second_account, second_token = create_account_and_token()
    reference = f"pagamento-{uuid4().hex}"

    first = send(
        "POST",
        f"/accounts/{first_account}/deposits",
        payload={"amount": "20.00", "external_reference": reference},
        headers=internal_headers(),
    )
    conflict = send(
        "POST",
        f"/accounts/{second_account}/deposits",
        payload={"amount": "20.00", "external_reference": reference},
        headers=internal_headers(),
    )

    assert first.response_status == 201
    assert conflict.response_status == 409
    assert conflict.response_json["code"] == "KOD004002"
    assert read_account(second_account, second_token).response_json["balance"] == "0.00"


def test_deposit_requires_internal_token():
    account_key, token = create_account_and_token()

    response = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": "5.00",
            "external_reference": f"pagamento-{uuid4().hex}",
        },
    )

    assert response.response_status == 403
    assert read_account(account_key, token).response_json["balance"] == "0.00"


def test_deposit_rejects_invalid_amounts():
    account_key, token = create_account_and_token()

    for amount, expected_status in (
        ("0.00", 422),
        ("-1.00", 400),
        ("1.001", 400),
        (1.00, 400),
    ):
        response = send(
            "POST",
            f"/accounts/{account_key}/deposits",
            payload={
                "amount": amount,
                "external_reference": f"pagamento-{uuid4().hex}",
            },
            headers=internal_headers(),
        )
        assert response.response_status == expected_status

    assert read_account(account_key, token).response_json["balance"] == "0.00"