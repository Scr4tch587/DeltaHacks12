# Vultr VM Setup and Deployment Guide

Complete step-by-step guide to deploy your application to a Vultr VM.

## Prerequisites

- Vultr VM instance created (Ubuntu 20.04 or 22.04 recommended)
- SSH access to your VM (IP address and root/ubuntu credentials)
- Your MongoDB Atlas connection string
- (Optional) Vultr Object Storage credentials

## Step 1: Connect to Your Vultr VM

### Option A: Using the helper script
```bash
# From your local machine (in the project directory)
bash scripts/connect_vultr.sh YOUR_VULTR_IP
# or with a specific user
bash scripts/connect_vultr.sh YOUR_VULTR_IP ubuntu
```

### Option B: Manual SSH
```bash
ssh root@YOUR_VULTR_IP
# or
ssh ubuntu@YOUR_VULTR_IP
```

## Step 2: Set Up Docker on the VM

Once connected to your VM, run:

```bash
# Install Docker and Docker Compose
bash <(curl -s https://raw.githubusercontent.com/Doomsy1/DeltaHacks12/main/scripts/vultr_setup.sh)
```

Or if you've already cloned the repo:
```bash
bash scripts/vultr_setup.sh
```

**Note:** After adding yourself to the docker group, you may need to log out and back in, or run docker commands with `sudo` temporarily.

Verify installation:
```bash
docker --version
docker compose version
```

## Step 3: Clone Your Repository

On your Vultr VM:

```bash
# Install git if not already installed
sudo apt-get update
sudo apt-get install -y git

# Clone your repository
git clone <your-repo-url>
cd DeltaHacks12

# Or if you prefer, upload your project using SCP from local machine:
# (Run this from your LOCAL machine)
# scp -r /path/to/DeltaHacks12 root@YOUR_VULTR_IP:/root/
```

## Step 4: Configure Environment Variables

```bash
# Copy the example file
cp .env.example .env

# Edit with your favorite editor
nano .env
# or
vi .env
```

Fill in at minimum:
```bash
MONGODB_URI=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB=app
```

If using Object Storage (optional):
```bash
VULTR_ENDPOINT=https://ewr1.vultrobjects.com
VULTR_ACCESS_KEY=your_access_key
VULTR_SECRET_KEY=your_secret_key
VULTR_BUCKET=your_bucket_name
```

## Step 5: Deploy Services

Run the deployment script:
```bash
bash scripts/deploy.sh
```

Or manually:
```bash
# Build and start services in production mode
docker compose -f docker-compose.prod.yml up -d --build

# Check status
docker compose -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

## Step 6: Test Your Deployment

### Test health endpoints:
```bash
# Backend health
curl http://localhost:8000/health | python3 -m json.tool

# MongoDB connection
curl http://localhost:8000/health/db | python3 -m json.tool

# Object Storage (if configured)
curl http://localhost:8000/health/storage | python3 -m json.tool

# Or use the test script
bash scripts/test_connections.sh
```

### Test from outside the VM:
```bash
# From your local machine
curl http://YOUR_VULTR_IP:8000/health
```

## Step 7: Configure Firewall (if needed)

If you can't access the services from outside:

```bash
# Ubuntu UFW firewall
sudo ufw allow 8000/tcp
sudo ufw status

# Or if using iptables directly
sudo iptables -A INPUT -p tcp --dport 8000 -j ACCEPT
sudo iptables-save
```

Vultr also has a firewall in the dashboard - make sure port 8000 is open there too.

## Step 8: Set Up Automatic Startup (Optional)

Your services should already restart automatically (`restart: unless-stopped`), but to ensure Docker starts on boot:

```bash
# Docker service should already be enabled, but verify:
sudo systemctl enable docker
sudo systemctl status docker
```

## Monitoring and Maintenance

### View logs:
```bash
# All services
docker compose -f docker-compose.prod.yml logs

# Specific service
docker compose -f docker-compose.prod.yml logs backend

# Follow logs
docker compose -f docker-compose.prod.yml logs -f backend
```

### Restart services:
```bash
docker compose -f docker-compose.prod.yml restart
# or specific service
docker compose -f docker-compose.prod.yml restart backend
```

### Update and redeploy:
```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose -f docker-compose.prod.yml up -d --build
```

### Check resource usage:
```bash
docker stats
```

## Troubleshooting

### Services won't start:
- Check logs: `docker compose -f docker-compose.prod.yml logs`
- Verify `.env` file exists and has correct values
- Check Docker is running: `sudo systemctl status docker`
- Ensure you have enough disk space: `df -h`

### Can't connect from outside:
- Check firewall rules (both on VM and Vultr dashboard)
- Verify services are running: `docker compose -f docker-compose.prod.yml ps`
- Test locally first: `curl http://localhost:8000/health`
- Check if port is listening: `sudo netstat -tlnp | grep 8000`

### MongoDB connection fails:
- Verify `MONGODB_URI` is correct in `.env`
- Check MongoDB Atlas Network Access - add your Vultr VM's IP to whitelist
- Test connection from VM: `curl http://localhost:8000/health/db`

### Object Storage connection fails:
- See `scripts/vultr_object_storage_setup.md` for detailed troubleshooting
- Verify credentials are correct (no extra spaces)
- Check endpoint region matches your bucket region

## Security Recommendations

1. **Use a non-root user** for running services:
   ```bash
   adduser deploy
   usermod -aG docker deploy
   # Then SSH as deploy user and run commands
   ```

2. **Set up SSH keys** instead of password authentication:
   ```bash
   # On local machine
   ssh-copy-id root@YOUR_VULTR_IP
   ```

3. **Configure firewall** to only allow necessary ports:
   ```bash
   sudo ufw default deny incoming
   sudo ufw default allow outgoing
   sudo ufw allow ssh
   sudo ufw allow 8000/tcp
   sudo ufw enable
   ```

4. **Keep system updated**:
   ```bash
   sudo apt-get update
   sudo apt-get upgrade -y
   ```

5. **Monitor logs** regularly for suspicious activity

## Next Steps

- Set up domain name and point it to your Vultr IP
- Configure SSL/TLS with Let's Encrypt (optional)
- Set up monitoring/alerting (optional)
- Configure backups for your data
- Set up Tailscale for private access (see `scripts/tailscale_setup.sh`)
