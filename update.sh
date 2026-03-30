#!/usr/bin/env bash

set -euo pipefail

git add .
git commit -m "chore: update" -s
git push
