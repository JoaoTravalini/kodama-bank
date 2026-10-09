from decimal import Decimal
from uuid import UUID, uuid4

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from errors.service_charge_errors import (
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
    def _response(charge: ServiceCharge) -> dict:
        return {
            "charge_key": str(charge.charge_key),
            "description": charge.description,
            "amount": format(charge.amount, ".2f"),
            "status": charge.status,
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

        charge = ServiceCharge(
            charge_key=uuid4(),
            account_id=account.id,
            description=payload["description"].strip(),
            amount=amount,
            status="OPEN",
        )

        self.session.add(charge)
        self.session.flush()
        response = self._response(charge)
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
        rows = self.repository.list_for_account(account.id, page, limit)

        return {
            "account_key": str(account.account_key),
            "page": page,
            "limit": limit,
            "has_more": len(rows) > limit,
            "charges": [self._response(charge) for charge in rows[:limit]],
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

        return self._response(charge)