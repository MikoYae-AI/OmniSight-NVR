FROM python:3.12-slim

# Install system dependencies including ffmpeg for hardware RTSP stream demuxing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements & install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

CMD ["python3", "backend/server.py", "8080"]
