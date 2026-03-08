from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Literal
from ..email import service as email_service
from ..rate_limiter import limiter
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contact", tags=["contact"])

SUBJECTS = Literal["General", "Bug report", "Billing", "Feature request", "Other"]


class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    subject: SUBJECTS
    message: str = Field(..., min_length=10, max_length=2000)


@router.post("", status_code=200)
@limiter.limit("3/hour")
async def send_contact_message(
    request: Request,
    body: ContactRequest,
):
    """Send a contact message to the Languni team. Public endpoint."""
    try:
        email_service.send_contact_email(
            from_name=body.name,
            from_email=body.email,
            subject=body.subject,
            message=body.message,
        )
    except Exception as e:
        logger.error(f"Failed to send contact email from {body.email}: {e}")

    return {"message": "Your message has been sent successfully."}
