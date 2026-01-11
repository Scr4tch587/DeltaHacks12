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
        key: S3 object key
        expires_in: Expiration time in seconds
    
    Returns:
        Presigned URL string
    """
    client = get_s3_client()
    
    try:
        url = client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': VULTR_BUCKET,
                'Key': key
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
        key: S3 object key
    
    Returns:
        Object content as bytes
    
    Raises:
        Exception: If the object cannot be fetched
    """
    client = get_s3_client()
    
    try:
        response = client.get_object(Bucket=VULTR_BUCKET, Key=key)
        return response['Body'].read()
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == 'NoSuchKey':
            raise Exception(f"Object not found: {key}")
        elif error_code == 'AccessDenied':
            raise Exception(f"Access denied: {key}")
        else:
            raise Exception(f"Failed to fetch object '{key}': {str(e)}")
