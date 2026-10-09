from fastapi import FastAPI, Request

from constants import BYPASS_ENDPOINTS, INTERNAL_TOKEN
from errors.base_error import ForbiddenNotInternal
from errors.handlers import qi_exception_to_response


def register_internal_token_middleware(application: FastAPI) -> None:
    """Deixa passar só quem manda o header INTERNAL-TOKEN com o valor certo.

    O valor certo vem da variável de ambiente INTERNAL_TOKEN, nunca do
    código. As rotas de BYPASS_ENDPOINTS (raiz e health check) são públicas.

    Repare que aqui a gente DEVOLVE a resposta de erro em vez de levantar
    a exceção: dentro de um middleware, ninguém está escutando pra traduzir
    o erro — quem traduz são os exception handlers, que rodam mais pra
    dentro. Levantar aqui viraria um 500.
    """

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

        is_public = request.url.path in BYPASS_ENDPOINTS or (
            request.url.path == "/clients" and request.method == "POST"
        ) or (
            request.url.path == "/auth/login" and request.method == "POST"
        ) or (
            request.url.path == "/clients/me" and request.method == "GET"
        ) or (
            request.method == "GET"
            and (
                request.url.path == "/accounts"
                or request.url.path.startswith("/accounts/")
            )
        ) or is_client_transfer or is_client_charge

        if request.method == "OPTIONS" or is_public:
            return await call_next(request)

        if request.headers.get("INTERNAL-TOKEN") != INTERNAL_TOKEN:
            return qi_exception_to_response(ForbiddenNotInternal())

        return await call_next(request)