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

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# The sed strips Windows line endings in case the repo was checked out on Windows.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home --home-dir /nonexistent coolin \
    && mkdir -p /dingo \
    && chown coolin:coolin /dingo

# Builds, assets, the game catalog and the beta key live here.
VOLUME ["/dingo"]
EXPOSE 2665

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ['COOLIN_PORT'], timeout=4)"

# The entrypoint fixes /dingo ownership, then runs the server as the unprivileged "coolin" user.
ENTRYPOINT ["docker-entrypoint.sh"]

# One process, several threads: rate limits and failed-login tracking are kept in memory,
# so they must be shared by every request. Long timeout for big build uploads.
# No control socket: it's a gunicorn admin feature this app doesn't use, and it needs a writable home directory.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${COOLIN_PORT} --workers 1 --threads 8 --timeout 600 --no-control-socket --access-logfile - server:app"]
