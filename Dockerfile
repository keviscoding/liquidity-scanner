FROM python:3.12-slim

WORKDIR /app

# Install Node.js 20.x + Chromium runtime dependencies for dev-browser
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libxshmfence1 \
    fonts-liberation fonts-noto-color-emoji \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install dev-browser (headless Chromium for AI agent browsing)
RUN npm install -g dev-browser && dev-browser install

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Create data directory
RUN mkdir -p data/cache data/results

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
