from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import aliased

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
            self.session.query(ServiceCharge, Transaction, AccountEntry)
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
                ServiceCharge.status.in_(("PAID", "REFUNDED")),
            )
            .order_by(ServiceCharge.id)
            .all()
        )

    def refunded_charge_records(self, account_id: int):
        original = aliased(Transaction, name="original_payment")
        refund = aliased(Transaction, name="completed_refund")
        debit = aliased(AccountEntry, name="refund_debit")
        credit = aliased(AccountEntry, name="refund_credit")

        counts = (
            self.session.query(
                AccountEntry.transaction_id.label("transaction_id"),
                func.count(AccountEntry.id).label("entry_count"),
            )
            .group_by(AccountEntry.transaction_id)
            .subquery()
        )

        return (
            self.session.query(
                ServiceCharge,
                original,
                refund,
                debit,
                credit,
                counts.c.entry_count,
            )
            .select_from(ServiceCharge)
            .outerjoin(
                original,
                original.id == ServiceCharge.paid_transaction_id,
            )
            .outerjoin(
                refund,
                refund.id == ServiceCharge.refunded_transaction_id,
            )
            .outerjoin(
                debit,
                and_(
                    debit.transaction_id == refund.id,
                    debit.account_id == ServiceCharge.account_id,
                    debit.kind == "DEBIT",
                ),
            )
            .outerjoin(
                credit,
                and_(
                    credit.transaction_id == refund.id,
                    credit.account_id == original.source_account_id,
                    credit.kind == "CREDIT",
                ),
            )
            .outerjoin(
                counts,
                counts.c.transaction_id == refund.id,
            )
            .filter(
                ServiceCharge.status == "REFUNDED",
                or_(
                    ServiceCharge.account_id == account_id,
                    original.source_account_id == account_id,
                ),
            )
            .order_by(ServiceCharge.id)
            .all()
        )