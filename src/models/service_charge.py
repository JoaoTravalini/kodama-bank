from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from models.base import Base


class ServiceCharge(Base):
    __tablename__ = "service_charges"

    id = Column(Integer, primary_key=True)
    charge_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    description = Column(String(255), nullable=False)
    amount = Column(Numeric(18, 2), nullable=False)
    due_date = Column(Date)
    status = Column(String(20), nullable=False, server_default="OPEN")
    paid_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
    )
    refunded_transaction_id = Column(
        Integer,
        ForeignKey("transactions.id"),
        unique=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    paid_at = Column(DateTime)
    canceled_at = Column(DateTime)
    refunded_at = Column(DateTime)