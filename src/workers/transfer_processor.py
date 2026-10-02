from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.client import Account
from models.transaction import AccountEntry, Transaction
from utils.money import MAX_BALANCE


class TransferProcessor:
    def __init__(self, session: Session) -> None:
        self.session = session

    def process(self, transaction_key: UUID) -> str:
        try:
            # O bloqueio impede dois trabalhadores de processarem
            # simultaneamente a mesma transferência.
            transaction = (
                self.session.query(Transaction)
                .filter(
                    Transaction.transaction_key == transaction_key,
                    Transaction.kind == "TRANSFER",
                )
                .with_for_update()
                .one_or_none()
            )
            if transaction is None:
                raise ValueError("Transfer not found")

            if transaction.status != "PENDING":
                current_status = transaction.status
                self.session.rollback()
                return current_status

            # Todas as transferências bloqueiam contas na mesma ordem.
            # Isso evita que A -> B e B -> A fiquem esperando uma pela outra.
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
                    .with_for_update()
                    .one()
                )

            source = accounts[transaction.source_account_id]
            destination = accounts[transaction.destination_account_id]
            total_debit = transaction.amount + transaction.fee

            if source.balance < total_debit:
                transaction.status = "REJECTED"
                transaction.rejection_reason = "INSUFFICIENT_FUNDS"
                self.session.commit()
                return "REJECTED"

            destination_balance = destination.balance + transaction.amount
            if destination_balance > MAX_BALANCE:
                transaction.status = "REJECTED"
                transaction.rejection_reason = "DESTINATION_LIMIT_EXCEEDED"
                self.session.commit()
                return "REJECTED"

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

            # Tarifa zero não gera lançamento FEE: o banco exige
            # que um lançamento desse tipo tenha valor negativo.
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

            # Saldo, lançamentos e status tornam-se definitivos juntos.
            self.session.commit()
            return "COMPLETED"

        except Exception:
            self.session.rollback()
            raise