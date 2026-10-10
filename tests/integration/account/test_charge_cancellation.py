from concurrent.futures import ThreadPoolExecutor
from os import environ

from tests.integration.account.test_charge_payment import (
    balance,
    bearer,
    charge_detail,
    create_charge,
    create_client,
    deposit,
    process,
    request_payment,
    send,
    transaction_entries,
    transfer_detail,
)


def cancel(account_key, charge_key, token):
    return send(
        "POST",
        f"/accounts/{account_key}/charges/{charge_key}/cancel",
        headers=bearer(token),
    )


def test_cancel_open_charge_keeps_history_but_removes_receivable():
    merchant, token = create_client()
    account = merchant["professional"]
    charge = create_charge(account, token)

    before = send(
        "GET",
        f"/accounts/{account}/charges/summary",
        headers=bearer(token),
    )
    assert before.response_json["open"]["amount"] == "100.00"

    canceled = cancel(account, charge["charge_key"], token)
    assert canceled.response_status == 200
    assert canceled.response_json["status"] == "CANCELED"
    assert canceled.response_json["canceled_at"] is not None
    assert canceled.response_json["paid_at"] is None
    assert canceled.response_json["overdue"] is False

    repeated = cancel(account, charge["charge_key"], token)
    assert repeated.response_status == 200
    assert repeated.response_json == canceled.response_json
    assert charge_detail(
        account, charge["charge_key"], token
    ) == canceled.response_json

    summary = send(
        "GET",
        f"/accounts/{account}/charges/summary",
        headers=bearer(token),
    )
    assert summary.response_json["open"]["amount"] == "0.00"
    assert summary.response_json["paid"]["amount"] == "0.00"
    assert balance(account, token) == "0.00"

    endpoint = (
        f"/accounts/{account}/charges/"
        f"{charge['charge_key']}/cancel"
    )
    assert send("POST", endpoint).response_status == 401

    other, other_token = create_client()
    assert cancel(
        account, charge["charge_key"], other_token
    ).response_status == 404
    assert cancel(
        other["professional"], charge["charge_key"], other_token
    ).response_status == 404


def test_paid_charge_cannot_be_canceled():
    merchant, token = create_client()
    account = merchant["professional"]
    charge = create_charge(account, token)

    payment = send(
        "POST",
        f"/accounts/{account}/deposits",
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
    assert payment.response_status == 201

    refused = cancel(account, charge["charge_key"], token)
    assert refused.response_status == 409
    assert refused.response_json["code"] == "KOD006006"
    assert charge_detail(
        account, charge["charge_key"], token
    )["status"] == "PAID"
    assert balance(account, token) == "100.00"


def test_canceled_charge_cannot_receive_a_new_payment():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    account = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(account, merchant_token)
    deposit(source, "100.50")

    assert cancel(
        account, charge["charge_key"], merchant_token
    ).response_status == 200

    payment = request_payment(
        source, payer_token, charge["charge_key"]
    )
    assert payment.response_status == 409
    assert payment.response_json["code"] == "KOD007003"

    internal = send(
        "POST",
        f"/accounts/{account}/deposits",
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
    assert internal.response_status == 409
    assert balance(source, payer_token) == "100.50"
    assert balance(account, merchant_token) == "0.00"


def test_pending_payment_is_rejected_after_cancellation():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    account = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(account, merchant_token)
    deposit(source, "100.50")

    pending = request_payment(
        source, payer_token, charge["charge_key"]
    )
    assert pending.response_status == 202
    key = pending.response_json["transaction_key"]

    assert cancel(
        account, charge["charge_key"], merchant_token
    ).response_status == 200
    assert process(key) == "REJECTED"
    assert transfer_detail(
        source, key, payer_token
    )["rejection_reason"] == "CHARGE_CANCELED"
    assert transaction_entries(source, key, payer_token) == set()
    assert balance(source, payer_token) == "100.50"
    assert balance(account, merchant_token) == "0.00"


def test_payment_and_cancellation_race_has_only_one_winner():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    account = merchant["professional"]
    source = payer["personal"]
    charge = create_charge(account, merchant_token)
    deposit(source, "100.50")

    pending = request_payment(
        source, payer_token, charge["charge_key"]
    )
    assert pending.response_status == 202
    key = pending.response_json["transaction_key"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancel_future = pool.submit(
            cancel, account, charge["charge_key"], merchant_token
        )
        process_future = pool.submit(process, key)
        canceled = cancel_future.result()
        processed = process_future.result()

    if processed == "COMPLETED":
        assert canceled.response_status == 409
        assert charge_detail(
            account, charge["charge_key"], merchant_token
        )["status"] == "PAID"
        assert balance(source, payer_token) == "0.00"
        assert balance(account, merchant_token) == "100.00"
    else:
        assert processed == "REJECTED"
        assert canceled.response_status == 200
        assert transfer_detail(
            source, key, payer_token
        )["rejection_reason"] == "CHARGE_CANCELED"
        assert charge_detail(
            account, charge["charge_key"], merchant_token
        )["status"] == "CANCELED"
        assert transaction_entries(source, key, payer_token) == set()
        assert balance(source, payer_token) == "100.50"
        assert balance(account, merchant_token) == "0.00"