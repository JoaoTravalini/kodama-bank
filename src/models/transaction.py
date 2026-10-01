from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    transaction_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    fee = Column(Numeric(18, 2), nullable=False, server_default="0")
    source_account_id = Column(Integer, ForeignKey("accounts.id"))
    destination_account_id = Column(
        Integer,
        ForeignKey("accounts.id"),
        nullable=False,
    )
    idempotency_key = Column(UUID(as_uuid=True))
    external_reference = Column(String(100), unique=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    completed_at = Column(DateTime)


class AccountEntry(Base):
    __tablename__ = "account_entries"

    id = Column(Integer, primary_key=True)
    entry_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        nullable=False,
    )
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    kind = Column(String(20), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    balance_after = Column(Numeric(18, 2), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())