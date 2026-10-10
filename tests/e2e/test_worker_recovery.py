import os
import subprocess
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


def compose(*args):
    subprocess.run(
        ["docker", "compose", *args],
        check=True,
        timeout=90,
    )


def create_client():
    email = f"worker-recovery.{uuid4().hex}@example.com"

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
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return account_key, auth


def financial_state(source_key, source_auth, destination_key, destination_auth,
                    transaction_key):
    source = send("GET", f"/accounts/{source_key}", headers=source_auth)
    destination = send(
        "GET", f"/accounts/{destination_key}", headers=destination_auth
    )
    source_entries = send(
        "GET", f"/accounts/{source_key}/entries", headers=source_auth
    )
    destination_entries = send(
        "GET", f"/accounts/{destination_key}/entries",
        headers=destination_auth,
    )

    for response in (source, destination, source_entries, destination_entries):
        assert response.status_code == 200, response.text

    def transfer_entries(response):
        return sorted(
            (entry["kind"], entry["amount"])
            for entry in response.json()["entries"]
            if entry["transaction_key"] == transaction_key
        )

    return (
        source.json()["balance"],
        destination.json()["balance"],
        transfer_entries(source_entries),
        transfer_entries(destination_entries),
    )


def assert_reconciled(account_key, expected_balance):
    response = send(
        "GET",
        f"/internal/accounts/{account_key}/reconciliation",
        headers={
            "INTERNAL-TOKEN": os.environ.get(
                "INTERNAL_TOKEN", "default_token"
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["consistent"] is True, response.text
    assert response.json()["balance"] == expected_balance
    assert response.json()["ledger_balance"] == expected_balance
    assert response.json()["issues"] == []


def test_pending_transfer_recovers_after_worker_restart():
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
            "external_reference": f"worker-recovery-{uuid4().hex}",
        },
    )
    assert deposit.status_code == 201, deposit.text

    payload = {
        "amount": "40.00",
        "destination_account_key": destination_key,
        "idempotency_key": str(uuid4()),
    }

    try:
        compose("stop", "worker")

        requested = send(
            "POST",
            f"/accounts/{source_key}/transfers",
            headers=source_auth,
            json=payload,
        )
        assert requested.status_code == 202, requested.text
        transaction_key = requested.json()["transaction_key"]

        endpoint = f"/accounts/{source_key}/transfers/{transaction_key}"
        pending = send("GET", endpoint, headers=source_auth)
        assert pending.status_code == 200, pending.text
        assert pending.json()["status"] == "PENDING"

        assert financial_state(
            source_key, source_auth, destination_key, destination_auth,
            transaction_key,
        ) == ("100.00", "0.00", [], [])

        compose("start", "worker")

        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            detail = send("GET", endpoint, headers=source_auth)
            assert detail.status_code == 200, detail.text
            if detail.json()["status"] != "PENDING":
                break
            time.sleep(0.25)
        else:
            raise AssertionError(
                "O worker não processou a transferência após voltar"
            )

        assert detail.json()["status"] == "COMPLETED", detail.text
        assert detail.json()["fee"] == "0.20"

        completed_state = (
            "59.80",
            "40.00",
            [("DEBIT", "-40.00"), ("FEE", "-0.20")],
            [("CREDIT", "40.00")],
        )
        assert financial_state(
            source_key, source_auth, destination_key, destination_auth,
            transaction_key,
        ) == completed_state

        assert_reconciled(source_key, "59.80")
        assert_reconciled(destination_key, "40.00")

        compose("restart", "worker")

        repeated = send(
            "POST",
            f"/accounts/{source_key}/transfers",
            headers=source_auth,
            json=payload,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["transaction_key"] == transaction_key
        assert repeated.json()["status"] == "COMPLETED"

        assert financial_state(
            source_key, source_auth, destination_key, destination_auth,
            transaction_key,
        ) == completed_state

        assert_reconciled(source_key, "59.80")
        assert_reconciled(destination_key, "40.00")

    finally:
        compose("start", "worker")