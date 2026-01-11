# DeltaHacks12 - JobReels

A hackathon-ready scaffold optimized for:
- **MongoDB Atlas** as the ONLY database (no local Mongo container)
- Deployment to a single **Vultr VM** using Docker Compose
- Optional **Tailscale** integration to keep services private
- Minimal **Expo** frontend that can be tested with Expo Go

## Architecture

- **Backend**: FastAPI service on port 8000 (health endpoint only)
- **Headless Service**: FastAPI service on port 8001 (health endpoint only)
- **Video Service**: FastAPI service on port 8002 (health endpoint only)
- **Frontend**: Expo React Native app with health status display

All services are ready to connect to MongoDB Atlas but currently only implement `/health` endpoints.

## Local Development

### Prerequisites
- Docker and Docker Compose installed
- Node.js and npm (for Expo frontend)

### Setup

1. **Create environment file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and set your MongoDB Atlas connection string:**
   ```
   MONGODB_URI=mongodb+srv://USER:PASSWORD@CLUSTER.mongodb.net/?retryWrites=true&w=majority
   MONGODB_DB=app
   ```

3. **Start all services:**
   ```bash
   docker compose up --build
   ```

4. **Test health endpoints:**
   ```bash
   curl http://localhost:8000/health  # Backend
   curl http://localhost:8001/health  # Headless
   curl http://localhost:8002/health  # Video
   ```

   All should return: `{"status":"ok"}`

5. **Run the frontend:**
   ```bash
   cd frontend
   npm install
   npx expo start --tunnel
   ```

   - Scan the QR code with Expo Go app
   - Update `frontend/src/config.js` to point at your laptop's local IP for local development

## Vultr Deployment

### Initial Setup

1. **SSH into your Vultr VM** (Ubuntu recommended)

2. **Run the setup script:**
   ```bash
   bash <(curl -s https://raw.githubusercontent.com/yourusername/yourrepo/main/scripts/vultr_setup.sh)
   ```
   Or manually copy and run:
   ```bash
   bash scripts/vultr_setup.sh
   ```

3. **Clone this repository:**
   ```bash
   git clone <your-repo-url>
   cd DeltaHacks12
   ```

4. **Create `.env` file:**
   ```bash
   cp .env.example .env
   nano .env  # Edit and set MONGODB_URI
   ```

5. **Start services in production mode:**
   ```bash
   docker compose -f docker-compose.prod.yml up -d --build
   ```

6. **Verify services are running:**
   ```bash
   docker compose -f docker-compose.prod.yml ps
   curl http://localhost:8000/health
   ```

### Production Configuration

- **Backend** is exposed publicly on port 8000
- **Headless** and **Video** services are only accessible internally (bound to 127.0.0.1)
- All services have `restart: unless-stopped` policy
- Services automatically restart on VM reboot

## Frontend Configuration

The Expo frontend displays health status for all three services.

1. **For local development:**
   - Update `frontend/src/config.js` with your laptop's local IP
   - Example: `http://192.168.1.100:8000`

2. **For production:**
   - Update `frontend/src/config.js` with your Vultr public IP
   - Example: `http://YOUR_VULTR_IP:8000`
   - Or use Tailscale DNS names if using Tailscale mode

3. **Run with tunnel:**
   ```bash
   cd frontend
   npm install
   npx expo start --tunnel
   ```

See `frontend/README.md` for more details.

## Project Structure

```
/
  docker-compose.yml          # Development compose file
  docker-compose.prod.yml     # Production compose file (Vultr)
  .env.example                # Environment variables template
  README.md                   # This file

  frontend/                   # Expo React Native app
    package.json
    app.json
    App.js
    src/config.js
    README.md

  backend/                    # Main FastAPI backend
    Dockerfile
    requirements.txt
    app/main.py

  services/
    headless/                 # Headless service
      Dockerfile
      requirements.txt
      app/main.py
    video/                    # Video service
      Dockerfile
      requirements.txt
      app/main.py

  scripts/
    vultr_setup.sh           # Vultr VM setup script
    tailscale_setup.sh       # Tailscale setup instructions
```

## Health Endpoints

All services expose a single `/health` endpoint:

- `GET /health` → Returns `{"status":"ok"}`

Test locally:
- `http://localhost:8000/health` (Backend)
- `http://localhost:8001/health` (Headless)
- `http://localhost:8002/health` (Video)

## Notes

- MongoDB Atlas is the only database - no local Mongo container
- All services are minimal and hackathon-ready
- Environment variables are loaded but MongoDB connection is not yet implemented
- Production compose file keeps headless/video services private by default
- Tailscale integration is optional but fully supported

## Troubleshooting

**Services won't start:**
- Check that `.env` file exists and has valid `MONGODB_URI`
- Verify Docker is running: `docker ps`
- Check logs: `docker compose logs <service-name>`

**Frontend can't connect:**
- Verify services are running: `docker compose ps`
- Check your IP address in `frontend/src/config.js`
- Ensure firewall allows connections on ports 8000-8002 (dev) or 8000 (prod)

**Tailscale not working:**
- Verify `TS_AUTHKEY` is set in `.env`
- Check Tailscale service is uncommented in `docker-compose.prod.yml`
- View logs: `docker compose -f docker-compose.prod.yml logs tailscale`
