import hashlib
import hmac
import httpx
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.entities.user import User
from src.entities.subscription import Subscription
from src.config import Settings
from .models import SubscriptionStatusResponse

logger = logging.getLogger("billing")

LS_API_BASE = "https://api.lemonsqueezy.com/v1"


class BillingService:

    @staticmethod
    async def create_checkout(user: User, variant_id: str, settings: Settings) -> str:
        """Create a Lemon Squeezy checkout session and return the checkout URL."""
        headers = {
            "Authorization": f"Bearer {settings.lemon_squeezy_api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        payload = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "checkout_data": {
                        "email": user.email,
                        "name": f"{user.first_name} {user.last_name}".strip(),
                        "custom": {
                            "user_id": str(user.id),
                        },
                    },
                    "product_options": {
                        "redirect_url": f"{settings.frontend_url}/pricing/success",
                    },
                },
                "relationships": {
                    "store": {
                        "data": {"type": "stores", "id": settings.lemon_squeezy_store_id}
                    },
                    "variant": {
                        "data": {"type": "variants", "id": variant_id}
                    },
                },
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{LS_API_BASE}/checkouts",
                headers=headers,
                json=payload,
                timeout=15.0,
            )

        if response.status_code != 201:
            logger.error(f"LS checkout creation failed: {response.status_code} {response.text}")
            raise Exception("Failed to create checkout session")

        data = response.json()
        checkout_url = data["data"]["attributes"]["url"]
        return checkout_url

    @staticmethod
    async def create_portal_session(user: User, settings: Settings) -> str:
        """Generate a Lemon Squeezy customer portal URL by fetching the subscription."""
        subscription = user.subscription
        if not subscription or not subscription.ls_subscription_id:
            raise Exception("No active subscription found")

        headers = {
            "Authorization": f"Bearer {settings.lemon_squeezy_api_key}",
            "Accept": "application/vnd.api+json",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{LS_API_BASE}/subscriptions/{subscription.ls_subscription_id}",
                headers=headers,
                timeout=15.0,
            )

        if response.status_code != 200:
            logger.error(f"LS fetch subscription failed: {response.status_code} {response.text}")
            raise Exception("Failed to fetch subscription")

        data = response.json()
        portal_url = data["data"]["attributes"]["urls"]["customer_portal"]
        return portal_url

    @staticmethod
    def get_subscription(db: Session, user: User) -> SubscriptionStatusResponse:
        """Return the user's current subscription status."""
        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            return SubscriptionStatusResponse(plan=user.subscription_plan)
        return SubscriptionStatusResponse(
            plan=user.subscription_plan,
            status=sub.status,
            current_period_end=sub.current_period_end,
            cancel_at_period_end=sub.cancel_at_period_end,
        )

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
        """Verify the Lemon Squeezy webhook signature (HMAC-SHA256)."""
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def handle_webhook(payload: dict, db: Session) -> None:
        """Process a verified Lemon Squeezy webhook event and update the database."""
        event_name = payload.get("meta", {}).get("event_name", "")
        data = payload.get("data", {})
        attrs = data.get("attributes", {})
        meta_custom = payload.get("meta", {}).get("custom_data", {})

        # Every subscription event carries user_id in meta.custom_data
        user_id = meta_custom.get("user_id")
        if not user_id:
            logger.warning(f"Webhook {event_name}: no user_id in custom_data, skipping")
            return

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"Webhook {event_name}: user {user_id} not found, skipping")
            return

        ls_subscription_id = str(data.get("id", ""))
        ls_customer_id = str(attrs.get("customer_id", ""))
        ls_order_id = str(attrs.get("order_id", "")) if attrs.get("order_id") else None
        ls_variant_id = str(attrs.get("variant_id", "")) if attrs.get("variant_id") else None
        status = attrs.get("status", "")

        # Parse billing period dates
        period_start = None
        period_end = None
        if attrs.get("renews_at"):
            try:
                period_end = datetime.fromisoformat(attrs["renews_at"].replace("Z", "+00:00"))
            except Exception:
                pass
        if attrs.get("created_at"):
            try:
                period_start = datetime.fromisoformat(attrs["created_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        cancel_at_period_end = attrs.get("cancelled", False)

        # Upsert Subscription row
        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        if not sub:
            sub = Subscription(user_id=user.id)
            db.add(sub)

        sub.ls_subscription_id = ls_subscription_id
        sub.ls_customer_id = ls_customer_id
        if ls_order_id:
            sub.ls_order_id = ls_order_id
        if ls_variant_id:
            sub.ls_variant_id = ls_variant_id
        sub.status = status
        sub.cancel_at_period_end = cancel_at_period_end
        if period_start:
            sub.current_period_start = period_start
        if period_end:
            sub.current_period_end = period_end

        # Update user plan based on event
        if event_name in ("subscription_created", "subscription_updated", "subscription_resumed"):
            if status in ("active", "trialing"):
                user.subscription_plan = "premium"
                sub.plan = "premium"
            elif status in ("expired", "cancelled"):
                user.subscription_plan = "free"
                sub.plan = "free"

        elif event_name == "subscription_cancelled":
            # Still active until period ends — keep premium, just flag it
            sub.cancel_at_period_end = True

        elif event_name in ("subscription_expired", "subscription_unpaid"):
            # Subscription is truly over — downgrade to free
            user.subscription_plan = "free"
            sub.plan = "free"
            sub.status = status

        elif event_name == "subscription_paused":
            user.subscription_plan = "free"
            sub.plan = "free"
            sub.status = "paused"

        db.commit()
        logger.info(f"Webhook {event_name}: user {user_id} → plan={user.subscription_plan}, status={status}")
