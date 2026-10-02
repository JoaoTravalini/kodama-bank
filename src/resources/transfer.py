from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.transfer_controller import TransferController
from utils.schema_handler import SchemaHandler


class TransferResource:
    @SchemaHandler.validate("post_transfer.json")
    def on_post(
        self,
        request: Request,
        source_account_key: UUID,
        payload: dict,
    ) -> JSONResponse:
        result = TransferController().create(
            request.headers.get("Authorization"),
            source_account_key,
            payload,
        )

        response_status = (
            status.HTTP_202_ACCEPTED
            if result["status"] == "PENDING"
            else status.HTTP_200_OK
        )
        return JSONResponse(content=result, status_code=response_status)

    def on_get(
        self,
        request: Request,
        source_account_key: UUID,
        transaction_key: UUID,
    ) -> JSONResponse:
        result = TransferController().get(
            request.headers.get("Authorization"),
            source_account_key,
            transaction_key,
        )
        return JSONResponse(
            content=result,
            status_code=status.HTTP_200_OK,
        )