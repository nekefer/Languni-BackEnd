from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class CreateCheckoutRequest(BaseModel):
    variant_id: str


class CheckoutResponse(BaseModel):
    checkout_url: str


class CustomerPortalResponse(BaseModel):
    portal_url: str


class SubscriptionStatusResponse(BaseModel):
    plan: str                                    # 'free' | 'premium'
    status: Optional[str] = None                 # active | cancelled | past_due | etc.
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
