from datetime import date
from uuid import UUID

from sqlalchemy import and_, func

from database import Context
from models.client import Account
from models.service_charge import ServiceCharge
from models.transaction import AccountEntry, Transaction


class ServiceChargeRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def business_date(self) -> date:
        return self.session.query(
            func.date(
                func.timezone("America/Sao_Paulo", func.now())
            )
        ).scalar()

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

    def get_payment_record(self, charge: ServiceCharge):
        return (
            self.session.query(Transaction, AccountEntry)
            .outerjoin(
                AccountEntry,
                and_(
                    AccountEntry.transaction_id == Transaction.id,
                    AccountEntry.account_id == charge.account_id,
                    AccountEntry.kind == "CREDIT",
                ),
            )
            .filter(Transaction.id == charge.paid_transaction_id)
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

    def summary_for_account(self, account_id: int, today: date):
        open_charge = ServiceCharge.status == "OPEN"
        paid_charge = ServiceCharge.status == "PAID"
        overdue_charge = and_(
            open_charge,
            ServiceCharge.due_date < today,
        )

        return (
            self.session.query(
                func.count(ServiceCharge.id)
                .filter(open_charge)
                .label("open_count"),
                func.coalesce(
                    func.sum(ServiceCharge.amount).filter(open_charge),
                    0,
                ).label("open_amount"),
                func.count(ServiceCharge.id)
                .filter(overdue_charge)
                .label("overdue_count"),
                func.coalesce(
                    func.sum(ServiceCharge.amount).filter(overdue_charge),
                    0,
                ).label("overdue_amount"),
                func.count(ServiceCharge.id)
                .filter(paid_charge)
                .label("paid_count"),
                func.coalesce(
                    func.sum(ServiceCharge.amount).filter(paid_charge),
                    0,
                ).label("paid_amount"),
            )
            .filter(ServiceCharge.account_id == account_id)
            .one()
        )