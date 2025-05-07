#!/bin/bash
# Simple script to launch Chrome with debugging enabled on port 9222
# while preserving the user's existing profile

echo "Checking if Chrome is already running..."
pgrep "Google Chrome" > /dev/null
if [ $? -eq 0 ]; then
    echo "Chrome is already running. Closing Chrome..."
    killall "Google Chrome" > /dev/null 2>&1
    sleep 1
fi

echo "Launching Chrome with debugging enabled on port 9222..."
open -a "Google Chrome" --args --remote-debugging-port=9222

echo "Checking if Chrome debugging port is available..."
sleep 2
nc -z 127.0.0.1 9222
if [ $? -eq 0 ]; then
    echo "✅ Success! Chrome is now running with debugging enabled on port 9222."
    echo "You can now open DuckTrack and it should detect Chrome automatically."
else
    echo "❌ Failed to verify Chrome debugging port. Please try again."
fi 