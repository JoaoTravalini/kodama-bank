from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.charge_payment_controller import ChargePaymentController
from utils.schema_handler import SchemaHandler


class ChargePaymentResource:
    @SchemaHandler.validate("post_charge_payment.json")
    def on_post(
        self,
        request: Request,
        source_account_key: UUID,
        payload: dict,
    ) -> JSONResponse:
        result = ChargePaymentController().create(
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