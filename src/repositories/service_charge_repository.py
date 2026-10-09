from uuid import UUID

from database import Context
from models.client import Account
from models.service_charge import ServiceCharge


class ServiceChargeRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_owned_account(
        self,
        client_id: int,
        account_key: UUID,
    ) -> Account | None:
        return (
            self.session.query(Account)
            .filter(
                Account.client_id == client_id,
                Account.account_key == account_key,
            )
            .first()
        )

    def get_by_key(
        self,
        account_id: int,
        charge_key: UUID,
    ) -> ServiceCharge | None:
        return (
            self.session.query(ServiceCharge)
            .filter(
                ServiceCharge.account_id == account_id,
                ServiceCharge.charge_key == charge_key,
            )
            .first()
        )

    def list_for_account(
        self,
        account_id: int,
        page: int,
        limit: int,
    ) -> list[ServiceCharge]:
        return (
            self.session.query(ServiceCharge)
            .filter(ServiceCharge.account_id == account_id)
            .order_by(ServiceCharge.id.desc())
            .offset((page - 1) * limit)
            .limit(limit + 1)
            .all()
        )