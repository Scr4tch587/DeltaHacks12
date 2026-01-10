# Vultr Object Storage Setup Guide

This guide will help you set up Vultr Object Storage and get the credentials needed for your application.

## Step 1: Access Vultr Object Storage Dashboard

1. Log in to your Vultr account: https://my.vultr.com/
2. Navigate to **Products** → **Object Storage** in the left sidebar
3. Click **Create Object Storage** if you haven't already created an instance

## Step 2: Create a Bucket (if needed)

1. Once you have an Object Storage instance, you'll see it listed
2. Click on the instance name to open it
3. You can create buckets directly in the dashboard or via the API/S3 client

## Step 3: Get Your Access Keys

1. In the Object Storage dashboard, click on **Settings** or **Access Keys**
2. You'll see two options:
   - **S3 Compatible Endpoint**: This is your `VULTR_ENDPOINT`
     - Format: `https://REGION.vultrobjects.com`
     - Example: `https://ewr1.vultrobjects.com` (for East Coast US - Newark)
     - Common regions:
       - `ewr1` - East Coast US (Newark)
       - `sjc1` - West Coast US (San Jose)
       - `lax1` - West Coast US (Los Angeles)
       - `fra1` - Frankfurt, Germany
       - `ams1` - Amsterdam, Netherlands
       - `nrt1` - Tokyo, Japan

3. To get Access Keys:
   - Go to **Settings** → **S3 Compatible** tab
   - Click **Generate New Access Key** (or use existing keys if you have them)
   - **Access Key ID**: This is your `VULTR_ACCESS_KEY`
   - **Secret Access Key**: This is your `VULTR_SECRET_KEY` (save this immediately - you can't view it again!)
   - Note: You can have multiple access keys

## Step 4: Create a Bucket (if not created yet)

### Via Vultr Dashboard:
1. In your Object Storage instance, click **Buckets**
2. Click **Create Bucket**
3. Enter a unique bucket name (e.g., `jobreels-videos`)
4. Select a region (should match your endpoint region)
5. Click **Create Bucket**

### Via S3 Client (optional):
You can also use the AWS CLI or boto3 to create buckets programmatically.

## Step 5: Update Your .env File

Add these variables to your `.env` file:

```bash
# Vultr Object Storage (S3-compatible)
VULTR_ENDPOINT=https://ewr1.vultrobjects.com  # Replace with your region
VULTR_ACCESS_KEY=your_access_key_here
VULTR_SECRET_KEY=your_secret_key_here
VULTR_BUCKET=your_bucket_name
```

## Step 6: Test the Connection

Once you've updated your `.env` file:

1. **Restart your services:**
   ```bash
   docker compose down
   docker compose up --build -d
   ```

2. **Test the connection:**
   ```bash
   bash scripts/test_connections.sh
   ```

   Or test manually:
   ```bash
   curl http://localhost:8000/health/storage | python3 -m json.tool
   ```

## Troubleshooting

### "Bucket not found" error:
- Double-check your `VULTR_BUCKET` name (case-sensitive)
- Ensure the bucket exists in the same region as your endpoint
- Try listing buckets first: The `/health/storage` endpoint will show all available buckets

### "Invalid credentials" error:
- Verify your `VULTR_ACCESS_KEY` and `VULTR_SECRET_KEY` are correct
- Make sure there are no extra spaces or quotes in your `.env` file
- Access keys might take a few seconds to become active after creation

### "Connection timeout" error:
- Check that your endpoint URL is correct (including `https://`)
- Verify your network/firewall allows outbound HTTPS connections
- Ensure you're using the correct region endpoint for your bucket

### Testing with AWS CLI (optional):
If you have AWS CLI installed, you can test with:
```bash
aws s3 ls --endpoint-url https://ewr1.vultrobjects.com \
  --access-key-id YOUR_ACCESS_KEY \
  --secret-access-key YOUR_SECRET_KEY s3://YOUR_BUCKET/
```

## Security Notes

- **Never commit** your `.env` file to git (it's in `.gitignore`)
- Access keys have full permissions to your Object Storage instance
- Rotate keys periodically for security
- Use different keys for development and production if possible
- Consider using IAM policies if Vultr supports them in the future

## Next Steps

Once your Object Storage is connected:
- You can upload files using boto3 in your Python services
- The `/health/storage` endpoint will verify connectivity
- Object Storage is perfect for storing video files, images, and other large assets
