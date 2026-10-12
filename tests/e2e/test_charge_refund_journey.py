from os import environ
from time import monotonic, sleep
from uuid import uuid4

from tests.e2e.test_charge_payment_journey import create_client, send
from tests.e2e.test_worker_recovery import compose, financial_state


def wait_completed(endpoint, auth):
    deadline = monotonic() + 40

    while monotonic() < deadline:
        response = send("GET", endpoint, headers=auth)
        assert response.status_code == 200, response.text

        body = response.json()
        if body["status"] != "PENDING":
            assert body["status"] == "COMPLETED", body
            return body

        sleep(0.25)

    raise AssertionError(
        f"O worker não concluiu a operação: {endpoint}"
    )


def internal_headers():
    return {
        "INTERNAL-TOKEN": environ.get(
            "INTERNAL_TOKEN", "default_token"
        )
    }


def get_json(endpoint, auth):
    response = send("GET", endpoint, headers=auth)
    assert response.status_code == 200, response.text
    return response.json()


def assert_refund_reconciled(account, expected_balance):
    body = get_json(
        f"/internal/accounts/{account}/reconciliation",
        internal_headers(),
    )

    assert body["consistent"] is True, body
    assert body["balance"] == expected_balance
    assert body["ledger_balance"] == expected_balance
    assert body["refunded_charges_checked"] == 1
    assert body["issues"] == []


def test_charge_refund_recovers_and_preserves_financial_history():
    merchant, merchant_auth = create_client()
    payer, payer_auth = create_client()

    merchant_account = merchant["professional"]
    payer_account = payer["personal"]

    created = send(
        "POST",
        f"/accounts/{merchant_account}/charges",
        headers=merchant_auth,
        json={
            "description": "Serviço com devolução",
            "amount": "100.00",
        },
    )
    assert created.status_code == 201, created.text

    charge_key = created.json()["charge_key"]
    charge_path = (
        f"/accounts/{merchant_account}/charges/{charge_key}"
    )

    funding = send(
        "POST",
        f"/accounts/{payer_account}/deposits",
        headers=internal_headers(),
        json={
            "amount": "100.50",
            "external_reference": f"refund-e2e-{uuid4().hex}",
        },
    )
    assert funding.status_code == 201, funding.text

    payment_payload = {
        "charge_key": charge_key,
        "idempotency_key": str(uuid4()),
    }
    payment = send(
        "POST",
        f"/accounts/{payer_account}/charge-payments",
        headers=payer_auth,
        json=payment_payload,
    )
    assert payment.status_code in (200, 202), payment.text

    payment_key = payment.json()["transaction_key"]
    payment_path = (
        f"/accounts/{payer_account}/transfers/{payment_key}"
    )

    paid = wait_completed(payment_path, payer_auth)
    assert paid["fee"] == "0.50"

    original_receipt = get_json(
        f"{charge_path}/receipt", merchant_auth
    )
    assert get_json(
        charge_path, merchant_auth
    )["status"] == "PAID"

    payload = {"idempotency_key": str(uuid4())}
    refund_request_path = f"{charge_path}/refunds"

    try:
        compose("stop", "worker")

        requested = send(
            "POST",
            refund_request_path,
            headers=merchant_auth,
            json=payload,
        )
        assert requested.status_code == 202, requested.text

        key = requested.json()["transaction_key"]
        refund_path = f"{refund_request_path}/{key}"
        receipt_path = f"{refund_path}/receipt"

        assert get_json(
            refund_path, merchant_auth
        )["status"] == "PENDING"
        assert get_json(
            charge_path, merchant_auth
        )["status"] == "PAID"

        assert financial_state(
            merchant_account,
            merchant_auth,
            payer_account,
            payer_auth,
            key,
        ) == ("100.00", "0.00", [], [])

        unavailable_receipt = send(
            "GET",
            receipt_path,
            headers=merchant_auth,
        )
        assert unavailable_receipt.status_code == 409

        compose("start", "worker")

        completed = wait_completed(refund_path, merchant_auth)
        assert completed["kind"] == "REFUND"
        assert completed["amount"] == "100.00"
        assert completed["fee"] == "0.00"
        assert completed["original_fee_retained"] == "0.50"
        assert (
            completed["refund_of_transaction_key"]
            == payment_key
        )

        expected_state = (
            "0.00",
            "100.00",
            [("DEBIT", "-100.00")],
            [("CREDIT", "100.00")],
        )
        assert financial_state(
            merchant_account,
            merchant_auth,
            payer_account,
            payer_auth,
            key,
        ) == expected_state

        charge = get_json(charge_path, merchant_auth)
        assert charge["status"] == "REFUNDED"
        assert (
            charge["refunded_at"]
            == completed["completed_at"]
        )
        assert get_json(
            f"{charge_path}/receipt", merchant_auth
        ) == original_receipt

        original = get_json(payment_path, payer_auth)
        assert original["status"] == "COMPLETED"
        assert original["fee"] == "0.50"

        payer_entries = get_json(
            f"/accounts/{payer_account}/entries",
            payer_auth,
        )
        assert sorted(
            (entry["kind"], entry["amount"])
            for entry in payer_entries["entries"]
            if entry["transaction_key"] == payment_key
        ) == [
            ("DEBIT", "-100.00"),
            ("FEE", "-0.50"),
        ]

        proof = get_json(receipt_path, merchant_auth)
        assert proof["transaction_key"] == key
        assert proof["refund_of_transaction_key"] == payment_key
        assert proof["amount_refunded"] == "100.00"
        assert proof["fee"] == "0.00"
        assert proof["original_fee_retained"] == "0.50"
        assert proof["refunded_at"] == completed["completed_at"]

        summary = get_json(
            f"/accounts/{merchant_account}/charges/summary",
            merchant_auth,
        )
        assert summary["paid"] == {
            "count": 0,
            "amount": "0.00",
        }
        assert summary["refunded"] == {
            "count": 1,
            "amount": "100.00",
        }

        assert_refund_reconciled(merchant_account, "0.00")
        assert_refund_reconciled(payer_account, "100.00")

        compose("restart", "worker")

        repeated = send(
            "POST",
            refund_request_path,
            headers=merchant_auth,
            json=payload,
        )
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["transaction_key"] == key
        assert repeated.json()["status"] == "COMPLETED"
        assert get_json(receipt_path, merchant_auth) == proof

        new_attempt = send(
            "POST",
            refund_request_path,
            headers=merchant_auth,
            json={"idempotency_key": str(uuid4())},
        )
        assert new_attempt.status_code == 409, new_attempt.text
        assert new_attempt.json()["code"] == "KOD008002"

        original_retry = send(
            "POST",
            f"/accounts/{payer_account}/charge-payments",
            headers=payer_auth,
            json=payment_payload,
        )
        assert original_retry.status_code == 200, original_retry.text
        assert (
            original_retry.json()["transaction_key"]
            == payment_key
        )
        assert original_retry.json()["status"] == "COMPLETED"

        assert financial_state(
            merchant_account,
            merchant_auth,
            payer_account,
            payer_auth,
            key,
        ) == expected_state

        assert_refund_reconciled(merchant_account, "0.00")
        assert_refund_reconciled(payer_account, "100.00")

    finally:
        compose("start", "worker")