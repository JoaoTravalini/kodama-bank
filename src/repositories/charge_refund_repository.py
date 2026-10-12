from uuid import UUID

from models.service_charge import ServiceCharge
from models.transaction import AccountEntry, Transaction
from repositories.transfer_repository import TransferRepository


class ChargeRefundRepository(TransferRepository):
    def get_owned_charge(
        self, account_id: int, charge_key: UUID
    ) -> ServiceCharge | None:
        return (
            self.session.query(ServiceCharge)
            .filter(
                ServiceCharge.account_id == account_id,
                ServiceCharge.charge_key == charge_key,
            )
            .first()
        )

    def get_transaction_by_id(self, transaction_id: int) -> Transaction | None:
        return self.session.get(Transaction, transaction_id)

    def get_for_charge(
        self, account_id: int, charge_id: int, transaction_key: UUID
    ) -> Transaction | None:
        return (
            self.session.query(Transaction)
            .filter(
                Transaction.kind == "REFUND",
                Transaction.source_account_id == account_id,
                Transaction.service_charge_id == charge_id,
                Transaction.transaction_key == transaction_key,
            )
            .first()
        )

    def get_entries(self, transaction_id: int) -> list[AccountEntry]:
        return (
            self.session.query(AccountEntry)
            .filter(AccountEntry.transaction_id == transaction_id)
            .order_by(AccountEntry.id)
            .all()
        )