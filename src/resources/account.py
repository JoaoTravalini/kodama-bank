from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.account_controller import AccountController


class AccountResource:
    def on_get_list(self, request: Request) -> JSONResponse:
        result = AccountController().list_accounts(
            request.headers.get("Authorization")
        )
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)

    def on_get_by_key(
        self,
        request: Request,
        account_key: UUID,
    ) -> JSONResponse:
        result = AccountController().get_account(
            request.headers.get("Authorization"),
            account_key,
        )
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)