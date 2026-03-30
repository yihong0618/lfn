#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")"
uv tool install . --reinstall
