#!/bin/sh
# Nightly reset for the public demo.
# Writes the same sample the app uses (demo_data.build_demo_story):
# six invoices across months and statuses, not a separate shorter seed.
# Requires DEMO_MODE=1, which the demo container already sets.
set -eu
cd "$(dirname "$0")/.."
if command -v docker >/dev/null 2>&1 && docker compose ps --status running --services 2>/dev/null | grep -qx property-manager; then
  exec docker compose exec -T property-manager python app.py reset-demo
fi
exec python3 app.py reset-demo
