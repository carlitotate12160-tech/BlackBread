#!/bin/bash
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

# Insert PATH export before the interactive check in .bashrc
# Check if already fixed
if grep -q "Set PATH for non-interactive SSH" ~/.bashrc; then
    echo "ALREADY_FIXED"
else
    # Insert before the "# If not running interactively" line
    sed -i '/^# If not running interactively/i\
# Set PATH for non-interactive SSH shells (fixes empty PATH on ssh oracle-alpha cmd)\
export PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin\
' ~/.bashrc
    echo "FIXED"
fi

head -15 ~/.bashrc
