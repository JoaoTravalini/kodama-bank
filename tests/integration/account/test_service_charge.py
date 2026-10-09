from uuid import uuid4

from tests.utils.random_generator import RandomGenerator
from tests.utils.requisition import ClientRequisition
from concurrent.futures import ThreadPoolExecutor
from os import environ


PASSWORD = "SenhaDeTeste123!"


def send(method, endpoint, payload=None, headers=None):
    return ClientRequisition.send(
        method,
        endpoint,
        payload=payload,
        headers=headers,
    )


def create_client():
    email = f"cobranca.{uuid4().hex}@example.com"

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


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_creates_and_reads_open_charge_without_moving_money():
    accounts, token = create_client()
    account_key = accounts["professional"]
    endpoint = f"/accounts/{account_key}/charges"

    created = send(
        "POST",
        endpoint,
        payload={"description": "Criação de site", "amount": "120.00"},
        headers=bearer(token),
    )

    assert created.response_status == 201
    charge = created.response_json
    assert charge["description"] == "Criação de site"
    assert charge["amount"] == "120.00"
    assert charge["status"] == "OPEN"
    assert charge["payment_reference"] == f"charge:{charge['charge_key']}"
    assert charge["paid_at"] is None

    detail = send(
        "GET",
        f"{endpoint}/{charge['charge_key']}",
        headers=bearer(token),
    )
    assert detail.response_status == 200
    assert detail.response_json == charge

    listing = send("GET", endpoint, headers=bearer(token))
    assert listing.response_status == 200
    assert listing.response_json["charges"] == [charge]

    account = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    entries = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
    )
    assert account.response_json["balance"] == "0.00"
    assert entries.response_json["entries"] == []


def test_charge_routes_require_jwt_and_hide_other_clients_data():
    owner_accounts, owner_token = create_client()
    other_accounts, other_token = create_client()
    owner_key = owner_accounts["professional"]
    endpoint = f"/accounts/{owner_key}/charges"

    created = send(
        "POST",
        endpoint,
        payload={"description": "Consultoria", "amount": "75.00"},
        headers=bearer(owner_token),
    )
    assert created.response_status == 201
    charge_key = created.response_json["charge_key"]

    assert send(
        "POST",
        endpoint,
        payload={"description": "Teste", "amount": "1.00"},
    ).response_status == 401

    assert send("GET", endpoint).response_status == 401

    assert send(
        "GET",
        endpoint,
        headers=bearer(other_token),
    ).response_status == 404

    assert send(
        "GET",
        f"{endpoint}/{charge_key}",
        headers=bearer(other_token),
    ).response_status == 404

    # Mesmo usando uma conta própria, o outro cliente não encontra a cobrança.
    assert send(
        "GET",
        f"/accounts/{other_accounts['professional']}/charges/{charge_key}",
        headers=bearer(other_token),
    ).response_status == 404


def test_only_professional_account_can_create_charge():
    accounts, token = create_client()

    response = send(
        "POST",
        f"/accounts/{accounts['personal']}/charges",
        payload={"description": "Serviço", "amount": "50.00"},
        headers=bearer(token),
    )

    assert response.response_status == 422
    assert response.response_json["code"] == "KOD006002"


def test_rejects_invalid_charge_data():
    accounts, token = create_client()
    endpoint = f"/accounts/{accounts['professional']}/charges"

    zero = send(
        "POST",
        endpoint,
        payload={"description": "Serviço", "amount": "0.00"},
        headers=bearer(token),
    )
    assert zero.response_status == 422
    assert zero.response_json["code"] == "KOD006003"

    for payload in (
        {"description": "   ", "amount": "10.00"},
        {"description": "Serviço", "amount": "dez"},
        {"description": "Serviço", "amount": "10.00", "status": "PAID"},
    ):
        response = send(
            "POST",
            endpoint,
            payload=payload,
            headers=bearer(token),
        )
        assert response.response_status == 400


def test_lists_charges_with_pagination():
    accounts, token = create_client()
    endpoint = f"/accounts/{accounts['professional']}/charges"

    first = send(
        "POST",
        endpoint,
        payload={"description": "Primeiro serviço", "amount": "10.00"},
        headers=bearer(token),
    )
    second = send(
        "POST",
        endpoint,
        payload={"description": "Segundo serviço", "amount": "20.00"},
        headers=bearer(token),
    )
    assert first.response_status == 201
    assert second.response_status == 201

    page_one = send(
        "GET",
        f"{endpoint}?page=1&limit=1",
        headers=bearer(token),
    )
    page_two = send(
        "GET",
        f"{endpoint}?page=2&limit=1",
        headers=bearer(token),
    )

    assert page_one.response_status == 200
    assert page_one.response_json["has_more"] is True
    assert page_one.response_json["charges"][0]["charge_key"] == (
        second.response_json["charge_key"]
    )

    assert page_two.response_status == 200
    assert page_two.response_json["has_more"] is False
    assert page_two.response_json["charges"][0]["charge_key"] == (
        first.response_json["charge_key"]
    )

    invalid_page = send(
        "GET",
        f"{endpoint}?page=0",
        headers=bearer(token),
    )
    assert invalid_page.response_status == 400

