import httpx
import logging
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
        """Generate a Lemon Squeezy customer portal URL."""
        subscription = user.subscription
        if not subscription or not subscription.ls_customer_id:
            raise Exception("No active subscription found")

        headers = {
            "Authorization": f"Bearer {settings.lemon_squeezy_api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        }
        payload = {
            "data": {
                "type": "customer-portal-sessions",
                "attributes": {
                    "customer_id": int(subscription.ls_customer_id),
                },
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{LS_API_BASE}/customer-portal-sessions",
                headers=headers,
                json=payload,
                timeout=15.0,
            )

        if response.status_code not in (200, 201):
            logger.error(f"LS portal session failed: {response.status_code} {response.text}")
            raise Exception("Failed to create customer portal session")

        data = response.json()
        portal_url = data["data"]["attributes"]["url"]
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
