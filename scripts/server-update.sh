#!/usr/bin/env bash
# Run ON THE SERVER to install the latest pushed code. See docs/DEPLOY-SERVER.md.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

cd /opt/seqnce
git pull --ff-only

(cd backend && uv sync --no-dev)
(cd frontend && npm ci && npm run build)

sudo systemctl restart seqnce-backend seqnce-web
sleep 10
curl -fs http://127.0.0.1:8000/api/health && echo
echo "Updated."
