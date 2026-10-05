import os
import time
from uuid import uuid4

import requests

from tests.utils.random_generator import RandomGenerator


BASE_URL = (
    f"http://{os.environ.get('SERVER_LOCALHOST', '127.0.0.1')}:"
    f"{os.environ.get('API_PORT', '3000')}"
)
PASSWORD = "SenhaDeTeste123!"


def send(method, path, **kwargs):
    return requests.request(
        method,
        f"{BASE_URL}{path}",
        timeout=10,
        **kwargs,
    )


def create_client():
    email = f"fee-boundary.{uuid4().hex}@example.com"

    created = send(
        "POST",
        "/clients",
        json={
            "name": "Cliente de Teste",
            "email": email,
            "document_number": RandomGenerator.generate_cpf(),
            "password": PASSWORD,
        },
    )
    assert created.status_code == 201, created.text

    login = send(
        "POST",
        "/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert login.status_code == 200, login.text

    account_key = created.json()["accounts"][0]["account_key"]
    authorization = {
        "Authorization": f"Bearer {login.json()['access_token']}"
    }
    return account_key, authorization


def test_transfer_requires_balance_for_amount_and_fee():
    source_key, source_auth = create_client()
    destination_key, destination_auth = create_client()

    deposit = send(
        "POST",
        f"/accounts/{source_key}/deposits",
        headers={
            "INTERNAL-TOKEN": os.environ.get(
                "INTERNAL_TOKEN", "default_token"
            )
        },
        json={
            "amount": "100.00",
            "external_reference": f"fee-boundary-{uuid4().hex}",
        },
    )
    assert deposit.status_code == 201, deposit.text

    transfer_payload = {
        "amount": "100.00",
        "destination_account_key": destination_key,
        "idempotency_key": str(uuid4()),
    }
    requested = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        headers=source_auth,
        json=transfer_payload,
    )
    assert requested.status_code in (200, 202), requested.text
    assert requested.json()["fee"] == "0.50"

    transaction_key = requested.json()["transaction_key"]
    deadline = time.monotonic() + 15

    while True:
        detail = send(
            "GET",
            f"/accounts/{source_key}/transfers/{transaction_key}",
            headers=source_auth,
        )
        assert detail.status_code == 200, detail.text

        if detail.json()["status"] != "PENDING":
            break

        assert time.monotonic() < deadline, (
            "A transferência permaneceu PENDING; confira se o worker está ativo"
        )
        time.sleep(0.25)

    assert detail.json()["status"] == "REJECTED", detail.text
    assert detail.json()["rejection_reason"] == "INSUFFICIENT_FUNDS"

    source = send("GET", f"/accounts/{source_key}", headers=source_auth)
    destination = send(
        "GET", f"/accounts/{destination_key}", headers=destination_auth
    )
    assert source.status_code == 200, source.text
    assert destination.status_code == 200, destination.text
    assert source.json()["balance"] == "100.00"
    assert destination.json()["balance"] == "0.00"

    source_entries = send(
        "GET", f"/accounts/{source_key}/entries", headers=source_auth
    )
    destination_entries = send(
        "GET", f"/accounts/{destination_key}/entries",
        headers=destination_auth,
    )
    assert source_entries.status_code == 200, source_entries.text
    assert destination_entries.status_code == 200, destination_entries.text

    # Na origem permanece somente o depósito inicial.
    assert len(source_entries.json()["entries"]) == 1
    assert source_entries.json()["entries"][0]["amount"] == "100.00"
    assert destination_entries.json()["entries"] == []

    repeated = send(
        "POST",
        f"/accounts/{source_key}/transfers",
        headers=source_auth,
        json=transfer_payload,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["transaction_key"] == transaction_key
    assert repeated.json()["status"] == "REJECTED"