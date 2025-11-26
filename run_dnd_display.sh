#!/bin/bash
#
# Launcher script for E-Paper DND Display
# Edit the values below with your Home Assistant details
#

export HA_BASE_URL="http://YOUR_HA_IP:8123"
export HA_TOKEN="your-long-lived-token-here"
export HA_ENTITY_ID="input_boolean.dnd_status"
export HA_MIN_REFRESH_SECONDS=10

cd "$HOME/epaper-dnd"

# Activate virtual environment (required for Raspberry Pi OS Bookworm+)
# Comment out the line below if you installed dependencies system-wide (see README)
source "$HOME/dnd-venv/bin/activate"

python3 epaper_dnd.py
