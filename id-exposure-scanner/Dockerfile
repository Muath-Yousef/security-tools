FROM python:3.12-slim

LABEL maintainer="Security Lab"
LABEL description="ID Exposure Scanner — Isolated Testing Environment"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create output directory
RUN mkdir -p /app/output

# Default entrypoint
ENTRYPOINT ["python", "main.py"]
