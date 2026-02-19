FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libopencv-dev \
    && rm -rf /var/lib/apt/lists/*

# Install build dependencies first
RUN pip install --no-cache-dir \
    Cython==0.29.36 \
    numpy==1.24.3

# Install tracking packages that need Cython
RUN pip install --no-cache-dir \
    filterpy==1.4.5 \
    scikit-image==0.22.0

RUN pip install --no-cache-dir cython-bbox==0.1.3

RUN pip install --no-cache-dir lap==0.4.0

# Copy requirements
COPY requirements.txt .

# Install remaining Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Create directories
RUN mkdir -p /models /storage/captures /storage/crops /storage/retrain_easyocr

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD celery -A worker.celery_app inspect ping || exit 1

# Run Celery worker
CMD ["celery", "-A", "worker.celery_app", "worker", \
     "--loglevel=info", \
     "--concurrency=2", \
     "-Q", "lpr,tracking,training"]