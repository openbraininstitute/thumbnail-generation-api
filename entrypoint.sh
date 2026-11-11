#!/bin/sh
# Container start, as root, before supervisord starts nginx and the app (Dockerfile CMD).
#
# 1. Folders the app writes, owned by the user it runs as (www-data, supervisord.conf). In ECS,
#    /tmp is a fresh volume whose owner is not known in advance: making them here works either way.
#    MPLCONFIGDIR: matplotlib's font cache. /tmp/app: HOME, where kaleido's Chromium writes.
# 2. nginx's CORS allow-list, from the same settings as the app (app/api/nginx_cors.py).
set -eu
mkdir -p "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
chown www-data:www-data "${MPLCONFIGDIR:-/tmp/matplotlib}" /tmp/app
python -m app.api.nginx_cors > /tmp/nginx_cors.conf
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
