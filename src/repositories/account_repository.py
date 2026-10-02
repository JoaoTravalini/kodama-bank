from uuid import UUID

from database import Context
from models.client import Account

from models.transaction import AccountEntry, Transaction

class AccountRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def list_for_client(self, client_id: int) -> list[Account]:
        return (
            self.session.query(Account)
            .filter(Account.client_id == client_id)
            .order_by(Account.type.asc())
            .all()
        )

    def get_for_client(
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
        
    def list_entries(
        self,
        account_id: int,
        page: int,
        limit: int,
        kind: str | None,
    ):
        query = (
            self.session.query(AccountEntry, Transaction)
            .join(Transaction, Transaction.id == AccountEntry.transaction_id)
            .filter(AccountEntry.account_id == account_id)
        )

        if kind is not None:
            query = query.filter(AccountEntry.kind == kind)

        return (
            query.order_by(AccountEntry.id.desc())
            .offset((page - 1) * limit)
            .limit(limit + 1)
            .all()
        )