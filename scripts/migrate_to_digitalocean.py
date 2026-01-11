#!/usr/bin/env python3
"""
Migration script to copy HLS videos from Vultr Object Storage to DigitalOcean Spaces.

Usage:
    python scripts/migrate_to_digitalocean.py

Requires:
    pip install boto3
"""

import boto3
from botocore.config import Config
import os
import sys

# =============================================================================
# CONFIGURATION - Vultr (Source)
# =============================================================================
VULTR_ENDPOINT = os.getenv("VULTR_ENDPOINT", "https://ewr1.vultrobjects.com")
VULTR_ACCESS_KEY = os.getenv("VULTR_ACCESS_KEY", "")
VULTR_SECRET_KEY = os.getenv("VULTR_SECRET_KEY", "")
VULTR_BUCKET = os.getenv("VULTR_BUCKET", "deltahacks-storage-real")

# The prefix where HLS files are stored in Vultr
# Based on your structure: deltahacks-storage-real/deltahacks-storage-real/hls/
VULTR_PREFIX = "deltahacks-storage-real/hls/"

# =============================================================================
# CONFIGURATION - DigitalOcean Spaces (Destination)
# =============================================================================
DO_ENDPOINT = os.getenv("DO_SPACES_ENDPOINT", "https://deltahacksvideos.tor1.digitaloceanspaces.com")
DO_ACCESS_KEY = os.getenv("DO_SPACES_ACCESS_KEY", "")
DO_SECRET_KEY = os.getenv("DO_SPACES_SECRET_KEY", "")
DO_BUCKET = os.getenv("DO_SPACES_BUCKET", "deltahacksvideos")
DO_REGION = os.getenv("DO_SPACES_REGION", "tor1")

# Destination prefix in DigitalOcean (simpler structure: hls/{video_id}/...)
DO_PREFIX = "hls/"

# =============================================================================
# MAIN SCRIPT
# =============================================================================

def create_vultr_client():
    """Create Vultr S3 client."""
    if not VULTR_ACCESS_KEY or not VULTR_SECRET_KEY:
        print("❌ Vultr credentials not set. Please set VULTR_ACCESS_KEY and VULTR_SECRET_KEY environment variables.")
        print("   Or edit this script and add them directly.")
        sys.exit(1)
    
    return boto3.client(
        's3',
        endpoint_url=VULTR_ENDPOINT,
        aws_access_key_id=VULTR_ACCESS_KEY,
        aws_secret_access_key=VULTR_SECRET_KEY,
        config=Config(signature_version='s3v4')
    )

def create_do_client():
    """Create DigitalOcean Spaces S3 client."""
    if not DO_ACCESS_KEY or not DO_SECRET_KEY:
        print("❌ DigitalOcean credentials not set. Please set DO_SPACES_ACCESS_KEY and DO_SPACES_SECRET_KEY environment variables.")
        sys.exit(1)
    
    return boto3.client(
        's3',
        endpoint_url=DO_ENDPOINT,
        aws_access_key_id=DO_ACCESS_KEY,
        aws_secret_access_key=DO_SECRET_KEY,
        region_name=DO_REGION,
        config=Config(signature_version='s3v4')
    )

def list_vultr_objects(client, prefix=""):
    """List all objects in Vultr bucket with given prefix."""
    objects = []
    paginator = client.get_paginator('list_objects_v2')
    
    for page in paginator.paginate(Bucket=VULTR_BUCKET, Prefix=prefix):
        if 'Contents' in page:
            for obj in page['Contents']:
                objects.append(obj)
    
    return objects

