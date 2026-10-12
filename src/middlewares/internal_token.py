from fastapi import FastAPI, Request

from constants import BYPASS_ENDPOINTS, INTERNAL_TOKEN
from errors.base_error import ForbiddenNotInternal
from errors.handlers import qi_exception_to_response


def register_internal_token_middleware(application: FastAPI) -> None:
    @application.middleware("http")
    async def check_internal_token(request: Request, call_next):
        path_parts = request.url.path.strip("/").split("/")

        is_client_transfer = (
            request.method == "POST"
            and len(path_parts) == 3
            and path_parts[0] == "accounts"
            and path_parts[2] == "transfers"
        )

        is_client_charge = (
            request.method == "POST"
            and len(path_parts) == 3
            and path_parts[0] == "accounts"
            and path_parts[2] == "charges"
        )

        is_charge_payment = (
            request.method == "POST"
            and len(path_parts) == 3
            and path_parts[0] == "accounts"
            and path_parts[2] == "charge-payments"
        )

        is_client_charge_action = (
            request.method == "POST"
            and len(path_parts) == 5
            and path_parts[0] == "accounts"
            and path_parts[2] == "charges"
            and path_parts[4] in ("cancel", "refunds")
        )

        is_public = (
            request.url.path in BYPASS_ENDPOINTS
            or (
                request.url.path == "/clients"
                and request.method == "POST"
            )
            or (
                request.url.path == "/auth/login"
                and request.method == "POST"
            )
            or (
                request.url.path == "/clients/me"
                and request.method == "GET"
            )
            or (
                request.method == "GET"
                and (
                    request.url.path == "/accounts"
                    or request.url.path.startswith("/accounts/")
                )
            )
            or is_client_transfer
            or is_client_charge
            or is_charge_payment
            or is_client_charge_action
        )

        if request.method == "OPTIONS" or is_public:
            return await call_next(request)

        if request.headers.get("INTERNAL-TOKEN") != INTERNAL_TOKEN:
            return qi_exception_to_response(ForbiddenNotInternal())

        return await call_next(request)