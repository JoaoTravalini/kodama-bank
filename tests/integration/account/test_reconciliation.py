from contextlib import contextmanager
from os import environ
from uuid import uuid4

from sqlalchemy import create_engine, text

from tests.utils.db_utils import DbUtils
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


def internal_headers():
    return {
        "INTERNAL-TOKEN": environ.get("INTERNAL_TOKEN", "default_token")
    }


def create_client():
    email = f"conciliacao.{uuid4().hex}@example.com"

    created = send(
        "POST",
        "/clients",
        payload={
            "name": "Cliente da Conciliação",
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


def create_and_pay_charge(account_key, jwt):
    charge = send(
        "POST",
        f"/accounts/{account_key}/charges",
        payload={
            "description": "Serviço de teste",
            "amount": "120.00",
        },
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert charge.response_status == 201

    payment = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": "120.00",
            "external_reference": charge.response_json[
                "payment_reference"
            ],
        },
        headers=internal_headers(),
    )
    assert payment.response_status == 201
    return charge.response_json, payment.response_json


def reconcile(account_key, headers=None):
    return send(
        "GET",
        f"/internal/accounts/{account_key}/reconciliation",
        headers=headers,
    )


@contextmanager
def temporary_change(update_sql, restore_sql, params):
    """Altera uma linha de teste e sempre tenta restaurá-la."""
    engine = create_engine(DbUtils.database_url())
    changed = False

    try:
        with engine.begin() as connection:
            result = connection.execute(text(update_sql), params)
            assert result.rowcount == 1

        changed = True
        yield
    finally:
        try:
            if changed:
                with engine.begin() as connection:
                    result = connection.execute(
                        text(restore_sql),
                        params,
                    )
                    assert result.rowcount == 1
        finally:
            engine.dispose()


def test_reconciliation_requires_internal_token():
    accounts, jwt = create_client()
    account_key = accounts["professional"]

    assert reconcile(account_key).response_status == 403

    assert reconcile(
        account_key,
        headers={"INTERNAL-TOKEN": "token-incorreto"},
    ).response_status == 403

    assert reconcile(
        account_key,
        headers={"Authorization": f"Bearer {jwt}"},
    ).response_status == 403

    empty = reconcile(account_key, internal_headers())
    assert empty.response_status == 200
    assert empty.response_json["balance"] == "0.00"
    assert empty.response_json["ledger_balance"] == "0.00"
    assert empty.response_json["paid_charges_checked"] == 0
    assert empty.response_json["consistent"] is True
    assert empty.response_json["issues"] == []

    unknown = reconcile(str(uuid4()), internal_headers())
    assert unknown.response_status == 404


def test_paid_charge_and_other_deposit_reconcile():
    accounts, jwt = create_client()
    account_key = accounts["professional"]

    create_and_pay_charge(account_key, jwt)

    other_deposit = send(
        "POST",
        f"/accounts/{account_key}/deposits",
        payload={
            "amount": "10.00",
            "external_reference": f"outro-pagamento-{uuid4().hex}",
        },
        headers=internal_headers(),
    )
    assert other_deposit.response_status == 201

    result = reconcile(account_key, internal_headers())
    assert result.response_status == 200
    assert result.response_json["account_key"] == account_key
    assert result.response_json["balance"] == "130.00"
    assert result.response_json["ledger_balance"] == "130.00"
    assert result.response_json["paid_charges_checked"] == 1
    assert result.response_json["consistent"] is True
    assert result.response_json["issues"] == []


def test_reconciliation_detects_real_database_divergences():
    accounts, jwt = create_client()
    account_key = accounts["professional"]
    charge, payment = create_and_pay_charge(account_key, jwt)

    statement = send(
        "GET",
        f"/accounts/{account_key}/entries",
        headers={"Authorization": f"Bearer {jwt}"},
    )
    assert statement.response_status == 200
    entries = statement.response_json["entries"]
    assert len(entries) == 1
    entry_key = entries[0]["entry_key"]

    assert reconcile(
        account_key,
        internal_headers(),
    ).response_json["consistent"] is True

    with temporary_change(
        (
            "UPDATE accounts SET balance = 121.00 "
            "WHERE account_key = CAST(:key AS UUID)"
        ),
        (
            "UPDATE accounts SET balance = 120.00 "
            "WHERE account_key = CAST(:key AS UUID)"
        ),
        {"key": account_key},
    ):
        result = reconcile(account_key, internal_headers())
        assert result.response_status == 200
        assert result.response_json["consistent"] is False
        assert {
            issue["code"] for issue in result.response_json["issues"]
        } == {"BALANCE_MISMATCH"}

    with temporary_change(
        (
            "UPDATE account_entries SET amount = 119.00 "
            "WHERE entry_key = CAST(:key AS UUID)"
        ),
        (
            "UPDATE account_entries SET amount = 120.00 "
            "WHERE entry_key = CAST(:key AS UUID)"
        ),
        {"key": entry_key},
    ):
        result = reconcile(account_key, internal_headers())
        assert result.response_status == 200
        assert result.response_json["consistent"] is False
        assert {
            issue["code"] for issue in result.response_json["issues"]
        } == {
            "BALANCE_MISMATCH",
            "CHARGE_CREDIT_MISMATCH",
        }

    with temporary_change(
        (
            "UPDATE transactions SET amount = 119.00 "
            "WHERE transaction_key = CAST(:key AS UUID)"
        ),
        (
            "UPDATE transactions SET amount = 120.00 "
            "WHERE transaction_key = CAST(:key AS UUID)"
        ),
        {"key": payment["transaction_key"]},
    ):
        result = reconcile(account_key, internal_headers())
        assert result.response_status == 200
        assert result.response_json["consistent"] is False
        assert {
            issue["code"] for issue in result.response_json["issues"]
        } == {"CHARGE_TRANSACTION_MISMATCH"}
        assert result.response_json["issues"][0]["charge_key"] == (
            charge["charge_key"]
        )

    restored = reconcile(account_key, internal_headers())
    assert restored.response_status == 200
    assert restored.response_json["consistent"] is True
    assert restored.response_json["issues"] == []