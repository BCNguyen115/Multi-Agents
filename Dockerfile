# Sử dụng Python 3.11 slim để tối ưu kích thước
FROM python:3.11-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Biến môi trường PYTHONPATH để Python nhận diện thư mục src
ENV PYTHONPATH=/app

# Cài đặt các gói hệ thống cần thiết (nếu có)
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-install spaCy model cho MemoryManager / mem0ai
RUN python -m spacy download en_core_web_sm || pip install --no-cache-dir https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl || true

# Cài đặt Playwright Chromium & System Dependencies cho Crawl4AI
RUN playwright install --with-deps chromium

# Copy mã nguồn dự án
COPY src/ ./src/

# Copy ingestion script
COPY run_ingestion.py .

# (Lệnh CMD sẽ được ghi đè trong docker-compose.yml tùy thuộc vào service)
