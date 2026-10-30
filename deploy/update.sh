#!/usr/bin/env sh
# Deploy the latest commit, as root on the server: the built bundle is committed, so nothing is built here.
set -eu
cd "$(dirname "$0")/.."
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
systemctl restart xtip
systemctl --no-pager status xtip | head -5