def internal_headers():
    return {"INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")}


def create_charge(account_key, token, amount="120.00"):
    response = send(
        "POST",
        f"/accounts/{account_key}/charges",
        payload={"description": "Criação de site", "amount": amount},
        headers=bearer(token),
    )
    assert response.response_status == 201
    return response.response_json


def pay_charge(account_key, charge, amount=None, headers=None):
    return send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": amount or charge["amount"],
            "external_reference": charge["payment_reference"],
        },
        headers=headers if headers is not None else internal_headers(),
    )


def test_payment_closes_charge_and_credits_professional_account():
    accounts, token = create_client()
    account_key = accounts["professional"]
    charge = create_charge(account_key, token)

    payment = pay_charge(account_key, charge)
    assert payment.response_status == 201
    assert payment.response_json["status"] == "COMPLETED"
    assert payment.response_json["amount"] == "120.00"

    detail = send(
        "GET",
        f"/accounts/{account_key}/charges/{charge['charge_key']}",
        headers=bearer(token),
    )
    assert detail.response_status == 200
    assert detail.response_json["status"] == "PAID"
    assert detail.response_json["paid_at"] is not None

    account = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    entries = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
    )
    assert account.response_json["balance"] == "120.00"
    assert [
        (entry["kind"], entry["amount"], entry["transaction_key"])
        for entry in entries.response_json["entries"]
    ] == [("CREDIT", "120.00", payment.response_json["transaction_key"])]


def test_repeating_charge_payment_does_not_credit_twice():
    accounts, token = create_client()
    account_key = accounts["professional"]
    charge = create_charge(account_key, token)

    first = pay_charge(account_key, charge)
    repeated = pay_charge(account_key, charge)

    assert first.response_status == 201
    assert repeated.response_status == 201
    assert repeated.response_json == first.response_json

    account = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    entries = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
    )
    assert account.response_json["balance"] == "120.00"
    assert len(entries.response_json["entries"]) == 1


def test_charge_payment_rejects_wrong_amount_or_account():
    owner_accounts, owner_token = create_client()
    other_accounts, other_token = create_client()
    owner_key = owner_accounts["professional"]
    other_key = other_accounts["professional"]
    charge = create_charge(owner_key, owner_token)

    wrong_amount = pay_charge(owner_key, charge, amount="119.00")
    wrong_account = pay_charge(other_key, charge)

    assert wrong_amount.response_status == 409
    assert wrong_amount.response_json["code"] == "KOD006004"
    assert wrong_account.response_status == 409
    assert wrong_account.response_json["code"] == "KOD006004"

    detail = send(
        "GET",
        f"/accounts/{owner_key}/charges/{charge['charge_key']}",
        headers=bearer(owner_token),
    )
    owner_account = send(
        "GET",
        f"/accounts/{owner_key}",
        headers=bearer(owner_token),
    )
    other_account = send(
        "GET",
        f"/accounts/{other_key}",
        headers=bearer(other_token),
    )

    assert detail.response_json["status"] == "OPEN"
    assert owner_account.response_json["balance"] == "0.00"
    assert other_account.response_json["balance"] == "0.00"


def test_charge_payment_requires_internal_token():
    accounts, token = create_client()
    account_key = accounts["professional"]
    charge = create_charge(account_key, token)

    response = pay_charge(
        account_key,
        charge,
        headers=bearer(token),
    )
    assert response.response_status == 403

    detail = send(
        "GET",
        f"/accounts/{account_key}/charges/{charge['charge_key']}",
        headers=bearer(token),
    )
    assert detail.response_json["status"] == "OPEN"

def test_concurrent_retries_credit_charge_only_once():
    accounts, token = create_client()
    account_key = accounts["professional"]
    charge = create_charge(account_key, token)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(pay_charge, account_key, charge)
            for _ in range(2)
        ]
        responses = [future.result() for future in futures]

    assert [response.response_status for response in responses] == [201, 201]
    assert (
        responses[0].response_json["transaction_key"]
        == responses[1].response_json["transaction_key"]
    )

    account = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    entries = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers=bearer(token),
    )
    assert account.response_json["balance"] == "120.00"
    assert len(entries.response_json["entries"]) == 1

def test_invalid_references_do_not_credit_or_block_later_payment():
    accounts, token = create_client()
    account_key = accounts["professional"]
    charge = create_charge(account_key, token)

    for reference in ("charge:not-a-uuid", f"charge:{uuid4()}"):
        response = send(
            "POST",
            f"/accounts/{account_key}/deposits",
            payload={
                "amount": "120.00",
                "external_reference": reference,
            },
            headers=internal_headers(),
        )
        assert response.response_status == 409
        assert response.response_json["code"] == "KOD006004"

    account = send(
        "GET",
        f"/accounts/{account_key}",
        headers=bearer(token),
    )
    assert account.response_json["balance"] == "0.00"

    correct_payment = pay_charge(account_key, charge)
    assert correct_payment.response_status == 201

    detail = send(
        "GET",
        f"/accounts/{account_key}/charges/{charge['charge_key']}",
        headers=bearer(token),
    )
    assert detail.response_json["status"] == "PAID"