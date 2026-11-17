#!/bin/sh
# Runs as root at start: makes the app's writable folders in /tmp (owned by www-data) and
# writes nginx's CORS allow-list from the app's settings, then starts supervisord.
set -eu
mkdir -p "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
chown www-data:www-data "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
python -m app.api.nginx_cors > /tmp/nginx_cors.conf
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
