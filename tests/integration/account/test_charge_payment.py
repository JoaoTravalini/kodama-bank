from concurrent.futures import ThreadPoolExecutor
from os import environ
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.utils.db_utils import DbUtils
from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition
from workers.transfer_processor import TransferProcessor

import pytest


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None):
    return ClientRequisition.send(
        method, endpoint, payload=payload, headers=headers
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def create_client():
    email = f"pagamento.{uuid4().hex}@example.com"
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

    accounts = {
        account["type"]: account["account_key"]
        for account in created.response_json["accounts"]
    }
    return accounts, login.response_json["access_token"]


def create_charge(account_key, token, amount="100.00"):
    response = send(
        "POST",
        f"/accounts/{account_key}/charges",
        payload={"description": "Serviço de teste", "amount": amount},
        headers=bearer(token),
    )
    assert response.response_status == 201
    return response.response_json


def deposit(account_key, amount):
    response = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": amount,
            "external_reference": f"funds-{uuid4().hex}",
        },
        headers={
            "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
        },
    )
    assert response.response_status == 201


def request_payment(source_key, token, charge_key, idempotency_key=None):
    return send(
        "POST",
        f"/accounts/{source_key}/charge-payments",
        payload={
            "charge_key": charge_key,
            "idempotency_key": idempotency_key or str(uuid4()),
        },
        headers=bearer(token),
    )


def process(transaction_key):
    engine = create_engine(DbUtils.database_url())
    try:
        with Session(engine, autoflush=False) as session:
            return TransferProcessor(session).process(UUID(transaction_key))
    finally:
        engine.dispose()


def balance(account_key, token):
    response = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    assert response.response_status == 200
    return response.response_json["balance"]


def charge_detail(account_key, charge_key, token):
    response = send(
        "GET",
        f"/accounts/{account_key}/charges/{charge_key}",
        headers=bearer(token),
    )
    assert response.response_status == 200
    return response.response_json


def transfer_detail(source_key, transaction_key, token):
    response = send(
        "GET",
        f"/accounts/{source_key}/transfers/{transaction_key}",
        headers=bearer(token),
    )
    assert response.response_status == 200
    return response.response_json


def transaction_entries(account_key, transaction_key, token):
    response = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
    )
    assert response.response_status == 200
    return {
        (entry["kind"], entry["amount"])
        for entry in response.response_json["entries"]
        if entry["transaction_key"] == transaction_key
    }


def test_payment_completes_with_fee_entries_and_reconciliation():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    destination = merchant["professional"]
    source = payer["personal"]

    charge = create_charge(destination, merchant_token)
    deposit(source, "100.50")

    requested = request_payment(
        source, payer_token, charge["charge_key"]
    )
    assert requested.response_status == 202
    payment = requested.response_json
    assert payment["status"] == "PENDING"
    assert payment["amount"] == "100.00"
    assert payment["fee"] == "0.50"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "OPEN"
    assert balance(source, payer_token) == "100.50"
    assert balance(destination, merchant_token) == "0.00"

    key = payment["transaction_key"]
    assert process(key) == "COMPLETED"
    assert process(key) == "COMPLETED"

    assert balance(source, payer_token) == "0.00"
    assert balance(destination, merchant_token) == "100.00"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "PAID"
    assert transaction_entries(source, key, payer_token) == {
        ("DEBIT", "-100.00"),
        ("FEE", "-0.50"),
    }
    assert transaction_entries(
        destination, key, merchant_token
    ) == {("CREDIT", "100.00")}

    reconciled = send(
        "GET",
        f"/internal/accounts/{destination}/reconciliation",
        headers={
            "INTERNAL-TOKEN": environ.get(
                "INTERNAL_TOKEN", "default_token"
            )
        },
    )
    assert reconciled.response_status == 200
    assert reconciled.response_json["consistent"] is True
    assert reconciled.response_json["paid_charges_checked"] == 1
    assert reconciled.response_json["issues"] == []


def test_insufficient_funds_keeps_charge_open_and_allows_new_attempt():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    destination = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(destination, merchant_token)
    deposit(source, "100.00")

    first = request_payment(source, payer_token, charge["charge_key"])
    assert first.response_status == 202
    first_key = first.response_json["transaction_key"]

    assert process(first_key) == "REJECTED"
    assert transfer_detail(
        source, first_key, payer_token
    )["rejection_reason"] == "INSUFFICIENT_FUNDS"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "OPEN"
    assert balance(source, payer_token) == "100.00"
    assert balance(destination, merchant_token) == "0.00"
    assert transaction_entries(source, first_key, payer_token) == set()

    deposit(source, "1.00")
    second = request_payment(source, payer_token, charge["charge_key"])
    assert second.response_status == 202
    second_key = second.response_json["transaction_key"]
    assert second_key != first_key
    assert process(second_key) == "COMPLETED"

    assert balance(source, payer_token) == "0.50"
    assert balance(destination, merchant_token) == "100.00"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "PAID"


