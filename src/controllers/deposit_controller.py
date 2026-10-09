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
from errors.service_charge_errors import ServiceChargePaymentConflict
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

    def _charge_for_reference(
        self,
        external_reference: str,
        account_id: int,
        amount: Decimal,
    ):
        if not external_reference.startswith("charge:"):
            return None

        try:
            charge_key = UUID(external_reference[len("charge:"):])
        except ValueError:
            raise ServiceChargePaymentConflict() from None

        charge = self.repository.get_charge_for_update(charge_key)

        if (
            charge is None
            or charge.account_id != account_id
            or charge.amount != amount
        ):
            raise ServiceChargePaymentConflict()

        return charge

    @staticmethod
    def _check_repeated_charge_payment(charge, existing: Transaction) -> None:
        if charge is not None and (
            charge.status != "PAID"
            or charge.paid_transaction_id != existing.id
        ):
            raise ServiceChargePaymentConflict()

    def create(self, account_key: UUID, payload: dict) -> dict:
        amount = Decimal(payload["amount"])
        external_reference = payload["external_reference"]

        if amount <= 0:
            raise InvalidDepositAmount()

        account = self.repository.get_account_for_update(account_key)
        if account is None:
            raise AccountNotFound()

        account_id = account.id
        charge = self._charge_for_reference(
            external_reference,
            account_id,
            amount,
        )

        existing = self.repository.get_by_external_reference(
            external_reference
        )
        if existing is not None:
            self._check_repeated_charge_payment(charge, existing)
            return self._repeat_or_conflict(
                existing,
                account_id,
                account_key,
                amount,
            )

        if charge is not None and charge.status != "OPEN":
            raise ServiceChargePaymentConflict()

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

            if charge is not None:
                charge.status = "PAID"
                charge.paid_transaction_id = transaction.id
                charge.paid_at = func.now()

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

            if constraint == "transactions_external_reference_key":
                existing = self.repository.get_by_external_reference(
                    external_reference
                )
                if existing is not None:
                    charge = self._charge_for_reference(
                        external_reference,
                        account_id,
                        amount,
                    )
                    self._check_repeated_charge_payment(charge, existing)
                    return self._repeat_or_conflict(
                        existing,
                        account_id,
                        account_key,
                        amount,
                    )

            raise