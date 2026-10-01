from uuid import UUID

from fastapi import status
from fastapi.responses import JSONResponse

from controllers.deposit_controller import DepositController
from utils.schema_handler import SchemaHandler


class DepositResource:
    @SchemaHandler.validate("post_deposit.json")
    def on_post(
        self,
        account_key: UUID,
        payload: dict,
    ) -> JSONResponse:
        result = DepositController().create(account_key, payload)
        return JSONResponse(
            content=result,
            status_code=status.HTTP_201_CREATED,
        )