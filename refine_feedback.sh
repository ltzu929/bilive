#!/bin/bash
# Convert dashboard keep feedback into refined upload candidates.

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

source venv/bin/activate
export PYTHONPATH=.:./src

python -m src.burn.feedback_refine "$@"
