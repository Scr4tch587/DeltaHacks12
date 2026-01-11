FROM python:3.11-slim

WORKDIR /app

# Install ffmpeg for future video processing/validation and curl for healthchecks
RUN apt-get update && \
    apt-get install -y ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast parallel dependency installation
RUN pip install --no-cache-dir uv

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY app/ app/

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
