from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

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

from tests.integration.account.test_reconciliation import (
    internal_headers,
    reconcile,
    temporary_change,
)

@pytest.fixture
def paid_charge():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    account = merchant["professional"]
    charge = create_charge(account, merchant_token)

    deposit(payer["personal"], "100.50")
    payment = request_payment(
        payer["personal"], payer_token, charge["charge_key"]
    )
    assert payment.response_status == 202
    assert process(payment.response_json["transaction_key"]) == "COMPLETED"

    return {
        "merchant": merchant,
        "merchant_token": merchant_token,
        "payer": payer,
        "payer_token": payer_token,
        "charge": charge,
        "payment": payment.response_json,
    }


def request_refund(data, key=None):
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]
    return send(
        "POST",
        f"/accounts/{account}/charges/{charge_key}/refunds",
        payload={"idempotency_key": key or str(uuid4())},
        headers=bearer(data["merchant_token"]),
    )


def refund_detail(data, transaction_key):
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]
    response = send(
        "GET",
        f"/accounts/{account}/charges/{charge_key}/refunds/{transaction_key}",
        headers=bearer(data["merchant_token"]),
    )
    assert response.response_status == 200
    return response.response_json


def merchant_charge(data):
    return charge_detail(
        data["merchant"]["professional"],
        data["charge"]["charge_key"],
        data["merchant_token"],
    )


def assert_no_refund_entries(data, key):
    assert transaction_entries(
        data["merchant"]["professional"], key, data["merchant_token"]
    ) == set()
    assert transaction_entries(
        data["payer"]["personal"], key, data["payer_token"]
    ) == set()


def test_refund_completes_once_and_preserves_original_payment(paid_charge):
    data = paid_charge
    idempotency_key = str(uuid4())
    requested = request_refund(data, idempotency_key)
    assert requested.response_status == 202
    refund = requested.response_json
    key = refund["transaction_key"]

    assert refund["kind"] == "REFUND"
    assert refund["amount"] == "100.00"
    assert refund["fee"] == "0.00"
    assert refund["original_fee_retained"] == "0.50"
    assert refund["refund_of_transaction_key"] == data["payment"]["transaction_key"]
    assert merchant_charge(data)["status"] == "PAID"
    assert balance(data["merchant"]["professional"], data["merchant_token"]) == "100.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "0.00"
    assert_no_refund_entries(data, key)

    repeated = request_refund(data, idempotency_key)
    assert repeated.response_status == 202
    assert repeated.response_json["transaction_key"] == key
    assert process(key) == "COMPLETED"
    assert process(key) == "COMPLETED"

    assert merchant_charge(data)["status"] == "REFUNDED"
    assert balance(data["merchant"]["professional"], data["merchant_token"]) == "0.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "100.00"
    assert transaction_entries(
        data["merchant"]["professional"], key, data["merchant_token"]
    ) == {("DEBIT", "-100.00")}
    assert transaction_entries(
        data["payer"]["personal"], key, data["payer_token"]
    ) == {("CREDIT", "100.00")}

    original = transfer_detail(
        data["payer"]["personal"],
        data["payment"]["transaction_key"],
        data["payer_token"],
    )
    assert original["status"] == "COMPLETED"
    assert original["fee"] == "0.50"
    assert transaction_entries(
        data["payer"]["personal"],
        data["payment"]["transaction_key"],
        data["payer_token"],
    ) == {("DEBIT", "-100.00"), ("FEE", "-0.50")}

    repeated = request_refund(data, idempotency_key)
    assert repeated.response_status == 200
    assert repeated.response_json["transaction_key"] == key
    assert repeated.response_json["status"] == "COMPLETED"
    assert refund_detail(data, key)["completed_at"] is not None
    assert request_refund(data).response_status == 409


def test_concurrent_refunds_cannot_return_the_money_twice(paid_charge):
    data = paid_charge
    requests = [request_refund(data), request_refund(data)]
    assert all(response.response_status == 202 for response in requests)
    keys = [response.response_json["transaction_key"] for response in requests]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(process, keys))

    assert sorted(statuses) == ["COMPLETED", "REJECTED"]
    losing_key = keys[statuses.index("REJECTED")]
    assert refund_detail(data, losing_key)["rejection_reason"] == "CHARGE_ALREADY_REFUNDED"
    assert_no_refund_entries(data, losing_key)
    assert balance(data["merchant"]["professional"], data["merchant_token"]) == "0.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "100.00"


