#!/bin/bash
source /opt/anaconda3/etc/profile.d/conda.sh
conda activate truman
cd "$(dirname "$0")"
python truman/main.py 2>/dev/null
