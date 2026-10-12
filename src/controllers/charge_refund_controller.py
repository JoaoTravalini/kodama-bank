from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.base_error import InternalError
from errors.charge_refund_errors import (
    ChargeAlreadyRefunded,
    ChargeRefundNotFound,
    ChargeRefundReceiptUnavailable,
    RefundUnavailable,
)
from errors.service_charge_errors import ServiceChargeNotFound
from errors.transfer_errors import TransferIdempotencyConflict
from models.transaction import Transaction
from repositories.charge_refund_repository import ChargeRefundRepository


class ChargeRefundController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = ChargeRefundRepository(self.context)

    def _owned_charge(self, authorization, account_key, charge_key):
        client = AuthController().authenticate(authorization)
        source = self.repository.get_owned_account(client.id, account_key)
        if source is None:
            raise AccountNotFound()

        charge = self.repository.get_owned_charge(source.id, charge_key)
        if charge is None:
            raise ServiceChargeNotFound()

        return source, charge

    def _payment(self, source, charge):
        if charge.paid_transaction_id is None:
            raise RefundUnavailable()

        original = self.repository.get_transaction_by_id(
            charge.paid_transaction_id
        )
        if original is None:
            raise InternalError()
        if original.kind == "DEPOSIT":
            raise RefundUnavailable()

        if (
            original.kind != "TRANSFER"
            or original.status != "COMPLETED"
            or original.service_charge_id != charge.id
            or original.destination_account_id != source.id
            or original.source_account_id is None
            or original.amount != charge.amount
        ):
            raise InternalError()

        destination = self.repository.get_account_by_id(
            original.source_account_id
        )
        if (
            destination is None
            or destination.client_id == source.client_id
        ):
            raise InternalError()

        return original, destination

    @staticmethod
    def _matches(transaction, source, destination, charge, original):
        return (
            transaction.kind == "REFUND"
            and transaction.source_account_id == source.id
            and transaction.destination_account_id == destination.id
            and transaction.service_charge_id == charge.id
            and transaction.refund_of_transaction_id == original.id
            and transaction.amount == original.amount
            and transaction.fee == Decimal("0.00")
        )

    @staticmethod
    def _response(transaction, source, destination, charge, original):
        return {
            "transaction_key": str(transaction.transaction_key),
            "refund_of_transaction_key": str(original.transaction_key),
            "charge_key": str(charge.charge_key),
            "source_account_key": str(source.account_key),
            "destination_account_key": str(destination.account_key),
            "kind": transaction.kind,
            "status": transaction.status,
            "amount": format(transaction.amount, ".2f"),
            "fee": format(transaction.fee, ".2f"),
            "original_fee_retained": format(original.fee, ".2f"),
            "rejection_reason": transaction.rejection_reason,
            "created_at": transaction.created_at.isoformat(),
            "completed_at": (
                transaction.completed_at.isoformat()
                if transaction.completed_at is not None
                else None
            ),
        }

    def _repeat_or_conflict(self, existing, source, charge):
        if existing.kind != "REFUND" or existing.service_charge_id != charge.id:
            raise TransferIdempotencyConflict()

        original, destination = self._payment(source, charge)
        if not self._matches(existing, source, destination, charge, original):
            raise TransferIdempotencyConflict()

        return self._response(existing, source, destination, charge, original)

    def create(
        self,
        authorization: str | None,
        account_key: UUID,
        charge_key: UUID,
        payload: dict,
    ) -> dict:
        source, charge = self._owned_charge(
            authorization, account_key, charge_key
        )
        idempotency_key = UUID(payload["idempotency_key"])
        source_id = source.id

        existing = self.repository.get_by_idempotency_key(
            source_id, idempotency_key
        )
        if existing is not None:
            return self._repeat_or_conflict(existing, source, charge)

        if charge.status == "REFUNDED":
            raise ChargeAlreadyRefunded()
        if charge.status != "PAID":
            raise RefundUnavailable()

        original, destination = self._payment(source, charge)
        transaction = Transaction(
            transaction_key=uuid4(),
            kind="REFUND",
            status="PENDING",
            amount=original.amount,
            fee=Decimal("0.00"),
            source_account_id=source.id,
            destination_account_id=destination.id,
            service_charge_id=charge.id,
            refund_of_transaction_id=original.id,
            idempotency_key=idempotency_key,
            external_reference=None,
            completed_at=None,
        )

        try:
            self.session.add(transaction)
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            constraint = getattr(
                getattr(exc.orig, "diag", None), "constraint_name", None
            )
            if constraint == "transactions_source_idempotency_unique":
                existing = self.repository.get_by_idempotency_key(
                    source_id, idempotency_key
                )
                if existing is not None:
                    return self._repeat_or_conflict(existing, source, charge)
            raise

        return self._response(transaction, source, destination, charge, original)

    def get(
        self,
        authorization: str | None,
        account_key: UUID,
        charge_key: UUID,
        transaction_key: UUID,
    ) -> dict:
        source, charge = self._owned_charge(
            authorization, account_key, charge_key
        )
        transaction = self.repository.get_for_charge(
            source.id, charge.id, transaction_key
        )
        if transaction is None:
            raise ChargeRefundNotFound()

        original, destination = self._payment(source, charge)
        if not self._matches(transaction, source, destination, charge, original):
            raise InternalError()

        return self._response(transaction, source, destination, charge, original)

    def receipt(
        self,
        authorization: str | None,
        account_key: UUID,
        charge_key: UUID,
        transaction_key: UUID,
    ) -> dict:
        source, charge = self._owned_charge(
            authorization, account_key, charge_key
        )
        transaction = self.repository.get_for_charge(
            source.id, charge.id, transaction_key
        )

        if transaction is None:
            raise ChargeRefundNotFound()

        if transaction.status != "COMPLETED":
            raise ChargeRefundReceiptUnavailable()

        # O worker pode ter concluído entre as consultas anteriores.
        self.session.refresh(charge)

        original, destination = self._payment(source, charge)

        if (
            not self._matches(
                transaction, source, destination, charge, original
            )
            or original.completed_at is None
            or charge.paid_at is None
            or transaction.completed_at is None
            or charge.status != "REFUNDED"
            or charge.refunded_transaction_id != transaction.id
            or charge.refunded_at != transaction.completed_at
        ):
            raise InternalError()

        entries = self.repository.get_entries(transaction.id)

        debit = next(
            (
                entry
                for entry in entries
                if entry.kind == "DEBIT"
                and entry.account_id == source.id
            ),
            None,
        )
        credit = next(
            (
                entry
                for entry in entries
                if entry.kind == "CREDIT"
                and entry.account_id == destination.id
            ),
            None,
        )

        if (
            len(entries) != 2
            or debit is None
            or debit.amount != -transaction.amount
            or credit is None
            or credit.amount != transaction.amount
        ):
            raise InternalError()

        return {
            "charge_key": str(charge.charge_key),
            "transaction_key": str(transaction.transaction_key),
            "refund_of_transaction_key": str(original.transaction_key),
            "source_account_key": str(source.account_key),
            "destination_account_key": str(destination.account_key),
            "description": charge.description,
            "amount_refunded": format(transaction.amount, ".2f"),
            "fee": format(transaction.fee, ".2f"),
            "original_fee_retained": format(original.fee, ".2f"),
            "debit_entry_key": str(debit.entry_key),
            "credit_entry_key": str(credit.entry_key),
            "balance_after_debit": format(debit.balance_after, ".2f"),
            "balance_after_credit": format(credit.balance_after, ".2f"),
            "refunded_at": charge.refunded_at.isoformat(),
        }