def test_insufficient_funds_keeps_charge_paid_and_allows_new_attempt(paid_charge):
    data = paid_charge
    source = data["merchant"]["professional"]
    spend = send(
        "POST",
        f"/accounts/{source}/transfers",
        payload={
            "destination_account_key": data["merchant"]["personal"],
            "amount": "100.00",
            "idempotency_key": str(uuid4()),
        },
        headers=bearer(data["merchant_token"]),
    )
    assert spend.response_status == 202
    assert process(spend.response_json["transaction_key"]) == "COMPLETED"

    first_key = str(uuid4())
    first = request_refund(data, first_key)
    assert first.response_status == 202
    transaction_key = first.response_json["transaction_key"]
    assert process(transaction_key) == "REJECTED"
    assert refund_detail(data, transaction_key)["rejection_reason"] == "INSUFFICIENT_FUNDS"
    assert merchant_charge(data)["status"] == "PAID"
    assert balance(source, data["merchant_token"]) == "0.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "0.00"
    assert_no_refund_entries(data, transaction_key)

    deposit(source, "100.00")
    second = request_refund(data)
    assert second.response_status == 202
    assert second.response_json["transaction_key"] != transaction_key
    assert process(second.response_json["transaction_key"]) == "COMPLETED"
    assert merchant_charge(data)["status"] == "REFUNDED"
    assert balance(source, data["merchant_token"]) == "0.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "100.00"

    repeated = request_refund(data, first_key)
    assert repeated.response_status == 200
    assert repeated.response_json["status"] == "REJECTED"
    assert repeated.response_json["transaction_key"] == transaction_key


def test_refund_failure_rolls_back_and_can_be_retried(paid_charge, monkeypatch):
    data = paid_charge
    requested = request_refund(data)
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]

    def fail_commit(self):
        raise RuntimeError("simulated refund failure")

    with monkeypatch.context() as patcher:
        patcher.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="simulated refund failure"):
            process(key)

    assert refund_detail(data, key)["status"] == "PENDING"
    assert merchant_charge(data)["status"] == "PAID"
    assert balance(data["merchant"]["professional"], data["merchant_token"]) == "100.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "0.00"
    assert_no_refund_entries(data, key)

    assert process(key) == "COMPLETED"
    assert merchant_charge(data)["status"] == "REFUNDED"
    assert balance(data["merchant"]["professional"], data["merchant_token"]) == "0.00"
    assert balance(data["payer"]["personal"], data["payer_token"]) == "100.00"


def test_pending_payment_cannot_pay_a_refunded_charge_again():
    merchant, merchant_token = create_client()
    payer, payer_token = create_client()
    other_payer, other_token = create_client()
    charge = create_charge(merchant["professional"], merchant_token)
    deposit(payer["personal"], "100.50")
    deposit(other_payer["personal"], "100.50")

    first = request_payment(payer["personal"], payer_token, charge["charge_key"])
    second = request_payment(other_payer["personal"], other_token, charge["charge_key"])
    assert first.response_status == second.response_status == 202
    assert process(first.response_json["transaction_key"]) == "COMPLETED"

    data = {
        "merchant": merchant,
        "merchant_token": merchant_token,
        "payer": payer,
        "payer_token": payer_token,
        "charge": charge,
    }
    refund = request_refund(data)
    assert refund.response_status == 202
    assert process(refund.response_json["transaction_key"]) == "COMPLETED"

    key = second.response_json["transaction_key"]
    assert process(key) == "REJECTED"
    assert transfer_detail(other_payer["personal"], key, other_token)["rejection_reason"] == "CHARGE_ALREADY_PAID"
    assert merchant_charge(data)["status"] == "REFUNDED"
    assert balance(merchant["professional"], merchant_token) == "0.00"
    assert balance(payer["personal"], payer_token) == "100.00"
    assert balance(other_payer["personal"], other_token) == "100.50"
    assert transaction_entries(other_payer["personal"], key, other_token) == set()

def charge_summary(data):
    account = data["merchant"]["professional"]
    response = send(
        "GET",
        f"/accounts/{account}/charges/summary",
        headers=bearer(data["merchant_token"]),
    )
    assert response.response_status == 200
    return response.response_json


def original_receipt(data):
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]
    response = send(
        "GET",
        f"/accounts/{account}/charges/{charge_key}/receipt",
        headers=bearer(data["merchant_token"]),
    )
    assert response.response_status == 200
    return response.response_json


