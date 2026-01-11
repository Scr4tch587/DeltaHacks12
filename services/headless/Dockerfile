FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install uv for fast parallel dependency installation
RUN pip install uv

COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Install Playwright browsers (chromium for headless automation)
RUN playwright install chromium

COPY app/ app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
