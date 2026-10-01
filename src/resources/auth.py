from fastapi import Request, status
from fastapi.responses import JSONResponse

from controllers.auth_controller import AuthController
from utils.schema_handler import SchemaHandler


class AuthResource:
    @SchemaHandler.validate("post_login.json")
    def on_post_login(self, payload: dict) -> JSONResponse:
        result = AuthController().login(payload)
        return JSONResponse(content=result, status_code=status.HTTP_200_OK)

    def on_get_me(self, request: Request) -> JSONResponse:
        client = AuthController().get_current_client(
            request.headers.get("Authorization")
        )
        return JSONResponse(content=client, status_code=status.HTTP_200_OK)