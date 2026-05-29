from fastapi import APIRouter, Request, HTTPException, Depends
from svix.webhooks import Webhook, WebhookVerificationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import select
from app.config import settings
from app.core.database import get_db
from app.models import Organization, User
from app.api.v1.schemas.base import SuccessEnvelope
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handles incoming webhooks from Clerk to synchronize Organization and User data.
    """
    wh_secret = settings.CLERK_WEBHOOK_SECRET.get_secret_value()
    if not wh_secret:
        logger.error("CLERK_WEBHOOK_SECRET is not set in environment or settings")
        raise HTTPException(
            status_code=500, detail="The authentication service is misconfigured. Please contact support.")

    headers = request.headers
    payload = await request.body()

    # svix headers are used by Clerk for signature verification
    svix_id = headers.get("svix-id")
    svix_timestamp = headers.get("svix-timestamp")
    svix_signature = headers.get("svix-signature")

    if not svix_id or not svix_timestamp or not svix_signature:
        raise HTTPException(status_code=400, detail="Missing svix headers")

    wh = Webhook(wh_secret)

    try:
        # Verify the webhook signature
        data = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        logger.warning(f"Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = data.get("type")
    event_data = data.get("data")

    logger.info(f"Received Clerk webhook: {event_type}")

    try:
        if event_type == "organization.created":
            await handle_org_created(event_data, db)
        elif event_type == "organization.updated":
            await handle_org_created(event_data, db)
        elif event_type == "organizationMembership.created":
            await handle_membership_created(event_data, db)
        elif event_type == "organizationMembership.updated":
            await handle_membership_created(event_data, db)
        elif event_type == "user.updated":
            await handle_user_updated(event_data, db)
        elif event_type == "organization.deleted":
            await handle_org_deleted(event_data, db)
        elif event_type == "organizationMembership.deleted":
            await handle_membership_deleted(event_data, db)
    except HTTPException:
        raise
    except Exception as e:
        # The global exception handler will mask the details, but we log everything here
        logger.error(f"Critical error processing Clerk webhook {event_type} [Data: {event_data}]: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"An unexpected error occurred while processing the {event_type} event.")

    return SuccessEnvelope(message="Webhook processed successfully.")


async def handle_org_created(data, db: AsyncSession):
    """Upsert organization record from Clerk org data."""
    stmt = insert(Organization).values(
        clerk_org_id=data["id"],
        name=data["name"],
        slug=data["slug"],
        is_active=True
    ).on_conflict_do_update(
        index_elements=["clerk_org_id"],
        set_={
            "name": data["name"],
            "slug": data["slug"],
            "is_active": True
        }
    )
    await db.execute(stmt)
    await db.commit()


async def handle_membership_created(data, db: AsyncSession):
    """Upsert user record and link to organization from Clerk membership data."""
    org_clerk_id = data["organization"]["id"]
    user_clerk_id = data["public_user_data"]["user_id"]
    email = data["public_user_data"].get("identifier") or ""

    # Find internal org_id
    org_res = await db.execute(select(Organization.id).where(Organization.clerk_org_id == org_clerk_id))
    org_id = org_res.scalar()

    if not org_id:
        logger.warning(
            f"Org {org_clerk_id} not found. Re-queueing membership sync...")
        raise HTTPException(
            status_code=422, detail="Organization not found yet")

    # Normalize role
    role = data["role"].split(":")[-1] if ":" in data["role"] else data["role"]

    stmt = insert(User).values(
        org_id=org_id,
        clerk_user_id=user_clerk_id,
        email=email,
        full_name=f"{data['public_user_data'].get('first_name', '')} {data['public_user_data'].get('last_name', '')}".strip(
        ),
        role=role,
        is_active=True
    ).on_conflict_do_update(
        index_elements=["clerk_user_id"],
        set_={
            "org_id": org_id,
            "role": role,
            "is_active": True
        }
    )
    await db.execute(stmt)
    await db.commit()


async def handle_user_updated(data, db: AsyncSession):
    """Update user profile data from Clerk user data."""
    user_clerk_id = data["id"]
    full_name = f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(
    )
    avatar_url = data.get("image_url")

    # Find the user by clerk_id
    res = await db.execute(select(User).where(User.clerk_user_id == user_clerk_id))
    user = res.scalar_one_or_none()

    if user:
        user.full_name = full_name
        user.avatar_url = avatar_url
        await db.commit()


async def handle_org_deleted(data, db: AsyncSession):
    """Hard-delete organization from the database."""
    clerk_id = data["id"]
    from sqlalchemy import delete
    await db.execute(delete(Organization).where(Organization.clerk_org_id == clerk_id))
    await db.commit()


async def handle_membership_deleted(data, db: AsyncSession):
    """Hard-delete user membership from the database."""
    user_clerk_id = data["public_user_data"]["user_id"]
    from sqlalchemy import delete
    await db.execute(delete(User).where(User.clerk_user_id == user_clerk_id))
    await db.commit()
