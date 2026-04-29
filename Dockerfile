FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/hf_cache \
    PYTHONPATH=/app

# Build deps for spaCy/torch wheels + tini for a clean PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        tini \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && python -m spacy download pt_core_news_lg

# Non-root user (UID 1000 matches the host dev user); /hf_cache is a named
# volume so model weights survive image rebuilds.
RUN useradd -u 1000 -m -s /bin/bash app \
    && mkdir -p /hf_cache /app \
    && chown -R app:app /hf_cache /app

USER app

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
