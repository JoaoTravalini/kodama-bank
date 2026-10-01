from uuid import UUID

from database import Context
from models.client import Account


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