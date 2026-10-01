from uuid import UUID

import jwt

from models.client import Client

from controllers.base_controller import BaseController
from errors.auth_errors import InvalidAccessToken, InvalidCredentials
from repositories.client_repository import ClientRepository
from utils.jwt_token import (
    ACCESS_TOKEN_SECONDS,
    create_access_token,
    read_access_token,
)
from utils.password import hash_password, verify_password

DUMMY_PASSWORD_HASH = hash_password("senha-ficticia-para-verificacao")

class AuthController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = ClientRepository(self.context)

    def login(self, payload: dict) -> dict:
        email = payload["email"].lower()
        client = self.repository.get_by_email(email)

        password_hash = (
            client.password_hash if client is not None else DUMMY_PASSWORD_HASH
        )
        valid_password = verify_password(payload["password"], password_hash)

        if client is None or not valid_password:
            raise InvalidCredentials()

        return {
            "access_token": create_access_token(str(client.client_key)),
            "token_type": "bearer",
            "expires_in": ACCESS_TOKEN_SECONDS,
        }

    def authenticate(self, authorization: str | None) -> Client:
        if not authorization:
            raise InvalidAccessToken()

        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token:
            raise InvalidAccessToken()

        try:
            client_key: UUID = read_access_token(token)
        except (jwt.InvalidTokenError, ValueError, TypeError):
            raise InvalidAccessToken() from None

        client = self.repository.get_by_key(client_key)
        if client is None:
            raise InvalidAccessToken()

        return client

    def get_current_client(self, authorization: str | None) -> dict:
        client = self.authenticate(authorization)

        return {
            "client_key": str(client.client_key),
            "name": client.name,
            "email": client.email,
            "accounts": [
                {
                    "account_key": str(account.account_key),
                    "type": account.type,
                }
                for account in client.accounts
            ],
        }