def test_two_payers_cannot_pay_one_charge_twice():
    merchant, merchant_token = create_client()
    payer_a, token_a = create_client()
    payer_b, token_b = create_client()
    destination = merchant["professional"]
    source_a = payer_a["personal"]
    source_b = payer_b["personal"]
    charge = create_charge(destination, merchant_token)

    deposit(source_a, "100.50")
    deposit(source_b, "100.50")

    first = request_payment(source_a, token_a, charge["charge_key"])
    second = request_payment(source_b, token_b, charge["charge_key"])
    assert first.response_status == 202
    assert second.response_status == 202

    keys = (
        first.response_json["transaction_key"],
        second.response_json["transaction_key"],
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(process, keys))

    assert sorted(statuses) == ["COMPLETED", "REJECTED"]
    assert balance(destination, merchant_token) == "100.00"
    assert sorted((
        balance(source_a, token_a),
        balance(source_b, token_b),
    )) == ["0.00", "100.50"]
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "PAID"

    losing_index = statuses.index("REJECTED")
    losing_source = (source_a, source_b)[losing_index]
    losing_token = (token_a, token_b)[losing_index]
    losing_key = keys[losing_index]
    assert transfer_detail(
        losing_source, losing_key, losing_token
    )["rejection_reason"] == "CHARGE_ALREADY_PAID"
    assert transaction_entries(
        losing_source, losing_key, losing_token
    ) == set()


def test_auth_ownership_and_idempotency_boundaries():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    destination = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(destination, merchant_token)
    another = create_charge(destination, merchant_token)
    endpoint = f"/accounts/{source}/charge-payments"
    key = str(uuid4())
    payload = {
        "charge_key": charge["charge_key"],
        "idempotency_key": key,
    }

    assert send(
        "POST", endpoint, payload=payload
    ).response_status == 401
    assert send(
        "POST", endpoint, payload=payload,
        headers=bearer(merchant_token),
    ).response_status == 404
    assert send(
        "POST", endpoint,
        payload={"charge_key": charge["charge_key"]},
        headers=bearer(payer_token),
    ).response_status == 400

    own = request_payment(
        merchant["personal"], merchant_token, charge["charge_key"]
    )
    assert own.response_status == 422
    assert own.response_json["code"] == "KOD007001"

    first = send(
        "POST", endpoint, payload=payload,
        headers=bearer(payer_token),
    )
    repeated = send(
        "POST", endpoint, payload=payload,
        headers=bearer(payer_token),
    )
    assert first.response_status == 202
    assert repeated.response_status == 202
    assert repeated.response_json["transaction_key"] == (
        first.response_json["transaction_key"]
    )

    changed_charge = request_payment(
        source, payer_token, another["charge_key"],
        idempotency_key=key,
    )
    assert changed_charge.response_status == 409

    ordinary_transfer = send(
        "POST",
        f"/accounts/{source}/transfers",
        payload={
            "amount": "100.00",
            "destination_account_key": destination,
            "idempotency_key": key,
        },
        headers=bearer(payer_token),
    )
    assert ordinary_transfer.response_status == 409


def test_deposit_winning_race_rejects_pending_payment_without_debit():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    destination = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(destination, merchant_token)
    deposit(source, "100.50")

    pending = request_payment(source, payer_token, charge["charge_key"])
    assert pending.response_status == 202
    key = pending.response_json["transaction_key"]

    external_payment = send(
        "POST",
        f"/accounts/{destination}/deposits",
        payload={
            "amount": "100.00",
            "external_reference": charge["payment_reference"],
        },
        headers={
            "INTERNAL-TOKEN": environ.get(
                "INTERNAL_TOKEN", "default_token"
            )
        },
    )
    assert external_payment.response_status == 201

    assert process(key) == "REJECTED"
    assert transfer_detail(
        source, key, payer_token
    )["rejection_reason"] == "CHARGE_ALREADY_PAID"
    assert balance(source, payer_token) == "100.50"
    assert balance(destination, merchant_token) == "100.00"
    assert transaction_entries(source, key, payer_token) == set()
    
def test_technical_failure_rolls_back_charge_and_payment(monkeypatch):
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    destination = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(destination, merchant_token)
    deposit(source, "100.50")

    requested = request_payment(
        source, payer_token, charge["charge_key"]
    )
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]

    def fail_commit(self):
        raise RuntimeError("simulated commit failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            process(key)

    assert transfer_detail(source, key, payer_token)["status"] == "PENDING"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "OPEN"
    assert balance(source, payer_token) == "100.50"
    assert balance(destination, merchant_token) == "0.00"
    assert transaction_entries(source, key, payer_token) == set()

    assert process(key) == "COMPLETED"
    assert charge_detail(
        destination, charge["charge_key"], merchant_token
    )["status"] == "PAID"