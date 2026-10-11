#!/bin/sh
set -eu

if [ -n "${ARMS_LICENSE_KEY:-}" ]; then
    exec aliyun-instrument "$@"
fi

exec "$@"
