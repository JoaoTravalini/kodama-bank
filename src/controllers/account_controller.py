from uuid import UUID

from controllers.auth_controller import AuthController
from controllers.base_controller import BaseController
from errors.account_errors import AccountNotFound
from models.client import Account
from repositories.account_repository import AccountRepository


class AccountController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = AccountRepository(self.context)

    @staticmethod
    def _to_response(account: Account) -> dict:
        return {
            "account_key": str(account.account_key),
            "type": account.type,
            "balance": format(account.balance, ".2f"),
        }

    def list_accounts(self, authorization: str | None) -> dict:
        client = AuthController().authenticate(authorization)
        accounts = self.repository.list_for_client(client.id)

        return {
            "accounts": [self._to_response(account) for account in accounts]
        }

    def get_account(
        self,
        authorization: str | None,
        account_key: UUID,
    ) -> dict:
        client = AuthController().authenticate(authorization)
        account = self.repository.get_for_client(client.id, account_key)

        if account is None:
            raise AccountNotFound()

        return self._to_response(account)
    
    def list_entries(
        self,
        authorization: str | None,
        account_key: UUID,
        page: int,
        limit: int,
        kind: str | None,
    ) -> dict:
        client = AuthController().authenticate(authorization)
        account = self.repository.get_for_client(client.id, account_key)

        if account is None:
            raise AccountNotFound()

        rows = self.repository.list_entries(account.id, page, limit, kind)
        has_more = len(rows) > limit

        entries = []
        for entry, transaction in rows[:limit]:
            entries.append(
                {
                    "entry_key": str(entry.entry_key),
                    "transaction_key": str(transaction.transaction_key),
                    "transaction_kind": transaction.kind,
                    "kind": entry.kind,
                    "amount": format(entry.amount, ".2f"),
                    "balance_after": format(entry.balance_after, ".2f"),
                    "created_at": entry.created_at.isoformat(),
                }
            )

        return {
            "account_key": str(account.account_key),
            "page": page,
            "limit": limit,
            "has_more": has_more,
            "entries": entries,
        }