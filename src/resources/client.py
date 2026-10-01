from fastapi import status as http_status
from fastapi.responses import JSONResponse

from controllers.client_controller import ClientController
from utils.schema_handler import SchemaHandler


class ClientResource:
    @SchemaHandler.validate("post_client.json")
    def on_post(self, payload: dict) -> JSONResponse:
        client = ClientController().create(payload)

        return JSONResponse(
            content=client,
            status_code=http_status.HTTP_201_CREATED,
        )