def test_refund_updates_reporting_and_keeps_original_receipt(paid_charge):
    data = paid_charge
    receipt_before = original_receipt(data)
    before = charge_summary(data)

    assert before["paid"] == {"count": 1, "amount": "100.00"}
    assert before["refunded"] == {"count": 0, "amount": "0.00"}
    assert merchant_charge(data)["refunded_at"] is None

    requested = request_refund(data)
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]

    pending = charge_summary(data)
    assert pending["paid"] == before["paid"]
    assert pending["refunded"] == before["refunded"]
    assert original_receipt(data) == receipt_before

    assert process(key) == "COMPLETED"

    after = charge_summary(data)
    assert after["paid"] == {"count": 0, "amount": "0.00"}
    assert after["refunded"] == {"count": 1, "amount": "100.00"}
    assert after["open"] == {"count": 0, "amount": "0.00"}
    assert after["overdue"] == {"count": 0, "amount": "0.00"}

    charge = merchant_charge(data)
    assert charge["refunded_at"] == refund_detail(data, key)["completed_at"]
    assert original_receipt(data) == receipt_before

    for account in (
        data["merchant"]["professional"],
        data["payer"]["personal"],
    ):
        result = reconcile(account, internal_headers())
        assert result.response_status == 200

        body = result.response_json
        assert body["consistent"] is True
        assert body["issues"] == []
        assert body["balance"] == body["ledger_balance"]
        assert body["refunded_charges_checked"] == 1

    account = data["merchant"]["professional"]
    result = reconcile(account, internal_headers())
    assert result.response_json["paid_charges_checked"] == 1

    charge_key = data["charge"]["charge_key"]
    canceled = send(
        "POST",
        f"/accounts/{account}/charges/{charge_key}/cancel",
        headers=bearer(data["merchant_token"]),
    )
    assert canceled.response_status == 409
    assert merchant_charge(data)["status"] == "REFUNDED"


@pytest.mark.parametrize("changed_payment", ("refund", "original"))
def test_reconciliation_detects_corrupted_refund_history(
    paid_charge,
    changed_payment,
):
    data = paid_charge
    requested = request_refund(data)
    assert requested.response_status == 202

    key = requested.response_json["transaction_key"]
    assert process(key) == "COMPLETED"

    changed_key = (
        key
        if changed_payment == "refund"
        else data["payment"]["transaction_key"]
    )
    account = data["merchant"]["professional"]

    with temporary_change(
        "UPDATE account_entries SET amount = 99.00 "
        "WHERE kind = 'CREDIT' AND transaction_id = "
        "(SELECT id FROM transactions "
        "WHERE transaction_key = CAST(:key AS UUID))",
        "UPDATE account_entries SET amount = 100.00 "
        "WHERE kind = 'CREDIT' AND transaction_id = "
        "(SELECT id FROM transactions "
        "WHERE transaction_key = CAST(:key AS UUID))",
        {"key": changed_key},
    ):
        result = reconcile(account, internal_headers())
        assert result.response_status == 200
        assert result.response_json["consistent"] is False

        codes = {
            issue["code"]
            for issue in result.response_json["issues"]
        }
        expected = (
            {"CHARGE_REFUND_ENTRIES_MISMATCH"}
            if changed_payment == "refund"
            else {"BALANCE_MISMATCH", "CHARGE_CREDIT_MISMATCH"}
        )
        assert codes == expected

    restored = reconcile(account, internal_headers())
    assert restored.response_status == 200
    assert restored.response_json["consistent"] is True
    assert restored.response_json["issues"] == []

def refund_receipt(data, transaction_key, headers=None):
    account = data["merchant"]["professional"]
    charge_key = data["charge"]["charge_key"]

    return send(
        "GET",
        (
            f"/accounts/{account}/charges/{charge_key}"
            f"/refunds/{transaction_key}/receipt"
        ),
        headers=(
            bearer(data["merchant_token"])
            if headers is None
            else headers
        ),
    )


