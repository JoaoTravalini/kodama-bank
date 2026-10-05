from os import environ
from time import monotonic, sleep
from uuid import uuid4

from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None):
    return ClientRequisition.send(
        method, endpoint, payload=payload, headers=headers
    )


def create_client():
    email = f"worker.{uuid4().hex}@example.com"

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


def test_worker_completes_transfer_over_http():
    sender, sender_token = create_client()
    recipient, recipient_token = create_client()

    source_key = sender["accounts"][0]["account_key"]
    destination_key = recipient["accounts"][0]["account_key"]

    deposit = send(
        "POST",
        f"/accounts/{source_key}/deposits",
        payload={
            "amount": "100.00",
            "external_reference": f"worker-deposit-{uuid4().hex}",
        },
        headers={
            "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
        },
    )
    assert deposit.response_status == 201

    payload = {
        "amount": "40.00",
        "destination_account_key": destination_key,
        "idempotency_key": str(uuid4()),
    }
    transfer = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        payload=payload,
        headers=bearer(sender_token),
    )
    assert transfer.response_status in (200, 202)
    transaction_key = transfer.response_json["transaction_key"]

    endpoint = (
        f"/accounts/{source_key}/transfers/{transaction_key}"
    )
    deadline = monotonic() + 30

    while monotonic() < deadline:
        detail = send("GET", endpoint, headers=bearer(sender_token))
        assert detail.response_status == 200

        if detail.response_json["status"] == "COMPLETED":
            break

        assert detail.response_json["status"] == "PENDING"
        sleep(0.25)
    else:
        raise AssertionError(
            f"Worker did not complete transfer: {detail.response_json}"
        )

    assert detail.response_json["fee"] == "0.20"

    source = send(
        "GET", f"/accounts/{source_key}", headers=bearer(sender_token)
    )
    destination = send(
        "GET",
        f"/accounts/{destination_key}",
        headers=bearer(recipient_token),
    )
    assert source.response_json["balance"] == "59.80"
    assert destination.response_json["balance"] == "40.00"

    source_entries = send(
        "GET",
        f"/accounts/{source_key}/entries",
        headers=bearer(sender_token),
    )
    assert [
        (entry["kind"], entry["amount"])
        for entry in source_entries.response_json["entries"]
    ] == [
        ("FEE", "-0.20"),
        ("DEBIT", "-40.00"),
        ("CREDIT", "100.00"),
    ]

    repeated = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        payload=payload,
        headers=bearer(sender_token),
    )
    assert repeated.response_status == 200
    assert repeated.response_json["transaction_key"] == transaction_key
    
    assert repeated.response_json["status"] == "COMPLETED"

    source_after_retry = send(
        "GET", f"/accounts/{source_key}", headers=bearer(sender_token)
    )
    destination_after_retry = send(
        "GET",
        f"/accounts/{destination_key}",
        headers=bearer(recipient_token),
    )
    assert source_after_retry.response_status == 200
    assert destination_after_retry.response_status == 200
    assert source_after_retry.response_json["balance"] == "59.80"
    assert destination_after_retry.response_json["balance"] == "40.00"

    source_entries_after_retry = send(
        "GET",
        f"/accounts/{source_key}/entries",
        headers=bearer(sender_token),
    )
    destination_entries_after_retry = send(
        "GET",
        f"/accounts/{destination_key}/entries",
        headers=bearer(recipient_token),
    )
    assert source_entries_after_retry.response_status == 200
    assert destination_entries_after_retry.response_status == 200

    assert [
        (entry["kind"], entry["amount"])
        for entry in source_entries_after_retry.response_json["entries"]
    ] == [
        ("FEE", "-0.20"),
        ("DEBIT", "-40.00"),
        ("CREDIT", "100.00"),
    ]
    assert [
        (entry["kind"], entry["amount"])
        for entry in destination_entries_after_retry.response_json["entries"]
    ] == [("CREDIT", "40.00")]