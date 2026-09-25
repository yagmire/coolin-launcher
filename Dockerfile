# Coolin Launcher server (server.py + admin panel).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    COOLIN_DATA_DIR=/dingo \
    COOLIN_PORT=2665

WORKDIR /app

COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

# Only what the server needs. assets/ lets the admin panel preview the launcher's built-in graphics.
COPY server.py .
COPY templates/ templates/
COPY static/ static/
COPY assets/ assets/

RUN useradd --system --uid 10001 --home-dir /app coolin \
    && mkdir -p /dingo \
    && chown coolin:coolin /dingo
USER coolin

# Builds, assets, the game catalog and the beta key live here.
VOLUME ["/dingo"]
EXPOSE 2665

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['COOLIN_PORT'], timeout=4)"

# One process, several threads: rate limits and failed-login tracking are kept in memory,
# so they must be shared by every request. Long timeout for big build uploads.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${COOLIN_PORT} --workers 1 --threads 8 --timeout 600 --access-logfile - server:app"]
