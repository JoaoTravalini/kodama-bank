from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from os import environ
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.utils.db_utils import DbUtils
from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition
from workers.transfer_processor import TransferProcessor


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None):
    return ClientRequisition.send(
        method, endpoint, payload=payload, headers=headers
    )


def client():
    email = f"processamento.{uuid4().hex}@example.com"
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


def request_transfer(source_key, destination_key, token, amount):
    response = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        payload={
            "amount": amount,
            "destination_account_key": destination_key,
            "idempotency_key": str(uuid4()),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.response_status == 202
    return response.response_json["transaction_key"]


def balance(account_key, token):
    response = send(
        "GET",
        f"/accounts/{account_key}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.response_status == 200
    return response.response_json["balance"]


def detail(source_key, transaction_key, token):
    response = send(
        "GET",
        f"/accounts/{source_key}/transfers/{transaction_key}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.response_status == 200
    return response.response_json


def process(transaction_key):
    engine = create_engine(DbUtils.database_url())
    try:
        with Session(engine, autoflush=False) as session:
            return TransferProcessor(session).process(UUID(transaction_key))
    finally:
        engine.dispose()


def entries(transaction_key):
    engine = create_engine(DbUtils.database_url())
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT e.kind, e.amount, e.balance_after "
                    "FROM account_entries e "
                    "JOIN transactions t ON t.id = e.transaction_id "
                    "WHERE t.transaction_key = CAST(:key AS UUID)"
                ),
                {"key": transaction_key},
            ).all()
    finally:
        engine.dispose()


def test_cross_client_transfer_completes_once_with_fee():
    sender, sender_token = client()
    recipient, recipient_token = client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]
    deposit(source_key, "150.00")
    key = request_transfer(
        source_key, destination_key, sender_token, "100.00"
    )

    assert process(key) == "COMPLETED"
    assert process(key) == "COMPLETED"
    assert balance(source_key, sender_token) == "49.50"
    assert balance(destination_key, recipient_token) == "100.00"
    assert detail(source_key, key, sender_token)["status"] == "COMPLETED"

    rows = {row.kind: row for row in entries(key)}
    assert len(rows) == 3
    assert rows["DEBIT"].amount == Decimal("-100.00")
    assert rows["DEBIT"].balance_after == Decimal("50.00")
    assert rows["FEE"].amount == Decimal("-0.50")
    assert rows["FEE"].balance_after == Decimal("49.50")
    assert rows["CREDIT"].amount == Decimal("100.00")
    assert rows["CREDIT"].balance_after == Decimal("100.00")


def test_same_client_transfer_has_no_fee_entry():
    owner, token = client()
    source_key = owner["accounts"][0]["account_key"]
    destination_key = owner["accounts"][1]["account_key"]
    deposit(source_key, "25.00")
    key = request_transfer(
        source_key, destination_key, token, "10.00"
    )

    assert process(key) == "COMPLETED"
    assert balance(source_key, token) == "15.00"
    assert balance(destination_key, token) == "10.00"
    assert {row.kind for row in entries(key)} == {"DEBIT", "CREDIT"}


def test_insufficient_funds_rejects_without_entries():
    sender, token = client()
    recipient, recipient_token = client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]
    key = request_transfer(
        source_key, destination_key, token, "100.00"
    )

    assert process(key) == "REJECTED"
    assert process(key) == "REJECTED"
    result = detail(source_key, key, token)
    assert result["status"] == "REJECTED"
    assert result["rejection_reason"] == "INSUFFICIENT_FUNDS"
    assert balance(source_key, token) == "0.00"
    assert balance(destination_key, recipient_token) == "0.00"
    assert entries(key) == []


def test_destination_limit_rejects_without_entries():
    sender, token = client()
    recipient, recipient_token = client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]
    deposit(source_key, "10.05")
    deposit(destination_key, "9999999999999999.99")
    key = request_transfer(
        source_key, destination_key, token, "10.00"
    )

    assert process(key) == "REJECTED"
    result = detail(source_key, key, token)
    assert result["rejection_reason"] == "DESTINATION_LIMIT_EXCEEDED"
    assert balance(source_key, token) == "10.05"
    assert balance(destination_key, recipient_token) == "9999999999999999.99"
    assert entries(key) == []


def test_concurrent_transfers_cannot_spend_the_same_balance_twice():
    sender, token = client()
    recipient_a, token_a = client()
    recipient_b, token_b = client()
    source_key = sender["accounts"][0]["account_key"]
    destination_a = recipient_a["accounts"][0]["account_key"]
    destination_b = recipient_b["accounts"][0]["account_key"]
    deposit(source_key, "100.00")
    key_a = request_transfer(
        source_key, destination_a, token, "80.00"
    )
    key_b = request_transfer(
        source_key, destination_b, token, "80.00"
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(process, (key_a, key_b)))

    assert sorted(statuses) == ["COMPLETED", "REJECTED"]
    assert balance(source_key, token) == "19.60"
    destination_balances = [
        balance(destination_a, token_a),
        balance(destination_b, token_b),
    ]
    assert sorted(destination_balances) == ["0.00", "80.00"]
    assert sorted((len(entries(key_a)), len(entries(key_b)))) == [0, 3]


def test_technical_failure_rolls_back_and_can_be_retried(monkeypatch):
    sender, token = client()
    recipient, recipient_token = client()
    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]
    deposit(source_key, "30.00")
    key = request_transfer(
        source_key, destination_key, token, "10.00"
    )

    def fail_add_all(self, instances):
        raise RuntimeError("simulated technical failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "add_all", fail_add_all)
        with pytest.raises(RuntimeError, match="simulated technical failure"):
            process(key)

    assert detail(source_key, key, token)["status"] == "PENDING"
    assert balance(source_key, token) == "30.00"
    assert balance(destination_key, recipient_token) == "0.00"
    assert entries(key) == []

    assert process(key) == "COMPLETED"
    assert balance(source_key, token) == "19.95"
    assert balance(destination_key, recipient_token) == "10.00"