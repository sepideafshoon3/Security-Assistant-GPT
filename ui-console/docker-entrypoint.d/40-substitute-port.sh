#!/bin/sh
# Run automatically by the official nginx image's own entrypoint, before
# nginx starts, for every executable script in /docker-entrypoint.d/.
#
# Render (and most Docker PaaS hosts) assign a dynamic port via $PORT --
# nginx.conf can't read env vars directly, so we substitute a literal
# placeholder instead of using nginx's built-in envsubst templating,
# which would also zero out nginx's own $uri/$host/etc (those aren't
# env vars, so blind envsubst replaces them with an empty string too).
set -e

PORT="${PORT:-80}"
sed -i "s/__PORT__/${PORT}/" /etc/nginx/conf.d/default.conf
