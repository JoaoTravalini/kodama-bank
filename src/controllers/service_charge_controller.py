from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.base_error import InternalError, InvalidSchema
from errors.service_charge_errors import (
    ChargeReceiptUnavailable,
    InvalidChargeAmount,
    ProfessionalAccountRequired,
    ServiceChargeNotFound,
)
from models.service_charge import ServiceCharge
from repositories.service_charge_repository import ServiceChargeRepository


class ServiceChargeController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = ServiceChargeRepository(self.context)

    @staticmethod
    def _response(charge: ServiceCharge, today: date) -> dict:
        overdue = (
            charge.status == "OPEN"
            and charge.due_date is not None
            and charge.due_date < today
        )

        return {
            "charge_key": str(charge.charge_key),
            "description": charge.description,
            "amount": format(charge.amount, ".2f"),
            "status": charge.status,
            "due_date": (
                charge.due_date.isoformat()
                if charge.due_date is not None
                else None
            ),
            "overdue": overdue,
            "payment_reference": f"charge:{charge.charge_key}",
            "created_at": charge.created_at.isoformat(),
            "paid_at": (
                charge.paid_at.isoformat()
                if charge.paid_at is not None
                else None
            ),
        }

    def _owned_account(self, authorization: str | None, account_key: UUID):
        client = AuthController().authenticate(authorization)
        account = self.repository.get_owned_account(client.id, account_key)

        if account is None:
            raise AccountNotFound()

        return account

    def create(
        self,
        authorization: str | None,
        account_key: UUID,
        payload: dict,
    ) -> dict:
        account = self._owned_account(authorization, account_key)

        if account.type != "professional":
            raise ProfessionalAccountRequired()

        amount = Decimal(payload["amount"])
        if amount <= 0:
            raise InvalidChargeAmount()

        due_date = None
        if "due_date" in payload:
            try:
                due_date = date.fromisoformat(payload["due_date"])
            except ValueError:
                raise InvalidSchema(
                    "due_date must be a valid date in YYYY-MM-DD format"
                ) from None

        today = self.repository.business_date()

        charge = ServiceCharge(
            charge_key=uuid4(),
            account_id=account.id,
            description=payload["description"].strip(),
            amount=amount,
            due_date=due_date,
            status="OPEN",
        )

        self.session.add(charge)
        self.session.flush()
        response = self._response(charge, today)
        self.session.commit()
        return response

    def list_charges(
        self,
        authorization: str | None,
        account_key: UUID,
        page: int,
        limit: int,
    ) -> dict:
        account = self._owned_account(authorization, account_key)
        today = self.repository.business_date()
        rows = self.repository.list_for_account(account.id, page, limit)

        return {
            "account_key": str(account.account_key),
            "page": page,
            "limit": limit,
            "has_more": len(rows) > limit,
            "charges": [
                self._response(charge, today)
                for charge in rows[:limit]
            ],
        }

    def get(
        self,
        authorization: str | None,
        account_key: UUID,
        charge_key: UUID,
    ) -> dict:
        account = self._owned_account(authorization, account_key)
        charge = self.repository.get_by_key(account.id, charge_key)

        if charge is None:
            raise ServiceChargeNotFound()

        today = self.repository.business_date()
        return self._response(charge, today)

    def receipt(
        self,
        authorization: str | None,
        account_key: UUID,
        charge_key: UUID,
    ) -> dict:
        account = self._owned_account(authorization, account_key)
        charge = self.repository.get_by_key(account.id, charge_key)
        if charge is None:
            raise ServiceChargeNotFound()
        if charge.status != "PAID":
            raise ChargeReceiptUnavailable()

        record = self.repository.get_payment_record(charge)
        if record is None:
            raise InternalError()

        transaction, credit = record
        valid_payment = (
            transaction.status == "COMPLETED"
            and transaction.destination_account_id == account.id
            and transaction.amount == charge.amount
            and transaction.completed_at is not None
            and charge.paid_at is not None
            and credit is not None
            and credit.amount == charge.amount
            and (
                (
                    transaction.kind == "DEPOSIT"
                    and transaction.external_reference == f"charge:{charge.charge_key}"
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
            raise InternalError()

        return {
            "charge_key": str(charge.charge_key),
            "transaction_key": str(transaction.transaction_key),
            "credit_entry_key": str(credit.entry_key),
            "account_key": str(account.account_key),
            "description": charge.description,
            "amount_received": format(credit.amount, ".2f"),
            "balance_after_credit": format(credit.balance_after, ".2f"),
            "paid_at": charge.paid_at.isoformat(),
            "payment_method": (
                "KODAMA_TRANSFER"
                if transaction.kind == "TRANSFER"
                else "SIMULATED_INTERNAL_DEPOSIT"
            ),
        }

    def summary(
        self,
        authorization: str | None,
        account_key: UUID,
    ) -> dict:
        account = self._owned_account(authorization, account_key)

        if account.type != "professional":
            raise ProfessionalAccountRequired()

        today = self.repository.business_date()
        totals = self.repository.summary_for_account(account.id, today)

        return {
            "account_key": str(account.account_key),
            "as_of_date": today.isoformat(),
            "open": {
                "count": totals.open_count,
                "amount": format(totals.open_amount, ".2f"),
            },
            "overdue": {
                "count": totals.overdue_count,
                "amount": format(totals.overdue_amount, ".2f"),
            },
            "paid": {
                "count": totals.paid_count,
                "amount": format(totals.paid_amount, ".2f"),
            },
        }