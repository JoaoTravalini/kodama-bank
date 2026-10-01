from sqlalchemy.exc import IntegrityError

from controllers.base_controller import BaseController
from errors.client_errors import (
    ClientDocumentAlreadyRegistered,
    ClientEmailAlreadyRegistered,
    InvalidClientDocument,
)
from repositories.client_repository import ClientRepository
from utils.document_number import is_valid_cpf
from utils.password import hash_password


class ClientController(BaseController):
    def __init__(self) -> None:
        super().__init__(__name__)
        self.repository = ClientRepository(self.context)

    def create(self, payload: dict) -> dict:
        document_number = (
            payload["document_number"].replace(".", "").replace("-", "")
        )
        email = payload["email"].lower()

        if not is_valid_cpf(document_number):
            raise InvalidClientDocument()

        if self.repository.get_by_document_number(document_number):
            raise ClientDocumentAlreadyRegistered()

        if self.repository.get_by_email(email):
            raise ClientEmailAlreadyRegistered()

        client = self.repository.create(
            name=payload["name"].strip(),
            email=email,
            document_number=document_number,
            password_hash=hash_password(payload["password"]),
        )

        response = {
            "client_key": str(client.client_key),
            "accounts": [
                {
                    "account_key": str(account.account_key),
                    "type": account.type,
                }
                for account in client.accounts
            ],
        }

        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()

            constraint = getattr(
                getattr(exc.orig, "diag", None),
                "constraint_name",
                None,
            )

            if constraint == "clients_document_number_key":
                raise ClientDocumentAlreadyRegistered() from None

            if constraint == "clients_email_key":
                raise ClientEmailAlreadyRegistered() from None

            raise

        return response