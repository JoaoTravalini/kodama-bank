from sqlalchemy import (
    CHAR, CheckConstraint, Column, DateTime, ForeignKey,
    Integer, Numeric, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from models.base import Base

class Client(Base):
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True)
    client_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    document_number = Column(CHAR(11), nullable=False, unique=True)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    accounts = relationship("Account", back_populates="client")
    
class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)
    account_key = Column(UUID(as_uuid=True), nullable=False, unique=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    type = Column(String(20), nullable=False)
    balance = Column(Numeric(18, 2), nullable=False, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    client = relationship("Client", back_populates="accounts")

    __table_args__ = (
        UniqueConstraint("client_id", "type"),
        CheckConstraint("type IN ('personal', 'professional')"),
        CheckConstraint("balance >= 0"),
    )