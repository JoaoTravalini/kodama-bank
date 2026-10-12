from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from tests.integration.account.test_charge_refund import (
    assert_no_refund_entries,
    balance,
    bearer,
    create_charge,
    create_client,
    deposit,
    internal_headers,
    merchant_charge,
    paid_charge,
    process,
    refund_detail,
    request_payment,
    request_refund,
    send,
    transaction_entries,
)


def test_refund_requests_require_owner_jwt_and_scoped_charge(
    paid_charge,
):
    data = paid_charge
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]
    endpoint = f"/accounts/{account}/charges/{charge_key}/refunds"
    payload = {"idempotency_key": str(uuid4())}

    for headers in (
        {},
        bearer("invalid-token"),
        internal_headers(),
    ):
        response = send(
            "POST",
            endpoint,
            payload=payload,
            headers=headers,
        )
        assert response.response_status == 401

    response = send(
        "POST",
        endpoint,
        payload=payload,
        headers=bearer(data["payer_token"]),
    )
    assert response.response_status == 404

    for wrong_account, wrong_charge in (
        (data["merchant"]["personal"], charge_key),
        (account, str(uuid4())),
    ):
        response = send(
            "POST",
            (
                f"/accounts/{wrong_account}"
                f"/charges/{wrong_charge}/refunds"
            ),
            payload=payload,
            headers=bearer(data["merchant_token"]),
        )
        assert response.response_status == 404

    requested = request_refund(data)
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]
    detail_path = f"{endpoint}/{key}"

    assert send("GET", detail_path).response_status == 401
    assert send(
        "GET",
        detail_path,
        headers=internal_headers(),
    ).response_status == 401
    assert send(
        "GET",
        detail_path,
        headers=bearer(data["payer_token"]),
    ).response_status == 404
    assert send(
        "GET",
        f"{endpoint}/{uuid4()}",
        headers=bearer(data["merchant_token"]),
    ).response_status == 404

    assert merchant_charge(data)["status"] == "PAID"
    assert balance(account, data["merchant_token"]) == "100.00"
    assert balance(
        data["payer"]["personal"], data["payer_token"]
    ) == "0.00"
    assert_no_refund_entries(data, key)


def test_refund_body_cannot_change_amount_or_destination(paid_charge):
    data = paid_charge
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]
    endpoint = f"/accounts/{account}/charges/{charge_key}/refunds"
    key = str(uuid4())

    invalid_payloads = (
        {},
        {"idempotency_key": "not-a-uuid"},
        {"idempotency_key": None},
        {"idempotency_key": key, "amount": "1.00"},
        {
            "idempotency_key": key,
            "destination_account_key": data["merchant"]["personal"],
        },
        {
            "idempotency_key": key,
            "refund_of_transaction_key": str(uuid4()),
        },
    )

    for payload in invalid_payloads:
        response = send(
            "POST",
            endpoint,
            payload=payload,
            headers=bearer(data["merchant_token"]),
        )
        assert response.response_status == 400, response.response_json

    assert merchant_charge(data)["status"] == "PAID"
    assert balance(account, data["merchant_token"]) == "100.00"

    accepted = request_refund(data, key)
    assert accepted.response_status == 202
    assert accepted.response_json["amount"] == "100.00"
    assert (
        accepted.response_json["destination_account_key"]
        == data["payer"]["personal"]
    )
    assert_no_refund_entries(
        data, accepted.response_json["transaction_key"]
    )


@pytest.mark.parametrize(
    "charge_state",
    ("OPEN", "CANCELED", "DEPOSIT_PAID"),
)
def test_unpaid_canceled_or_deposit_charge_cannot_be_refunded(
    charge_state,
):
    merchant, token = create_client()
    account = merchant["professional"]
    charge = create_charge(account, token)
    charge_key = charge["charge_key"]
    expected_balance = "0.00"
    expected_status = charge_state

    if charge_state == "CANCELED":
        canceled = send(
            "POST",
            f"/accounts/{account}/charges/{charge_key}/cancel",
            headers=bearer(token),
        )
        assert canceled.response_status == 200

    elif charge_state == "DEPOSIT_PAID":
        paid = send(
            "POST",
            f"/accounts/{account}/deposits",
            payload={
                "amount": "100.00",
                "external_reference": charge["payment_reference"],
            },
            headers=internal_headers(),
        )
        assert paid.response_status == 201
        expected_balance = "100.00"
        expected_status = "PAID"

    data = {
        "merchant": merchant,
        "merchant_token": token,
        "charge": charge,
    }

    response = request_refund(data)
    assert response.response_status == 409
    assert response.response_json["code"] == "KOD008001"
    assert merchant_charge(data)["status"] == expected_status
    assert balance(account, token) == expected_balance


