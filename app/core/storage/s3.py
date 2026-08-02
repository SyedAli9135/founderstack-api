import asyncio
from typing import Optional

import boto3

from app.config import settings


def _client():
    kwargs = dict(
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY.get_secret_value(),
    )
    if settings.AWS_S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _ensure_bucket(client) -> None:
    """LocalStack starts with no buckets — create it on first use. Real AWS buckets are provisioned out-of-band."""
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET_DOCUMENTS)
    except Exception:
        client.create_bucket(Bucket=settings.S3_BUCKET_DOCUMENTS)


async def upload_bytes(key: str, data: bytes, content_type: Optional[str] = None) -> None:
    """Upload raw bytes to the documents bucket under `key`."""
    def _upload():
        client = _client()
        if settings.AWS_S3_ENDPOINT_URL:
            _ensure_bucket(client)
        extra_args = {"ContentType": content_type} if content_type else {}
        client.put_object(Bucket=settings.S3_BUCKET_DOCUMENTS, Key=key, Body=data, **extra_args)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _upload)


async def download_bytes(key: str) -> bytes:
    """Download raw bytes for `key` from the documents bucket."""
    def _download():
        client = _client()
        response = client.get_object(Bucket=settings.S3_BUCKET_DOCUMENTS, Key=key)
        return response["Body"].read()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _download)


async def delete_object(key: str) -> None:
    """Delete `key` from the documents bucket."""
    def _delete():
        client = _client()
        client.delete_object(Bucket=settings.S3_BUCKET_DOCUMENTS, Key=key)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _delete)
