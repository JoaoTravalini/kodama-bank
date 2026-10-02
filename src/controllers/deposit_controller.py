from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.deposit_errors import (
    AccountBalanceLimitExceeded,
    DepositReferenceConflict,
    InvalidDepositAmount,
)
from models.transaction import AccountEntry, Transaction
from repositories.deposit_repository import DepositRepository

from utils.money import MAX_BALANCE


class DepositController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = DepositRepository(self.context)

    @staticmethod
    def _response(
        transaction: Transaction,
        account_key: UUID,
        entry: AccountEntry,
    ) -> dict:
        return {
            "transaction_key": str(transaction.transaction_key),
            "account_key": str(account_key),
            "status": transaction.status,
            "amount": format(transaction.amount, ".2f"),
            "balance_after": format(entry.balance_after, ".2f"),
            "external_reference": transaction.external_reference,
        }

    def _repeat_or_conflict(
        self,
        existing: Transaction,
        account_id: int,
        account_key: UUID,
        amount: Decimal,
    ) -> dict:
        if (
            existing.destination_account_id != account_id
            or existing.amount != amount
        ):
            raise DepositReferenceConflict()

        entry = self.repository.get_credit_entry(existing.id)
        if entry is None:
            raise RuntimeError("Completed deposit without a credit entry")

        return self._response(existing, account_key, entry)

    def create(self, account_key: UUID, payload: dict) -> dict:
        amount = Decimal(payload["amount"])
        external_reference = payload["external_reference"]

        if amount <= 0:
            raise InvalidDepositAmount()

        account = self.repository.get_account_for_update(account_key)
        if account is None:
            raise AccountNotFound()

        account_id = account.id

        existing = self.repository.get_by_external_reference(external_reference)
        if existing is not None:
            return self._repeat_or_conflict(
                existing,
                account_id,
                account_key,
                amount,
            )

        new_balance = account.balance + amount
        if new_balance > MAX_BALANCE:
            raise AccountBalanceLimitExceeded()

        transaction = Transaction(
            transaction_key=uuid4(),
            kind="DEPOSIT",
            status="COMPLETED",
            amount=amount,
            fee=Decimal("0.00"),
            source_account_id=None,
            destination_account_id=account_id,
            idempotency_key=None,
            external_reference=external_reference,
            completed_at=func.now(),
        )

        try:
            self.session.add(transaction)
            self.session.flush()

            account.balance = new_balance

            entry = AccountEntry(
                entry_key=uuid4(),
                transaction_id=transaction.id,
                account_id=account_id,
                kind="CREDIT",
                amount=amount,
                balance_after=new_balance,
            )
            self.session.add(entry)

            response = self._response(transaction, account_key, entry)
            self.session.commit()
            return response

        except IntegrityError as exc:
            self.session.rollback()

            constraint = getattr(
                getattr(exc.orig, "diag", None),
                "constraint_name",
                None,
            )

            # Duas requisições podem usar a mesma referência ao mesmo tempo,
            # inclusive apontando para contas diferentes. O UNIQUE no banco
            # decide qual entrou; esta consulta interpreta o resultado.
            if constraint == "transactions_external_reference_key":
                existing = self.repository.get_by_external_reference(
                    external_reference
                )
                if existing is not None:
                    return self._repeat_or_conflict(
                        existing,
                        account_id,
                        account_key,
                        amount,
                    )

            raise