def test_concurrent_http_retries_create_one_refund(paid_charge):
    data = paid_charge
    key = str(uuid4())
    start = Barrier(2)

    def submit(_):
        start.wait(timeout=10)
        return request_refund(data, key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, range(2)))

    assert all(
        response.response_status == 202
        for response in responses
    )
    keys = {
        response.response_json["transaction_key"]
        for response in responses
    }
    assert len(keys) == 1

    transaction_key = keys.pop()
    assert_no_refund_entries(data, transaction_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(
                process,
                (transaction_key, transaction_key),
            )
        )

    assert statuses == ["COMPLETED", "COMPLETED"]
    assert balance(
        data["merchant"]["professional"],
        data["merchant_token"],
    ) == "0.00"
    assert balance(
        data["payer"]["personal"],
        data["payer_token"],
    ) == "100.00"

    assert transaction_entries(
        data["merchant"]["professional"],
        transaction_key,
        data["merchant_token"],
    ) == {("DEBIT", "-100.00")}

    assert transaction_entries(
        data["payer"]["personal"],
        transaction_key,
        data["payer_token"],
    ) == {("CREDIT", "100.00")}

    repeated = request_refund(data, key)
    assert repeated.response_status == 200
    assert (
        repeated.response_json["transaction_key"]
        == transaction_key
    )


@pytest.mark.parametrize(
    "first_operation",
    ("transfer", "payment", "refund"),
)
def test_refund_idempotency_namespace_is_shared(
    paid_charge,
    first_operation,
):
    data = paid_charge
    source = data["merchant"]["professional"]
    token = data["merchant_token"]
    key = str(uuid4())

    other_charge = create_charge(
        data["payer"]["professional"],
        data["payer_token"],
    )

    def transfer():
        return send(
            "POST",
            f"/accounts/{source}/transfers",
            payload={
                "destination_account_key": data["payer"]["personal"],
                "amount": "100.00",
                "idempotency_key": key,
            },
            headers=bearer(token),
        )

    def payment():
        return request_payment(
            source,
            token,
            other_charge["charge_key"],
            key,
        )

    def refund():
        return request_refund(data, key)

    operations = {
        "transfer": transfer,
        "payment": payment,
        "refund": refund,
    }

    first = operations[first_operation]()
    assert first.response_status == 202

    if first_operation == "refund":
        assert transfer().response_status == 409
        assert payment().response_status == 409
    else:
        assert refund().response_status == 409

    repeated = operations[first_operation]()
    assert repeated.response_status == 202
    assert (
        repeated.response_json["transaction_key"]
        == first.response_json["transaction_key"]
    )
    assert merchant_charge(data)["status"] == "PAID"
    assert balance(source, token) == "100.00"


def test_refund_key_cannot_be_reused_for_another_charge(paid_charge):
    data = paid_charge
    other_charge = create_charge(
        data["merchant"]["professional"],
        data["merchant_token"],
    )

    deposit(data["payer"]["personal"], "100.50")
    paid = request_payment(
        data["payer"]["personal"],
        data["payer_token"],
        other_charge["charge_key"],
    )
    assert paid.response_status == 202
    assert process(
        paid.response_json["transaction_key"]
    ) == "COMPLETED"

    key = str(uuid4())
    first = request_refund(data, key)
    assert first.response_status == 202

    other_data = dict(data, charge=other_charge)
    assert request_refund(other_data, key).response_status == 409

    repeated = request_refund(data, key)
    assert repeated.response_status == 202
    assert (
        repeated.response_json["transaction_key"]
        == first.response_json["transaction_key"]
    )
    assert balance(
        data["merchant"]["professional"],
        data["merchant_token"],
    ) == "200.00"
    assert merchant_charge(data)["status"] == "PAID"
    assert merchant_charge(other_data)["status"] == "PAID"


def test_destination_limit_rejects_refund_without_changing_charge(
    paid_charge,
):
    data = paid_charge
    destination = data["payer"]["personal"]
    deposit(destination, "9999999999999999.99")

    requested = request_refund(data)
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]

    assert process(key) == "REJECTED"
    assert (
        refund_detail(data, key)["rejection_reason"]
        == "DESTINATION_LIMIT_EXCEEDED"
    )
    assert merchant_charge(data)["status"] == "PAID"
    assert merchant_charge(data)["refunded_at"] is None

    assert balance(
        data["merchant"]["professional"],
        data["merchant_token"],
    ) == "100.00"
    assert balance(
        destination,
        data["payer_token"],
    ) == "9999999999999999.99"

    assert_no_refund_entries(data, key)