#!/bin/bash
#
# Launcher script for E-Paper DND Display
# Environment variables are loaded from dnd-display.env by systemd
# If running manually, source the env file first or set the variables in your shell
#

cd "$HOME/epaper-dnd"

# Activate virtual environment (required for Raspberry Pi OS Bookworm+)
# Comment out the line below if you installed dependencies system-wide (see README)
source "$HOME/dnd-venv/bin/activate"

python3 epaper_dnd.py
