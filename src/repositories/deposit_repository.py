from uuid import UUID

from database import Context
from models.client import Account
from models.transaction import AccountEntry, Transaction


class DepositRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_account_for_update(self, account_key: UUID) -> Account | None:
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .with_for_update()
            .first()
        )

    def get_by_external_reference(
        self,
        external_reference: str,
    ) -> Transaction | None:
        return (
            self.session.query(Transaction)
            .filter(Transaction.external_reference == external_reference)
            .first()
        )

    def get_credit_entry(self, transaction_id: int) -> AccountEntry | None:
        return (
            self.session.query(AccountEntry)
            .filter(
                AccountEntry.transaction_id == transaction_id,
                AccountEntry.kind == "CREDIT",
            )
            .first()
        )