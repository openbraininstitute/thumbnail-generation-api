#!/bin/sh
# Runs as root at start: makes the app's writable folders in /tmp (owned by www-data) and
# writes nginx's CORS allow-list from the app's settings, then starts supervisord.
set -eu
# ECS mounts the /tmp volume root-owned, 0755: the app (www-data) could not write a temp file,
# and neurom writes every SWC to one. 1777 is /tmp's usual mode (anyone writes, deletes own).
chmod 1777 /tmp
mkdir -p "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
chown www-data:www-data "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
python -m app.api.nginx_cors > /tmp/nginx_cors.conf
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
