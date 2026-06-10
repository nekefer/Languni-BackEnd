from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
from datetime import datetime
from ..database.core import Base


class Subscription(Base):
    __tablename__ = 'subscriptions'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)

    ls_customer_id = Column(String, nullable=True)
    ls_subscription_id = Column(String, nullable=True, unique=True)
    ls_order_id = Column(String, nullable=True)
    ls_variant_id = Column(String, nullable=True)

    # Plan info
    plan = Column(String(20), default='free', nullable=False)   # 'free' | 'premium'
    status = Column(String(20), nullable=True)                  # active | cancelled | expired | past_due | paused | unpaid | trialing

    # Billing period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="subscription")

    def __repr__(self):
        return f"<Subscription(user_id='{self.user_id}', plan='{self.plan}', status='{self.status}')>"
