from os import environ
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils.db_utils import DbUtils
from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None):
    return ClientRequisition.send(
        method,
        endpoint,
        payload=payload,
        headers=headers,
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def create_client():
    email = f"transferencia.{uuid4().hex}@example.com"

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

    return created.response_json, login.response_json["access_token"]


def deposit(account_key, amount):
    response = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": amount,
            "external_reference": f"entrada-{uuid4().hex}",
        },
        headers={
            "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
        },
    )
    assert response.response_status == 201


def request_transfer(
    source_key, destination_key, token, amount="100.00", idempotency_key=None
):
    return send(
        "POST",
        f"/accounts/{source_key}/transfers",
        payload={
            "amount": amount,
            "destination_account_key": destination_key,
            "idempotency_key": idempotency_key or str(uuid4()),
        },
        headers=bearer(token),
    )


def read_balance(account_key, token):
    response = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    assert response.response_status == 200
    return response.response_json["balance"]


def test_cross_client_request_is_pending_without_moving_money():
    sender, sender_token = create_client()
    recipient, recipient_token = create_client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]

    deposit(source_key, "101.00")

    response = request_transfer(
        source_key, destination_key, sender_token, amount="100.00"
    )

    assert response.response_status == 202
    transfer = response.response_json
    assert transfer["status"] == "PENDING"
    assert transfer["amount"] == "100.00"
    assert transfer["fee"] == "0.50"
    assert transfer["source_account_key"] == source_key
    assert transfer["destination_account_key"] == destination_key

    detail = send(
        "GET",
        f"/accounts/{source_key}/transfers/{transfer['transaction_key']}",
        headers=bearer(sender_token),
    )
    assert detail.response_status == 200
    assert detail.response_json == transfer

    assert read_balance(source_key, sender_token) == "101.00"
    assert read_balance(destination_key, recipient_token) == "0.00"

    engine = create_engine(DbUtils.database_url())
    try:
        with engine.connect() as connection:
            entry_count = connection.execute(
                text(
                    "SELECT COUNT(*) FROM account_entries e "
                    "JOIN transactions t ON t.id = e.transaction_id "
                    "WHERE t.transaction_key = CAST(:key AS UUID)"
                ),
                {"key": transfer["transaction_key"]},
            ).scalar_one()
        assert entry_count == 0
    finally:
        engine.dispose()


def test_same_client_transfer_is_free():
    client, token = create_client()
    source_key = client["accounts"][0]["account_key"]
    destination_key = client["accounts"][1]["account_key"]

    response = request_transfer(
        source_key, destination_key, token, amount="100.00"
    )

    assert response.response_status == 202
    assert response.response_json["fee"] == "0.00"
    assert read_balance(source_key, token) == "0.00"
    assert read_balance(destination_key, token) == "0.00"


def test_cross_client_fee_has_two_real_cap():
    sender, token = create_client()
    recipient, _ = create_client()

    response = request_transfer(
        sender["accounts"][0]["account_key"],
        recipient["accounts"][0]["account_key"],
        token,
        amount="500.00",
    )

    assert response.response_status == 202
    assert response.response_json["fee"] == "2.00"


def test_repeating_request_returns_same_transfer_and_changed_data_conflicts():
    sender, token = create_client()
    first_recipient, _ = create_client()
    second_recipient, _ = create_client()

    source_key = sender["accounts"][0]["account_key"]
    destination_key = first_recipient["accounts"][0]["account_key"]
    other_destination_key = second_recipient["accounts"][0]["account_key"]
    key = str(uuid4())

    first = request_transfer(
        source_key, destination_key, token, "20.00", key
    )
    repeated = request_transfer(
        source_key, destination_key, token, "20.00", key
    )
    changed_amount = request_transfer(
        source_key, destination_key, token, "21.00", key
    )
    changed_destination = request_transfer(
        source_key, other_destination_key, token, "20.00", key
    )

    assert first.response_status == 202
    assert repeated.response_status == 202
    assert repeated.response_json == first.response_json

    for response in (changed_amount, changed_destination):
        assert response.response_status == 409
        assert response.response_json["code"] == "KOD005003"


def test_transfer_requires_own_account_and_valid_jwt():
    sender, sender_token = create_client()
    recipient, recipient_token = create_client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]
    endpoint = f"/accounts/{source_key}/transfers"
    payload = {
        "amount": "10.00",
        "destination_account_key": destination_key,
        "idempotency_key": str(uuid4()),
    }

    no_token = send("POST", endpoint, payload=payload)
    bad_token = send(
        "POST", endpoint, payload=payload, headers=bearer("invalido")
    )
    foreign_source = request_transfer(
        source_key, destination_key, recipient_token, "10.00"
    )

    assert no_token.response_status == 401
    assert bad_token.response_status == 401
    assert foreign_source.response_status == 404

    own_request = request_transfer(
        source_key, destination_key, sender_token, "10.00"
    )
    assert own_request.response_status == 202

    foreign_detail = send(
        "GET",
        (
            f"/accounts/{source_key}/transfers/"
            f"{own_request.response_json['transaction_key']}"
        ),
        headers=bearer(recipient_token),
    )
    assert foreign_detail.response_status == 404


def test_rejects_same_account_missing_destination_and_invalid_amount():
    client, token = create_client()
    source_key = client["accounts"][0]["account_key"]
    destination_key = client["accounts"][1]["account_key"]

    same_account = request_transfer(
        source_key, source_key, token, "10.00"
    )
    missing_destination = request_transfer(
        source_key, str(uuid4()), token, "10.00"
    )
    zero = request_transfer(
        source_key, destination_key, token, "0.00"
    )
    malformed = request_transfer(
        source_key, destination_key, token, "-1.00"
    )

    assert same_account.response_status == 422
    assert same_account.response_json["code"] == "KOD005002"
    assert missing_destination.response_status == 404
    assert zero.response_status == 422
    assert zero.response_json["code"] == "KOD005001"
    assert malformed.response_status == 400