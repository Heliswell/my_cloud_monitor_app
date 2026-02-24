#!/usr/bin/env bash
set -euo pipefail

COMMIT_MSG="${1:-update}"

git init
git add .
git commit -m "$COMMIT_MSG"
git branch -M main
git push origin main
