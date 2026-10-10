from os import environ
from uuid import uuid4

from tests.integration.account.test_charge_payment import (
    create_client as create_payment_client,
    deposit,
    process,
    request_payment,
)
from tests.integration.account.test_service_charge import (
    bearer,
    create_client,
    send,
)


def create_charge(account_key, token, amount="100.00"):
    response = send(
        "POST",
        f"/accounts/{account_key}/charges",
        payload={"description": "Site institucional", "amount": amount},
        headers=bearer(token),
    )
    assert response.response_status == 201
    return response.response_json


def receipt_path(account_key, charge_key):
    return f"/accounts/{account_key}/charges/{charge_key}/receipt"


def test_receipt_requires_owner_and_completed_payment():
    merchant, token = create_client()
    other, other_token = create_client()
    account_key = merchant["professional"]
    charge = create_charge(account_key, token)
    path = receipt_path(account_key, charge["charge_key"])

    assert send("GET", path).response_status == 401
    assert send("GET", path, headers=bearer(other_token)).response_status == 404
    assert send(
        "GET",
        receipt_path(other["professional"], charge["charge_key"]),
        headers=bearer(other_token),
    ).response_status == 404
    assert send("GET", path, headers=bearer(token)).response_status == 409
    assert send(
        "GET", receipt_path(account_key, uuid4()), headers=bearer(token)
    ).response_status == 404

    payment = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": "100.00",
            "external_reference": charge["payment_reference"],
        },
        headers={"INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")},
    )
    assert payment.response_status == 201

    first = send("GET", path, headers=bearer(token))
    second = send("GET", path, headers=bearer(token))
    assert first.response_status == second.response_status == 200
    assert first.response_json == second.response_json
    result = first.response_json
    assert result["charge_key"] == charge["charge_key"]
    assert result["transaction_key"] == payment.response_json["transaction_key"]
    assert result["amount_received"] == "100.00"
    assert result["balance_after_credit"] == "100.00"
    assert result["payment_method"] == "SIMULATED_INTERNAL_DEPOSIT"
    assert result["paid_at"] is not None

    entries = send(
        "GET", f"/accounts/{account_key}/entries", headers=bearer(token)
    )
    assert entries.response_status == 200
    credit = next(
        entry for entry in entries.response_json["entries"]
        if entry["transaction_key"] == result["transaction_key"]
    )
    assert credit["entry_key"] == result["credit_entry_key"]
    assert credit["amount"] == result["amount_received"]


def test_transfer_receipt_tracks_merchant_credit_without_payer_details():
    merchant, merchant_token = create_payment_client()
    payer, payer_token = create_payment_client()
    account_key = merchant["professional"]
    charge = create_charge(account_key, merchant_token)
    deposit(payer["personal"], "100.50")

    requested = request_payment(
        payer["personal"], payer_token, charge["charge_key"]
    )
    assert requested.response_status == 202
    path = receipt_path(account_key, charge["charge_key"])
    assert send("GET", path, headers=bearer(merchant_token)).response_status == 409
    assert process(requested.response_json["transaction_key"]) == "COMPLETED"

    receipt = send("GET", path, headers=bearer(merchant_token))
    assert receipt.response_status == 200
    assert receipt.response_json["payment_method"] == "KODAMA_TRANSFER"
    assert (
        receipt.response_json["transaction_key"]
        == requested.response_json["transaction_key"]
    )
    assert receipt.response_json["amount_received"] == "100.00"
    assert receipt.response_json["balance_after_credit"] == "100.00"
    assert "source_account_key" not in receipt.response_json
    assert "idempotency_key" not in receipt.response_json