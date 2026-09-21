#!/bin/sh
# The production compose file gives this unprivileged, read-only service a
# tmpfs at /run.  Do not add a fallback to the public image filesystem.
set -eu

if [ "${LEGAL_RENDER_ENABLED:-false}" != "true" ]; then
    echo >&2 "LEGAL_RENDER_ENABLED must be true for this image"
    exit 1
fi

exec python3 /opt/melpis/render_legal_pages.py \
    --template-dir /opt/melpis/legal-templates \
    --output-dir /run/melpis-legal
