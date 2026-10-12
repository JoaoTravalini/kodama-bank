from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.charge_refund_controller import ChargeRefundController
from utils.schema_handler import SchemaHandler


class ChargeRefundResource:
    @SchemaHandler.validate("post_charge_refund.json")
    def on_post(
        self,
        request: Request,
        account_key: UUID,
        charge_key: UUID,
        payload: dict,
    ) -> JSONResponse:
        result = ChargeRefundController().create(
            request.headers.get("Authorization"),
            account_key,
            charge_key,
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
        account_key: UUID,
        charge_key: UUID,
        transaction_key: UUID,
    ) -> JSONResponse:
        result = ChargeRefundController().get(
            request.headers.get("Authorization"),
            account_key,
            charge_key,
            transaction_key,
        )
        return JSONResponse(
            content=result,
            status_code=status.HTTP_200_OK,
        )

    def on_get_receipt(
        self,
        request: Request,
        account_key: UUID,
        charge_key: UUID,
        transaction_key: UUID,
    ) -> JSONResponse:
        result = ChargeRefundController().receipt(
            request.headers.get("Authorization"),
            account_key,
            charge_key,
            transaction_key,
        )
        return JSONResponse(
            content=result,
            status_code=status.HTTP_200_OK,
            headers={"Cache-Control": "no-store"},
        )