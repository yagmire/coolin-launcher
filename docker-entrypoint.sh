#!/bin/sh
# Starts as root only to make sure the app user can write to the data volume
# (bind-mounted host folders are usually owned by root), then drops privileges.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$COOLIN_DATA_DIR"
    # Only touches files that aren't already owned by the app user, so restarts stay fast.
    find "$COOLIN_DATA_DIR" ! -user coolin -exec chown coolin:coolin {} +
    exec setpriv --reuid=coolin --regid=coolin --init-groups "$@"
fi

# Already running as a non-root user (e.g. docker run --user): start as-is.
exec "$@"
