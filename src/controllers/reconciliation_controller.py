from uuid import UUID

from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from repositories.reconciliation_repository import ReconciliationRepository


class ReconciliationController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = ReconciliationRepository(self.context)

    def get(self, account_key: UUID) -> dict:
        # Nenhuma consulta ao banco pode acontecer antes desta linha.
        self.repository.begin_snapshot()

        account = self.repository.get_account(account_key)
        if account is None:
            raise AccountNotFound()

        ledger_balance = self.repository.ledger_balance(account.id)
        issues = []

        if account.balance != ledger_balance:
            issues.append({
                "code": "BALANCE_MISMATCH",
                "balance": format(account.balance, ".2f"),
                "ledger_balance": format(ledger_balance, ".2f"),
            })

        paid_records = self.repository.paid_charge_records(account.id)

        for charge, transaction, entry in paid_records:
            valid_payment = (
                transaction is not None
                and transaction.status == "COMPLETED"
                and transaction.completed_at is not None
                and charge.paid_at is not None
                and transaction.destination_account_id == account.id
                and transaction.amount == charge.amount
                and (
                    (
                        transaction.kind == "DEPOSIT"
                        and transaction.external_reference
                        == f"charge:{charge.charge_key}"
                        and transaction.service_charge_id is None
                    )
                    or (
                        transaction.kind == "TRANSFER"
                        and transaction.service_charge_id == charge.id
                        and transaction.source_account_id is not None
                    )
                )
            )

            if not valid_payment:
                issues.append({
                    "code": "CHARGE_TRANSACTION_MISMATCH",
                    "charge_key": str(charge.charge_key),
                })
                continue

            if entry is None or entry.amount != charge.amount:
                issues.append({
                    "code": "CHARGE_CREDIT_MISMATCH",
                    "charge_key": str(charge.charge_key),
                    "transaction_key": str(transaction.transaction_key),
                })

        refunded_records = self.repository.refunded_charge_records(
            account.id
        )

        for charge, original, refund, debit, credit, count in refunded_records:
            valid_refund = (
                original is not None
                and original.kind == "TRANSFER"
                and original.status == "COMPLETED"
                and original.completed_at is not None
                and original.service_charge_id == charge.id
                and original.destination_account_id == charge.account_id
                and original.source_account_id is not None
                and original.source_account_id != charge.account_id
                and original.amount == charge.amount
                and charge.paid_at is not None
                and refund is not None
                and refund.kind == "REFUND"
                and refund.status == "COMPLETED"
                and refund.completed_at is not None
                and refund.refund_of_transaction_id == original.id
                and refund.service_charge_id == charge.id
                and refund.source_account_id == charge.account_id
                and refund.destination_account_id
                == original.source_account_id
                and refund.amount == charge.amount
                and refund.fee == 0
                and charge.refunded_at == refund.completed_at
            )

            if not valid_refund:
                issues.append({
                    "code": "CHARGE_REFUND_TRANSACTION_MISMATCH",
                    "charge_key": str(charge.charge_key),
                })
                continue

            if (
                count != 2
                or debit is None
                or debit.amount != -charge.amount
                or credit is None
                or credit.amount != charge.amount
            ):
                issues.append({
                    "code": "CHARGE_REFUND_ENTRIES_MISMATCH",
                    "charge_key": str(charge.charge_key),
                    "transaction_key": str(refund.transaction_key),
                })

        return {
            "account_key": str(account.account_key),
            "balance": format(account.balance, ".2f"),
            "ledger_balance": format(ledger_balance, ".2f"),
            "paid_charges_checked": len(paid_records),
            "refunded_charges_checked": len(refunded_records),
            "consistent": len(issues) == 0,
            "issues": issues,
        }