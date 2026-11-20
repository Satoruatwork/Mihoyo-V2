FROM python:3.13-slim

# Stream logs immediately (no buffering) and don't write .pyc files.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application package: includes commands/, services/, api/, database/, cache/,
# renderer/, models/, utils/, translations/locales/*.json and resources/*.json —
# every runtime module and bundled data file the bot needs.
COPY bot ./bot

# Bundled static assets (card template, welcome image, placeholder dirs).
# assets/fonts and assets/characters are downloaded at runtime (see .dockerignore),
# so create them up front to guarantee a writable target for the bootstrap step.
COPY assets ./assets
RUN mkdir -p assets/fonts assets/characters

# BOT_TOKEN and REDIS_URL are provided by the deployment platform (Railway/Render)
# as environment variables — never baked into the image.
CMD ["python", "-m", "bot.main"]
