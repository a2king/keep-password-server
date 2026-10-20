#!/bin/sh
set -e
cd /app
python -m app.dbutil
exec gunicorn -b 0.0.0.0:8000 -w 2 --preload --timeout 60 wsgi:app