def copy_object(vultr_client, do_client, vultr_key, do_key):
    """Copy a single object from Vultr to DigitalOcean."""
    try:
        # Download from Vultr
        response = vultr_client.get_object(Bucket=VULTR_BUCKET, Key=vultr_key)
        body = response['Body'].read()
        content_type = response.get('ContentType', 'application/octet-stream')
        
        # Determine content type based on extension if not set
        if content_type == 'application/octet-stream':
            if vultr_key.endswith('.m3u8'):
                content_type = 'application/vnd.apple.mpegurl'
            elif vultr_key.endswith('.ts'):
                content_type = 'video/MP2T'
            elif vultr_key.endswith('.jpg') or vultr_key.endswith('.jpeg'):
                content_type = 'image/jpeg'
            elif vultr_key.endswith('.png'):
                content_type = 'image/png'
        
        # Upload to DigitalOcean with public-read ACL
        do_client.put_object(
            Bucket=DO_BUCKET,
            Key=do_key,
            Body=body,
            ContentType=content_type,
            ACL='public-read'  # Make it publicly accessible
        )
        
        return True
    except Exception as e:
        print(f"    ❌ Error copying {vultr_key}: {e}")
        return False

def main():
    print("=" * 60)
    print("Migration: Vultr Object Storage → DigitalOcean Spaces")
    print("=" * 60)
    print()
    
    # Create clients
    print("📡 Connecting to Vultr Object Storage...")
    vultr_client = create_vultr_client()
    
    print("📡 Connecting to DigitalOcean Spaces...")
    do_client = create_do_client()
    
    # Test DigitalOcean connection
    try:
        do_client.head_bucket(Bucket=DO_BUCKET)
        print(f"✅ Connected to DigitalOcean Spaces bucket: {DO_BUCKET}")
    except Exception as e:
        print(f"❌ Failed to connect to DigitalOcean Spaces: {e}")
        sys.exit(1)
    
    # List all objects in Vultr
    print()
    print(f"📂 Listing objects in Vultr bucket: {VULTR_BUCKET}")
    print(f"   Prefix: {VULTR_PREFIX}")
    
    objects = list_vultr_objects(vultr_client, VULTR_PREFIX)
    
    if not objects:
        print("⚠️  No objects found with prefix. Trying without prefix...")
        # Try listing all objects
        all_objects = list_vultr_objects(vultr_client, "")
        print(f"   Found {len(all_objects)} total objects in bucket")
        if all_objects:
            print("   First 5 keys:")
            for obj in all_objects[:5]:
                print(f"     - {obj['Key']}")
        
        # Look for hls folders
        hls_objects = [obj for obj in all_objects if 'hls/' in obj['Key']]
        if hls_objects:
            print(f"   Found {len(hls_objects)} objects containing 'hls/'")
            objects = hls_objects
        else:
            print("❌ No HLS objects found in bucket")
            sys.exit(1)
    
    print(f"📊 Found {len(objects)} objects to migrate")
    
    # Calculate total size
    total_size = sum(obj['Size'] for obj in objects)
    print(f"📦 Total size: {total_size / (1024*1024):.2f} MB")
    print()
    
    # Migrate objects
    print("🚀 Starting migration...")
    print()
    
    success_count = 0
    error_count = 0
    
    for i, obj in enumerate(objects, 1):
        vultr_key = obj['Key']
        
        # Transform key from Vultr structure to DigitalOcean structure
        # Vultr: deltahacks-storage-real/hls/{video_id}/...
        # DigitalOcean: hls/{video_id}/...
        
        # Find the hls/ part and extract from there
        if 'hls/' in vultr_key:
            hls_index = vultr_key.find('hls/')
            do_key = vultr_key[hls_index:]  # hls/{video_id}/...
        else:
            do_key = vultr_key
        
        size_kb = obj['Size'] / 1024
        print(f"[{i}/{len(objects)}] Copying: {do_key} ({size_kb:.1f} KB)")
        
        if copy_object(vultr_client, do_client, vultr_key, do_key):
            success_count += 1
        else:
            error_count += 1
    
    print()
    print("=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"✅ Successfully migrated: {success_count} files")
    if error_count > 0:
        print(f"❌ Errors: {error_count} files")
    print()
    print(f"📍 CDN URL pattern:")
    print(f"   https://deltahacksvideos.tor1.cdn.digitaloceanspaces.com/hls/{{video_id}}/master.m3u8")
    print()

if __name__ == "__main__":
    main()
