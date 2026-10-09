from os import environ
from time import monotonic, sleep
from uuid import uuid4

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


def test_service_payment_and_transfer_to_personal_account():
    email = f"jornada.{uuid4().hex}@example.com"

    created = send(
        "POST",
        "/clients",
        payload={
            "name": "Profissional de Teste",
            "email": email,
            "document_number": RandomGenerator.generate_cpf(),
            "password": PASSWORD,
        },
    )
    assert created.response_status == 201

    accounts = {
        account["type"]: account["account_key"]
        for account in created.response_json["accounts"]
    }
    professional_key = accounts["professional"]
    personal_key = accounts["personal"]

    login = send(
        "POST",
        "/auth/login",
        payload={"email": email, "password": PASSWORD},
    )
    assert login.response_status == 200
    token = login.response_json["access_token"]

    charge = send(
        "POST",
        f"/accounts/{professional_key}/charges",
        payload={"description": "Criação de site", "amount": "100.00"},
        headers=bearer(token),
    )
    assert charge.response_status == 201
    assert charge.response_json["status"] == "OPEN"

    payment = send(
        "POST",
        f"/accounts/{professional_key}/deposits",
        payload={
            "amount": "100.00",
            "external_reference": charge.response_json["payment_reference"],
        },
        headers={
            "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
        },
    )
    assert payment.response_status == 201

    charge_detail = send(
        "GET",
        (
            f"/accounts/{professional_key}/charges/"
            f"{charge.response_json['charge_key']}"
        ),
        headers=bearer(token),
    )
    assert charge_detail.response_status == 200
    assert charge_detail.response_json["status"] == "PAID"

    transfer = send(
        "POST",
        f"/accounts/{professional_key}/transfers",
        payload={
            "amount": "30.00",
            "destination_account_key": personal_key,
            "idempotency_key": str(uuid4()),
        },
        headers=bearer(token),
    )
    assert transfer.response_status in (200, 202)
    assert transfer.response_json["fee"] == "0.00"

    transfer_endpoint = (
        f"/accounts/{professional_key}/transfers/"
        f"{transfer.response_json['transaction_key']}"
    )
    deadline = monotonic() + 30

    while monotonic() < deadline:
        detail = send("GET", transfer_endpoint, headers=bearer(token))
        assert detail.response_status == 200

        if detail.response_json["status"] == "COMPLETED":
            break

        assert detail.response_json["status"] == "PENDING"
        sleep(0.25)
    else:
        raise AssertionError("Worker did not complete the transfer")

    professional = send(
        "GET",
        f"/accounts/{professional_key}",
        headers=bearer(token),
    )
    personal = send(
        "GET",
        f"/accounts/{personal_key}",
        headers=bearer(token),
    )
    assert professional.response_json["balance"] == "70.00"
    assert personal.response_json["balance"] == "30.00"

    professional_entries = send(
        "GET",
        f"/accounts/{professional_key}/entries",
        headers=bearer(token),
    )
    assert [
        (entry["kind"], entry["amount"])
        for entry in professional_entries.response_json["entries"]
    ] == [
        ("DEBIT", "-30.00"),
        ("CREDIT", "100.00"),
    ]