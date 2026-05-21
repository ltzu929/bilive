#!/bin/bash
source ~/miniforge/etc/profile.d/conda.sh
conda activate bilive
cd /mnt/win/bilive
export PYTHONPATH=./src
export BILIVE_VIDEOS_DIR=/mnt/win/bilive/Videos
exec python -m uvicorn src.dashboard.app:api --host 0.0.0.0 --port 2234
