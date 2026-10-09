from uuid import UUID

from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.service_charge_controller import ServiceChargeController
from utils.schema_handler import SchemaHandler


class ServiceChargeResource:
    @SchemaHandler.validate("post_service_charge.json")
    def on_post(
        self,
        request: Request,
        account_key: UUID,
        payload: dict,
    ) -> JSONResponse:
        result = ServiceChargeController().create(
            request.headers.get("Authorization"),
            account_key,
            payload,
        )
        return JSONResponse(content=result, status_code=status.HTTP_201_CREATED)

    @SchemaHandler.validate_query_params("get_service_charges.json")
    def on_get_list(
        self,
        request: Request,
        account_key: UUID,
    ) -> JSONResponse:
        result = ServiceChargeController().list_charges(
            request.headers.get("Authorization"),
            account_key,
            page=int(request.query_params.get("page", "1")),
            limit=int(request.query_params.get("limit", "20")),
        )
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)

    def on_get(
        self,
        request: Request,
        account_key: UUID,
        charge_key: UUID,
    ) -> JSONResponse:
        result = ServiceChargeController().get(
            request.headers.get("Authorization"),
            account_key,
            charge_key,
        )
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)