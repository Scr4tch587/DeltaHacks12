FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create temp directory
RUN mkdir -p /tmp/generator_output

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV TEMP_OUTPUT_DIR=/tmp/generator_output

# Health check - just verify the process is running
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD pgrep -f "python.*worker.py" || exit 1

# Run the worker
CMD ["python", "-m", "app.worker"]
