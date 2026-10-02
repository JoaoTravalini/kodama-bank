from uuid import UUID

from database import Context
from models.client import Account
from models.transaction import Transaction


class TransferRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_owned_account(
        self, client_id: int, account_key: UUID
    ) -> Account | None:
        return (
            self.session.query(Account)
            .filter(
                Account.client_id == client_id,
                Account.account_key == account_key,
            )
            .first()
        )

    def get_account_by_key(self, account_key: UUID) -> Account | None:
        return (
            self.session.query(Account)
            .filter(Account.account_key == account_key)
            .first()
        )

    def get_account_by_id(self, account_id: int) -> Account | None:
        return self.session.get(Account, account_id)

    def get_by_idempotency_key(
        self, source_account_id: int, idempotency_key: UUID
    ) -> Transaction | None:
        return (
            self.session.query(Transaction)
            .filter(
                Transaction.kind == "TRANSFER",
                Transaction.source_account_id == source_account_id,
                Transaction.idempotency_key == idempotency_key,
            )
            .first()
        )

    def get_by_key_for_source(
        self, transaction_key: UUID, source_account_id: int
    ) -> Transaction | None:
        return (
            self.session.query(Transaction)
            .filter(
                Transaction.kind == "TRANSFER",
                Transaction.transaction_key == transaction_key,
                Transaction.source_account_id == source_account_id,
            )
            .first()
        )