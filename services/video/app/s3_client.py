"""
S3 client module for Vultr Object Storage with configurable addressing style.
"""
import os
import re
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import Optional

# Environment variables
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "")
S3_ADDRESSING_STYLE = os.getenv("S3_ADDRESSING_STYLE", "path").lower()  # path or virtual
PRESIGN_EXPIRES_SECONDS = int(os.getenv("PRESIGN_EXPIRES_SECONDS", os.getenv("PRESIGNED_URL_EXPIRY", "3600")))  # Default 1 hour

# S3 key prefix - files are stored under bucket-name/hls/ in this setup
# If your files are at root level (just hls/), set this to empty string
S3_KEY_PREFIX = os.getenv("S3_KEY_PREFIX", VULTR_BUCKET)  # Default to bucket name as prefix


def get_s3_key(relative_key: str) -> str:
    """
    Construct the full S3 key with the configured prefix.
    
    Args:
        relative_key: Relative key path (e.g., "hls/abc123/master.m3u8")
    
    Returns:
        Full S3 key with prefix (e.g., "deltahacks-storage-real/hls/abc123/master.m3u8")
    """
    if S3_KEY_PREFIX:
        # Remove leading slash from prefix if present
        prefix = S3_KEY_PREFIX.rstrip('/')
        # Remove leading slash from key if present
        key = relative_key.lstrip('/')
        return f"{prefix}/{key}"
    return relative_key.lstrip('/')

_s3_client: Optional[boto3.client] = None


def get_s3_client():
    """Get or create the S3 client with configured addressing style."""
    global _s3_client
    
    if _s3_client is not None:
        return _s3_client
    
    if not (VULTR_ENDPOINT and VULTR_ACCESS_KEY and VULTR_SECRET_KEY):
        raise ValueError("Vultr S3 credentials not configured")
    
    # Extract region from endpoint (e.g., https://ewr1.vultrobjects.com -> ewr1)
    region_match = re.search(r'//([^.]+)\.vultrobjects\.com', VULTR_ENDPOINT)
    region = region_match.group(1) if region_match else 'us-east-1'
    
    # Configure addressing style
    addressing_style = 'path' if S3_ADDRESSING_STYLE == 'path' else 'virtual'
    s3_config = Config(
        signature_version='s3v4',
        s3={
            'addressing_style': addressing_style
        }
    )
    
    _s3_client = boto3.client(
        's3',
        endpoint_url=VULTR_ENDPOINT,
        aws_access_key_id=VULTR_ACCESS_KEY,
        aws_secret_access_key=VULTR_SECRET_KEY,
        region_name=region,
        config=s3_config
    )
    
    return _s3_client


def get_presigned_url(key: str, expires_in: int = PRESIGN_EXPIRES_SECONDS) -> str:
    """
    Generate a presigned URL for an S3 object.
    
    Args:
        key: S3 object key (relative key, will be prefixed automatically)
        expires_in: Expiration time in seconds
    
    Returns:
        Presigned URL string
    """
    client = get_s3_client()
    
    # Construct full S3 key with prefix
    full_key = get_s3_key(key)
    
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': VULTR_BUCKET,
                'Key': full_key
            },
            ExpiresIn=expires_in
        )
        return url
    except ClientError as e:
        raise Exception(f"Failed to generate presigned URL for key '{key}': {str(e)}")


def fetch_object(key: str) -> bytes:
    """
    Fetch an object from S3.
    
    Args:
        key: S3 object key (relative key, will be prefixed automatically)
    
    Returns:
        Object content as bytes
    
    Raises:
        Exception: If the object cannot be fetched
    """
    client = get_s3_client()
    
    # Construct full S3 key with prefix
    full_key = get_s3_key(key)
    
    try:
        response = client.get_object(Bucket=VULTR_BUCKET, Key=full_key)
        return response['Body'].read()
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'NoSuchKey':
            # Include the full key in the error for debugging
            raise Exception(f"Object not found: {key} (resolved to: {full_key} in bucket: {VULTR_BUCKET})")
        elif error_code == 'AccessDenied':
            raise Exception(f"Access denied: {key} (resolved to: {full_key} in bucket: {VULTR_BUCKET})")
        else:
            raise Exception(f"Failed to fetch object '{key}': {str(e)}")
