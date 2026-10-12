from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.client import Account
from models.service_charge import ServiceCharge
from models.transaction import AccountEntry, Transaction
from utils.money import MAX_BALANCE


class TransferProcessor:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _reject(self, transaction, reason: str) -> str:
        transaction.status = "REJECTED"
        transaction.rejection_reason = reason
        self.session.commit()
        return "REJECTED"

    def _refund_problem(self, transaction, source, destination, charge):
        if charge is None:
            raise RuntimeError("Refund has no service charge")

        if charge.status == "REFUNDED":
            return "CHARGE_ALREADY_REFUNDED"

        if charge.status != "PAID":
            return "REFUND_UNAVAILABLE"

        original = self.session.get(
            Transaction,
            transaction.refund_of_transaction_id,
            populate_existing=True,
        )

        if (
            original is None
            or original.kind != "TRANSFER"
            or original.status != "COMPLETED"
            or original.completed_at is None
            or original.service_charge_id != charge.id
            or charge.paid_transaction_id != original.id
            or charge.account_id != source.id
            or original.destination_account_id != source.id
            or original.source_account_id != destination.id
            or source.client_id == destination.client_id
            or original.amount != transaction.amount
            or charge.amount != transaction.amount
            or transaction.fee != Decimal("0.00")
        ):
            raise RuntimeError("Refund does not match its original payment")

        return None

    def process(self, transaction_key: UUID) -> str:
        try:
            transaction = (
                self.session.query(Transaction)
                .filter(
                    Transaction.transaction_key == transaction_key,
                    Transaction.kind.in_(("TRANSFER", "REFUND")),
                )
                .populate_existing()
                .with_for_update()
                .one_or_none()
            )

            if transaction is None:
                raise ValueError("Transaction not found")

            if transaction.status != "PENDING":
                current_status = transaction.status
                self.session.rollback()
                return current_status

            # Todas as operações bloqueiam contas na mesma ordem.
            account_ids = sorted(
                (
                    transaction.source_account_id,
                    transaction.destination_account_id,
                )
            )
            accounts = {}

            for account_id in account_ids:
                accounts[account_id] = (
                    self.session.query(Account)
                    .filter(Account.id == account_id)
                    .populate_existing()
                    .with_for_update()
                    .one()
                )

            source = accounts[transaction.source_account_id]
            destination = accounts[transaction.destination_account_id]

            charge = None
            if transaction.service_charge_id is not None:
                charge = (
                    self.session.query(ServiceCharge)
                    .filter(ServiceCharge.id == transaction.service_charge_id)
                    .populate_existing()
                    .with_for_update()
                    .one()
                )

            if transaction.kind == "REFUND":
                problem = self._refund_problem(
                    transaction, source, destination, charge
                )
                if problem is not None:
                    return self._reject(transaction, problem)

            elif charge is not None:
                if (
                    charge.account_id != destination.id
                    or charge.amount != transaction.amount
                ):
                    raise RuntimeError(
                        "Charge payment does not match its transfer"
                    )

                if charge.status in ("PAID", "REFUNDED"):
                    return self._reject(transaction, "CHARGE_ALREADY_PAID")

                if charge.status == "CANCELED":
                    return self._reject(transaction, "CHARGE_CANCELED")

                if charge.status != "OPEN":
                    raise RuntimeError("Unexpected service charge status")

            total_debit = transaction.amount + transaction.fee
            if source.balance < total_debit:
                return self._reject(transaction, "INSUFFICIENT_FUNDS")

            destination_balance = destination.balance + transaction.amount
            if destination_balance > MAX_BALANCE:
                return self._reject(transaction, "DESTINATION_LIMIT_EXCEEDED")

            balance_after_debit = source.balance - transaction.amount
            source_balance = balance_after_debit - transaction.fee

            entries = [
                AccountEntry(
                    entry_key=uuid4(),
                    transaction_id=transaction.id,
                    account_id=source.id,
                    kind="DEBIT",
                    amount=-transaction.amount,
                    balance_after=balance_after_debit,
                ),
                AccountEntry(
                    entry_key=uuid4(),
                    transaction_id=transaction.id,
                    account_id=destination.id,
                    kind="CREDIT",
                    amount=transaction.amount,
                    balance_after=destination_balance,
                ),
            ]

            if transaction.fee > 0:
                entries.append(
                    AccountEntry(
                        entry_key=uuid4(),
                        transaction_id=transaction.id,
                        account_id=source.id,
                        kind="FEE",
                        amount=-transaction.fee,
                        balance_after=source_balance,
                    )
                )

            source.balance = source_balance
            destination.balance = destination_balance
            self.session.add_all(entries)

            transaction.status = "COMPLETED"
            transaction.completed_at = func.now()

            if charge is not None:
                if transaction.kind == "REFUND":
                    # O pagamento original permanece intacto.
                    charge.status = "REFUNDED"
                    charge.refunded_transaction_id = transaction.id
                    charge.refunded_at = func.now()
                else:
                    charge.status = "PAID"
                    charge.paid_transaction_id = transaction.id
                    charge.paid_at = func.now()

            # Saldos, lançamentos e estados são confirmados juntos.
            self.session.commit()
            return "COMPLETED"

        except Exception:
            self.session.rollback()
            raise