def test_refund_receipt_requires_completed_refund_and_is_stable(
    paid_charge,
):
    data = paid_charge
    requested = request_refund(data)
    assert requested.response_status == 202

    key = requested.response_json["transaction_key"]
    pending = refund_receipt(data, key)
    assert pending.response_status == 409
    assert pending.response_json["code"] == "KOD008004"

    assert process(key) == "COMPLETED"

    first = refund_receipt(data, key)
    repeated = refund_receipt(data, key)

    assert first.response_status == repeated.response_status == 200
    assert first.response_json == repeated.response_json
    assert first.response.headers["Cache-Control"] == "no-store"

    proof = first.response_json
    assert proof["transaction_key"] == key
    assert (
        proof["refund_of_transaction_key"]
        == data["payment"]["transaction_key"]
    )
    assert proof["charge_key"] == data["charge"]["charge_key"]
    assert (
        proof["source_account_key"]
        == data["merchant"]["professional"]
    )
    assert (
        proof["destination_account_key"]
        == data["payer"]["personal"]
    )
    assert proof["amount_refunded"] == "100.00"
    assert proof["fee"] == "0.00"
    assert proof["original_fee_retained"] == "0.50"
    assert proof["balance_after_debit"] == "0.00"
    assert proof["balance_after_credit"] == "100.00"
    assert (
        proof["refunded_at"]
        == refund_detail(data, key)["completed_at"]
    )
    assert "idempotency_key" not in proof

    for account, token, field, kind in (
        (
            data["merchant"]["professional"],
            data["merchant_token"],
            "debit_entry_key",
            "DEBIT",
        ),
        (
            data["payer"]["personal"],
            data["payer_token"],
            "credit_entry_key",
            "CREDIT",
        ),
    ):
        statement = send(
            "GET",
            f"/accounts/{account}/entries",
            headers=bearer(token),
        )
        assert statement.response_status == 200

        matching = [
            entry
            for entry in statement.response_json["entries"]
            if entry["transaction_key"] == key
            and entry["kind"] == kind
        ]
        assert len(matching) == 1
        assert proof[field] == matching[0]["entry_key"]


def test_refund_receipt_requires_owner_jwt(paid_charge):
    data = paid_charge
    requested = request_refund(data)
    assert requested.response_status == 202

    key = requested.response_json["transaction_key"]
    assert process(key) == "COMPLETED"

    assert refund_receipt(data, key, {}).response_status == 401
    assert refund_receipt(
        data, key, bearer("invalid-token")
    ).response_status == 401
    assert refund_receipt(
        data, key, internal_headers()
    ).response_status == 401
    assert refund_receipt(
        data, key, bearer(data["payer_token"])
    ).response_status == 404
    assert refund_receipt(
        data, str(uuid4())
    ).response_status == 404

    account = data["merchant"]["professional"]
    wrong_charge = send(
        "GET",
        (
            f"/accounts/{account}/charges/{uuid4()}"
            f"/refunds/{key}/receipt"
        ),
        headers=bearer(data["merchant_token"]),
    )
    assert wrong_charge.response_status == 404
    assert refund_receipt(data, key).response_status == 200


def test_rejected_refund_has_no_receipt(paid_charge):
    data = paid_charge
    account = data["merchant"]["professional"]

    spent = send(
        "POST",
        f"/accounts/{account}/transfers",
        payload={
            "destination_account_key": data["merchant"]["personal"],
            "amount": "100.00",
            "idempotency_key": str(uuid4()),
        },
        headers=bearer(data["merchant_token"]),
    )
    assert spent.response_status == 202
    assert process(
        spent.response_json["transaction_key"]
    ) == "COMPLETED"

    requested = request_refund(data)
    assert requested.response_status == 202
    key = requested.response_json["transaction_key"]

    assert process(key) == "REJECTED"

    response = refund_receipt(data, key)
    assert response.response_status == 409
    assert response.response_json["code"] == "KOD008004"
    assert merchant_charge(data)["status"] == "PAID"
    assert_no_refund_entries(data, key)


@pytest.mark.parametrize(
    "kind, changed_amount",
    (("DEBIT", "-99.00"), ("CREDIT", "99.00")),
)
def test_refund_receipt_rejects_corrupted_entries(
    paid_charge,
    kind,
    changed_amount,
):
    data = paid_charge
    requested = request_refund(data)
    assert requested.response_status == 202

    key = requested.response_json["transaction_key"]
    assert process(key) == "COMPLETED"

    valid = refund_receipt(data, key)
    assert valid.response_status == 200

    original_amount = "-100.00" if kind == "DEBIT" else "100.00"

    with temporary_change(
        "UPDATE account_entries SET amount = :changed_amount "
        "WHERE kind = :kind AND transaction_id = "
        "(SELECT id FROM transactions "
        "WHERE transaction_key = CAST(:key AS UUID))",
        "UPDATE account_entries SET amount = :original_amount "
        "WHERE kind = :kind AND transaction_id = "
        "(SELECT id FROM transactions "
        "WHERE transaction_key = CAST(:key AS UUID))",
        {
            "key": key,
            "kind": kind,
            "changed_amount": changed_amount,
            "original_amount": original_amount,
        },
    ):
        response = refund_receipt(data, key)
        assert response.response_status == 500
        assert response.response_json["code"] == "QIT000500"

    restored = refund_receipt(data, key)
    assert restored.response_status == 200
    assert restored.response_json == valid.response_json