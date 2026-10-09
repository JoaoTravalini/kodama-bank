from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.charge_payment_errors import ChargeAlreadyPaid, OwnChargePayment
from errors.service_charge_errors import ServiceChargeNotFound
from errors.transfer_errors import TransferIdempotencyConflict
from models.transaction import Transaction
from repositories.transfer_repository import TransferRepository
from utils.transfer_fee import calculate_transfer_fee


class ChargePaymentController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = TransferRepository(self.context)

    @staticmethod
    def _response(transaction, source, destination, charge) -> dict:
        return {
            "charge_key": str(charge.charge_key),
            "transaction_key": str(transaction.transaction_key),
            "source_account_key": str(source.account_key),
            "destination_account_key": str(destination.account_key),
            "status": transaction.status,
            "amount": format(transaction.amount, ".2f"),
            "fee": format(transaction.fee, ".2f"),
            "rejection_reason": transaction.rejection_reason,
        }

    def _repeat_or_conflict(
        self, existing, source, destination, charge
    ) -> dict:
        if (
            existing.service_charge_id != charge.id
            or existing.destination_account_id != destination.id
            or existing.amount != charge.amount
        ):
            raise TransferIdempotencyConflict()

        return self._response(existing, source, destination, charge)

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

        charge_key = UUID(payload["charge_key"])
        idempotency_key = UUID(payload["idempotency_key"])

        charge = self.repository.get_charge_by_key(charge_key)
        if charge is None:
            raise ServiceChargeNotFound()

        destination = self.repository.get_account_by_id(charge.account_id)
        if destination is None:
            raise ServiceChargeNotFound()

        # Uma repetição legítima recupera a operação anterior, inclusive
        # se o worker já a concluiu ou rejeitou.
        existing = self.repository.get_by_idempotency_key(
            source.id, idempotency_key
        )
        if existing is not None:
            return self._repeat_or_conflict(
                existing, source, destination, charge
            )

        if source.client_id == destination.client_id:
            raise OwnChargePayment()

        if charge.status != "OPEN":
            raise ChargeAlreadyPaid()

        fee = calculate_transfer_fee(
            charge.amount,
            source.client_id,
            destination.client_id,
        )

        transaction = Transaction(
            transaction_key=uuid4(),
            kind="TRANSFER",
            status="PENDING",
            amount=charge.amount,
            fee=fee,
            source_account_id=source.id,
            destination_account_id=destination.id,
            service_charge_id=charge.id,
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

            # Duas requisições podem chegar com a mesma chave ao mesmo tempo.
            if constraint == "transactions_source_idempotency_unique":
                existing = self.repository.get_by_idempotency_key(
                    source.id, idempotency_key
                )
                if existing is not None:
                    return self._repeat_or_conflict(
                        existing, source, destination, charge
                    )

            raise

        return self._response(transaction, source, destination, charge)