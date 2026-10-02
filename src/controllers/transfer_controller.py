from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.transfer_errors import (
    InvalidTransferAmount,
    SameAccountTransfer,
    TransferIdempotencyConflict,
    TransferNotFound,
)
from models.transaction import Transaction
from repositories.transfer_repository import TransferRepository
from utils.transfer_fee import calculate_transfer_fee


class TransferController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = TransferRepository(self.context)

    @staticmethod
    def _response(
        transaction: Transaction,
        source_account_key: UUID,
        destination_account_key: UUID,
    ) -> dict:
        return {
            "transaction_key": str(transaction.transaction_key),
            "source_account_key": str(source_account_key),
            "destination_account_key": str(destination_account_key),
            "status": transaction.status,
            "amount": format(transaction.amount, ".2f"),
            "fee": format(transaction.fee, ".2f"),
            "rejection_reason": transaction.rejection_reason,
        }

    def _repeat_or_conflict(
        self,
        existing: Transaction,
        source_account_key: UUID,
        destination_account_key: UUID,
        amount: Decimal,
    ) -> dict:
        saved_destination = self.repository.get_account_by_id(
            existing.destination_account_id
        )

        if (
            saved_destination is None
            or saved_destination.account_key != destination_account_key
            or existing.amount != amount
        ):
            raise TransferIdempotencyConflict()

        return self._response(
            existing,
            source_account_key,
            saved_destination.account_key,
        )

    def create(
        self,
        authorization: str | None,
        source_account_key: UUID,
        payload: dict,
    ) -> dict:
        client = AuthController().authenticate(authorization)

        source = self.repository.get_owned_account(
            client.id, source_account_key
        )
        if source is None:
            raise AccountNotFound()

        amount = Decimal(payload["amount"])
        if amount <= 0:
            raise InvalidTransferAmount()

        destination_account_key = UUID(payload["destination_account_key"])
        idempotency_key = UUID(payload["idempotency_key"])
        source_account_id = source.id

        existing = self.repository.get_by_idempotency_key(
            source_account_id, idempotency_key
        )
        if existing is not None:
            return self._repeat_or_conflict(
                existing,
                source_account_key,
                destination_account_key,
                amount,
            )

        destination = self.repository.get_account_by_key(
            destination_account_key
        )
        if destination is None:
            raise AccountNotFound()

        if destination.id == source_account_id:
            raise SameAccountTransfer()

        fee = calculate_transfer_fee(
            amount,
            source.client_id,
            destination.client_id,
        )

        transaction = Transaction(
            transaction_key=uuid4(),
            kind="TRANSFER",
            status="PENDING",
            amount=amount,
            fee=fee,
            source_account_id=source_account_id,
            destination_account_id=destination.id,
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
                getattr(exc.orig, "diag", None),
                "constraint_name",
                None,
            )

            # Outra requisição pode ter gravado a mesma chave primeiro.
            if constraint == "transactions_source_idempotency_unique":
                existing = self.repository.get_by_idempotency_key(
                    source_account_id, idempotency_key
                )
                if existing is not None:
                    return self._repeat_or_conflict(
                        existing,
                        source_account_key,
                        destination_account_key,
                        amount,
                    )

            raise

        return self._response(
            transaction,
            source_account_key,
            destination_account_key,
        )

    def get(
        self,
        authorization: str | None,
        source_account_key: UUID,
        transaction_key: UUID,
    ) -> dict:
        client = AuthController().authenticate(authorization)

        source = self.repository.get_owned_account(
            client.id, source_account_key
        )
        if source is None:
            raise AccountNotFound()

        transaction = self.repository.get_by_key_for_source(
            transaction_key, source.id
        )
        if transaction is None:
            raise TransferNotFound()

        destination = self.repository.get_account_by_id(
            transaction.destination_account_id
        )
        if destination is None:
            raise TransferNotFound()

        return self._response(
            transaction,
            source_account_key,
            destination.account_key,
        )