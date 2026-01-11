#!/usr/bin/env python3
"""Fix DigitalOcean Spaces ACLs for HLS files."""

import boto3
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# DigitalOcean Spaces configuration
DO_SPACES_KEY = os.getenv("DO_SPACES_KEY")
DO_SPACES_SECRET = os.getenv("DO_SPACES_SECRET")
DO_SPACES_BUCKET = os.getenv("DO_SPACES_BUCKET", "deltahacksvideos")
DO_SPACES_REGION = os.getenv("DO_SPACES_REGION", "tor1")

if not DO_SPACES_KEY or not DO_SPACES_SECRET:
    print("ERROR: DO_SPACES_KEY and DO_SPACES_SECRET must be set in .env")
    exit(1)

# Initialize S3 client
s3 = boto3.client(
    "s3",
    endpoint_url=f"https://{DO_SPACES_REGION}.digitaloceanspaces.com",
    aws_access_key_id=DO_SPACES_KEY,
    aws_secret_access_key=DO_SPACES_SECRET,
    region_name=DO_SPACES_REGION
)

prefix = "hls/"

print(f"Updating ACLs for all files in {DO_SPACES_BUCKET}/{prefix}...")
print("This will make all HLS files publicly readable.\n")

count = 0
paginator = s3.get_paginator("list_objects_v2")

try:
    for page in paginator.paginate(Bucket=DO_SPACES_BUCKET, Prefix=prefix):
        if "Contents" not in page:
            continue
        
        for obj in page["Contents"]:
            key = obj["Key"]
            try:
                s3.put_object_acl(Bucket=DO_SPACES_BUCKET, Key=key, ACL="public-read")
                print(f"✓ {key}")
                count += 1
            except Exception as e:
                print(f"✗ {key}: {e}")

    print(f"\n✅ Successfully updated {count} files")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    exit(1)
