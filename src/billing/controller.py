import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session
from src.database.core import get_db
from src.auth.service import RequireVerified, CurrentUser
from src.entities.user import User
from src.config import get_settings, Settings
from .models import CreateCheckoutRequest, CheckoutResponse, CustomerPortalResponse, SubscriptionStatusResponse
from .service import BillingService

logger = logging.getLogger("billing")

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


@router.post("/webhook", status_code=200)
async def lemon_squeezy_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_signature: str = Header(..., alias="X-Signature"),
):
    """Receive and process Lemon Squeezy webhook events."""
    import json

    raw_body = await request.body()

    if not BillingService.verify_webhook_signature(raw_body, x_signature, settings.lemon_squeezy_webhook_secret):
        logger.warning("Webhook signature verification failed")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event_name = payload.get("meta", {}).get("event_name", "unknown")
    logger.info(f"Received LS webhook: {event_name}")

    try:
        BillingService.handle_webhook(payload, db)
    except Exception as e:
        logger.error(f"Webhook handler error for {event_name}: {e}", exc_info=True)
        # Still return 200 so LS doesn't retry for internal errors
        return {"received": True}

    return {"received": True}
