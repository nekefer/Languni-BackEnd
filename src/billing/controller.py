from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import RequireVerified, CurrentUser
from src.entities.user import User
from src.config import get_settings, Settings
from .models import CreateCheckoutRequest, CheckoutResponse, CustomerPortalResponse, SubscriptionStatusResponse
from .service import BillingService

router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CreateCheckoutRequest,
    token: RequireVerified,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Create a Lemon Squeezy checkout session. Returns the checkout URL."""
    user = db.query(User).filter(User.id == token.get_uuid()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        checkout_url = await BillingService.create_checkout(user, body.variant_id, settings)
        return CheckoutResponse(checkout_url=checkout_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/portal", response_model=CustomerPortalResponse)
async def create_portal(
    token: RequireVerified,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Generate a Lemon Squeezy customer portal URL for managing subscriptions."""
    user = db.query(User).filter(User.id == token.get_uuid()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        portal_url = await BillingService.create_portal_session(user, settings)
        return CustomerPortalResponse(portal_url=portal_url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/subscription", response_model=SubscriptionStatusResponse)
async def get_subscription(
    token: CurrentUser,
    db: Session = Depends(get_db),
):
    """Get the current user's subscription status."""
    user = db.query(User).filter(User.id == token.get_uuid()).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return BillingService.get_subscription(db, user)
