from os import environ
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.utils.db_utils import DbUtils
from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition
from workers.transfer_processor import TransferProcessor


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None, query_params=None):
    return ClientRequisition.send(
        method,
        endpoint,
        payload=payload,
        headers=headers,
        query_params=query_params,
    )


def create_client():
    email = f"extrato.{uuid4().hex}@example.com"
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


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def deposit(account_key, amount):
    response = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": amount,
            "external_reference": f"extrato-{uuid4().hex}",
        },
        headers={
            "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
        },
    )
    assert response.response_status == 201


def statement(account_key, token, **query_params):
    return send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
        query_params=query_params,
    )


def test_pagination_and_filters():
    client, token = create_client()
    account_key = client["accounts"][0]["account_key"]

    for amount in ("10.00", "20.00", "30.00"):
        deposit(account_key, amount)

    first = statement(account_key, token, page="1", limit="2")
    assert first.response_status == 200
    assert first.response_json["account_key"] == account_key
    assert first.response_json["page"] == 1
    assert first.response_json["limit"] == 2
    assert first.response_json["has_more"] is True
    assert [
        entry["amount"] for entry in first.response_json["entries"]
    ] == ["30.00", "20.00"]
    assert [
        entry["balance_after"] for entry in first.response_json["entries"]
    ] == ["60.00", "30.00"]
    assert all(
        entry["transaction_kind"] == "DEPOSIT"
        for entry in first.response_json["entries"]
    )

    second = statement(account_key, token, page="2", limit="2")
    assert second.response_status == 200
    assert second.response_json["has_more"] is False
    assert [
        entry["amount"] for entry in second.response_json["entries"]
    ] == ["10.00"]

    empty = statement(account_key, token, page="3", limit="2")
    assert empty.response_status == 200
    assert empty.response_json["entries"] == []
    assert empty.response_json["has_more"] is False

    fees = statement(account_key, token, kind="FEE")
    assert fees.response_status == 200
    assert fees.response_json["entries"] == []

    for params in (
        {"page": "0"},
        {"limit": "0"},
        {"limit": "101"},
        {"kind": "UNKNOWN"},
        {"unexpected": "value"},
    ):
        invalid = statement(account_key, token, **params)
        assert invalid.response_status == 400


def test_jwt_and_account_ownership():
    owner, owner_token = create_client()
    _, other_token = create_client()
    account_key = owner["accounts"][0]["account_key"]

    without_jwt = send("GET", f"/accounts/{account_key}/entries")
    assert without_jwt.response_status == 401

    foreign = statement(account_key, other_token)
    nonexistent = statement(str(uuid4()), other_token)
    assert foreign.response_status == 404
    assert foreign.response_json == nonexistent.response_json

    own = statement(account_key, owner_token)
    assert own.response_status == 200
    assert own.response_json["entries"] == []


def test_completed_transfer_shows_debit_fee_and_credit():
    sender, sender_token = create_client()
    recipient, recipient_token = create_client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]

    deposit(source_key, "100.00")
    requested = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        payload={
            "amount": "40.00",
            "destination_account_key": destination_key,
            "idempotency_key": str(uuid4()),
        },
        headers=bearer(sender_token),
    )
    assert requested.response_status == 202
    transaction_key = requested.response_json["transaction_key"]

    pending = statement(source_key, sender_token)
    assert pending.response_status == 200
    assert len(pending.response_json["entries"]) == 1

    engine = create_engine(DbUtils.database_url())
    try:
        with Session(engine, autoflush=False) as session:
            assert (
                TransferProcessor(session).process(UUID(transaction_key))
                == "COMPLETED"
            )
    finally:
        engine.dispose()

    source = statement(source_key, sender_token)
    assert source.response_status == 200
    assert [
        (entry["kind"], entry["amount"], entry["balance_after"])
        for entry in source.response_json["entries"]
    ] == [
        ("FEE", "-0.20", "59.80"),
        ("DEBIT", "-40.00", "60.00"),
        ("CREDIT", "100.00", "100.00"),
    ]
    assert all(
        entry["transaction_key"] == transaction_key
        for entry in source.response_json["entries"][:2]
    )

    only_fees = statement(source_key, sender_token, kind="FEE")
    assert only_fees.response_status == 200
    assert len(only_fees.response_json["entries"]) == 1
    assert only_fees.response_json["entries"][0]["amount"] == "-0.20"

    destination = statement(destination_key, recipient_token)
    assert destination.response_status == 200
    assert [
        (entry["kind"], entry["amount"], entry["balance_after"])
        for entry in destination.response_json["entries"]
    ] == [("CREDIT", "40.00", "40.00")]