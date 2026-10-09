from os import environ
from time import monotonic, sleep
from uuid import uuid4

import requests

from tests.utils.random_generator import RandomGenerator


BASE_URL = (
    f"http://{environ.get('SERVER_LOCALHOST', '127.0.0.1')}:"
    f"{environ.get('API_PORT', '3000')}"
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
    email = f"jornada-pagamento.{uuid4().hex}@example.com"

    created = send(
        "POST",
        "/clients",
        json={
            "name": "Cliente da Jornada",
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

    accounts = {
        account["type"]: account["account_key"]
        for account in created.json()["accounts"]
    }
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return accounts, auth


def test_client_pays_service_charge_through_worker():
    merchant, merchant_auth = create_client()
    payer, payer_auth = create_client()
    destination = merchant["professional"]
    source = payer["personal"]

    charge_response = send(
        "POST",
        f"/accounts/{destination}/charges",
        headers=merchant_auth,
        json={
            "description": "Desenvolvimento de site",
            "amount": "120.00",
        },
    )
    assert charge_response.status_code == 201, charge_response.text
    charge_key = charge_response.json()["charge_key"]

    funding = send(
        "POST",
        f"/accounts/{source}/deposits",
        headers={
            "INTERNAL-TOKEN": environ.get(
                "INTERNAL_TOKEN", "default_token"
            )
        },
        json={
            "amount": "120.60",
            "external_reference": f"funding-{uuid4().hex}",
        },
    )
    assert funding.status_code == 201, funding.text

    idempotency_key = str(uuid4())
    payload = {
        "charge_key": charge_key,
        "idempotency_key": idempotency_key,
    }
    requested = send(
        "POST",
        f"/accounts/{source}/charge-payments",
        headers=payer_auth,
        json=payload,
    )
    assert requested.status_code in (200, 202), requested.text
    assert requested.json()["amount"] == "120.00"
    assert requested.json()["fee"] == "0.60"
    transaction_key = requested.json()["transaction_key"]

    endpoint = f"/accounts/{source}/transfers/{transaction_key}"
    deadline = monotonic() + 30

    while monotonic() < deadline:
        detail = send("GET", endpoint, headers=payer_auth)
        assert detail.status_code == 200, detail.text

        if detail.json()["status"] != "PENDING":
            break

        sleep(0.25)
    else:
        raise AssertionError("Worker did not process the charge payment")

    assert detail.json()["status"] == "COMPLETED", detail.text

    charge = send(
        "GET",
        f"/accounts/{destination}/charges/{charge_key}",
        headers=merchant_auth,
    )
    source_account = send(
        "GET", f"/accounts/{source}", headers=payer_auth
    )
    destination_account = send(
        "GET", f"/accounts/{destination}", headers=merchant_auth
    )

    assert charge.status_code == 200
    assert charge.json()["status"] == "PAID"
    assert source_account.json()["balance"] == "0.00"
    assert destination_account.json()["balance"] == "120.00"

    source_entries = send(
        "GET", f"/accounts/{source}/entries", headers=payer_auth
    )
    destination_entries = send(
        "GET",
        f"/accounts/{destination}/entries",
        headers=merchant_auth,
    )
    assert {
        (entry["kind"], entry["amount"])
        for entry in source_entries.json()["entries"]
        if entry["transaction_key"] == transaction_key
    } == {("DEBIT", "-120.00"), ("FEE", "-0.60")}
    assert {
        (entry["kind"], entry["amount"])
        for entry in destination_entries.json()["entries"]
        if entry["transaction_key"] == transaction_key
    } == {("CREDIT", "120.00")}

    internal_headers = {
        "INTERNAL-TOKEN": environ.get(
            "INTERNAL_TOKEN", "default_token"
        )
    }
    for account_key, expected_balance, paid_count in (
        (source, "0.00", 0),
        (destination, "120.00", 1),
    ):
        reconciliation = send(
            "GET",
            f"/internal/accounts/{account_key}/reconciliation",
            headers=internal_headers,
        )
        assert reconciliation.status_code == 200
        assert reconciliation.json()["balance"] == expected_balance
        assert reconciliation.json()["ledger_balance"] == expected_balance
        assert reconciliation.json()["paid_charges_checked"] == paid_count
        assert reconciliation.json()["consistent"] is True
        assert reconciliation.json()["issues"] == []

    repeated = send(
        "POST",
        f"/accounts/{source}/charge-payments",
        headers=payer_auth,
        json=payload,
    )
    assert repeated.status_code == 200
    assert repeated.json()["transaction_key"] == transaction_key
    assert repeated.json()["status"] == "COMPLETED"

    new_attempt = send(
        "POST",
        f"/accounts/{source}/charge-payments",
        headers=payer_auth,
        json={
            "charge_key": charge_key,
            "idempotency_key": str(uuid4()),
        },
    )
    assert new_attempt.status_code == 409
    assert new_attempt.json()["code"] == "KOD007002"