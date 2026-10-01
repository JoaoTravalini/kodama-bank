from uuid import uuid4

from database import Context
from models.client import Account, Client


class ClientRepository:
    def __init__(self, context: Context) -> None:
        self.session = context.db_session

    def get_by_document_number(self, document_number: str) -> Client | None:
        return (
            self.session.query(Client)
            .filter(Client.document_number == document_number)
            .first()
        )

    def get_by_email(self, email: str) -> Client | None:
        return (
            self.session.query(Client)
            .filter(Client.email == email)
            .first()
        )
        
    def get_by_key(self, client_key) -> Client | None:
        return (
            self.session.query(Client)
            .filter(Client.client_key == client_key)
            .first()
        )

    def create(
        self,
        name: str,
        email: str,
        document_number: str,
        password_hash: str,
    ) -> Client:
        client = Client(
            client_key=uuid4(),
            name=name,
            email=email,
            document_number=document_number,
            password_hash=password_hash,
        )

        client.accounts = [
            Account(account_key=uuid4(), type="personal"),
            Account(account_key=uuid4(), type="professional"),
        ]

        self.session.add(client)
        return client