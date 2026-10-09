from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, text

from database import Context
from models.client import Account
from models.service_charge import ServiceCharge
from models.transaction import AccountEntry, Transaction


class ReconciliationRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def begin_snapshot(self) -> None:
        # Precisa ser o primeiro comando SQL desta sessão.
        self.session.execute(
            text(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, "
                "READ ONLY"
            )
        )

    def get_account(self, account_key: UUID) -> Account | None:
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .first()
        )

    def ledger_balance(self, account_id: int) -> Decimal:
        return (
            self.session.query(
                func.coalesce(
                    func.sum(AccountEntry.amount),
                    Decimal("0.00"),
                )
            )
            .filter(AccountEntry.account_id == account_id)
            .scalar()
        )

    def paid_charge_records(self, account_id: int):
        return (
            self.session.query(
                ServiceCharge,
                Transaction,
                AccountEntry,
            )
            .outerjoin(
                Transaction,
                Transaction.id == ServiceCharge.paid_transaction_id,
            )
            .outerjoin(
                AccountEntry,
                and_(
                    AccountEntry.transaction_id == Transaction.id,
                    AccountEntry.account_id == ServiceCharge.account_id,
                    AccountEntry.kind == "CREDIT",
                ),
            )
            .filter(
                ServiceCharge.account_id == account_id,
                ServiceCharge.status == "PAID",
            )
            .order_by(ServiceCharge.id)
            .all()
        )