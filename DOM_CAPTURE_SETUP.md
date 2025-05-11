# DOM and Accessibility Tree Capture Setup Guide

DuckTrack can capture DOM snapshots from web browsers and accessibility trees from native applications. These captures provide valuable context for your screen recordings. This guide will help you set up and troubleshoot these features.

## Requirements

1. **For DOM Capture:**
   - A Chromium-based browser (Chrome, Edge, Brave, Opera, Vivaldi, etc.)
   - The browser must be started with remote debugging enabled
   
2. **For Accessibility Tree Capture:**
   - macOS only
   - Accessibility permissions must be granted to DuckTrack

## Setting Up Browsers for DOM Capture

For DuckTrack to capture DOM snapshots from Chromium-based browsers, at least one browser must be running with remote debugging enabled:

### Option 1: Use our helper script (Recommended)

We've included a helper script that can launch any supported browser with debugging enabled:

```bash
# From the DuckTrack directory:
python3 launch_chrome_debug.py
```

**Advanced usage:**
```bash
# List available browsers
python3 launch_chrome_debug.py --list

# Launch specific browser
python3 launch_chrome_debug.py --browser edge

# Use different port (if 9222 is already in use)
python3 launch_chrome_debug.py --port 9223

# Launch browser with specific URL
python3 launch_chrome_debug.py --url https://github.com
```

### Option 2: Manual launch

If you prefer to launch browsers manually, here are the commands for different platforms:

#### macOS:
```bash
# Chrome
open -a "Google Chrome" --args --remote-debugging-port=9222

# Microsoft Edge
open -a "Microsoft Edge" --args --remote-debugging-port=9222

# Brave Browser
open -a "Brave Browser" --args --remote-debugging-port=9222
```

#### Windows:
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
"C:\Program Files\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222
"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe" --remote-debugging-port=9222
```

#### Linux:
```bash
google-chrome --remote-debugging-port=9222
microsoft-edge --remote-debugging-port=9222
brave-browser --remote-debugging-port=9222
```

## How DuckTrack Detects Browsers

DuckTrack will automatically try to find a suitable browser for DOM captures:

1. It first tries the default port (9222)
2. If that fails, it checks other common debugging ports (9223, 9224, 9333, 8080)
3. It will use the first available browser it finds

This means you don't need to configure anything - as long as at least one browser is running with debugging enabled, DuckTrack should be able to capture DOM snapshots.

## When DOM & Accessibility Captures Occur

DuckTrack intelligently captures DOM snapshots and accessibility trees at key moments:

### DOM Snapshot Triggers

- **Mouse Clicks:** Immediate capture when clicking in a browser window
- **Delayed Capture:** 3-second delayed capture after clicks to catch page transitions
- **Key Presses:** When pressing navigation keys (Enter, Tab, arrows, etc.)
- **Page Changes:** When navigating to a new URL or site
- **Periodic Capture:** Automatic capture every 30 seconds

### Accessibility Tree Triggers (macOS)

- **Mouse Clicks:** When clicking in native applications
- **Key Presses:** When pressing navigation or modifier keys
- **Delayed Key Capture:** After key release to capture resulting UI changes

### Smart Deduplication

To prevent excessive storage use, DuckTrack implements smart deduplication:
- Content-based hashing to avoid saving identical snapshots
- Cooldown periods between captures (2-5 seconds)
- Detection of similar URLs to prevent near-duplicate captures
- Levenshtein distance comparison for URLs to identify similar pages

## Granting Accessibility Permissions (macOS)

For DuckTrack to capture accessibility trees from native apps on macOS:

1. Go to System Preferences > Security & Privacy > Privacy
2. Select "Accessibility" from the left panel
3. Click the lock to make changes (requires admin password)
4. Check the box next to DuckTrack.app
5. Restart DuckTrack if it's already running

## Troubleshooting

### DOM Snapshots Not Being Captured

1. **Check if any browser has debugging enabled:**
   ```bash
   python3 debug_chrome_cdp.py
   ```
   This will attempt to connect to any available browser.

2. **Common issues:**
   - No browsers started with the `--remote-debugging-port` flag
   - Firewalls blocking access to the debugging ports
   - Antivirus software preventing the connections
   - Custom browser configurations that disable remote debugging

3. **Check the logs:**
   - Look for messages indicating connection attempts to different ports
   - Check for "CDP connection failed" or similar error messages
   - Verify that the browser is detected as the focused application

### Accessibility Trees Not Being Captured

1. **Check if your app has accessibility permissions:**
   ```bash
   python3 debug_accessibility.py
   ```
   This will test if DuckTrack can access the accessibility API.

2. **Common issues:**
   - Accessibility permissions not granted to DuckTrack
   - The application you're trying to capture doesn't properly support accessibility
   - The PyObjC library is not properly installed or working

3. **Check the logs:**
   - Look for warnings about "Accessibility permissions"
   - Check for specific errors related to "AXUIElement" or accessibility API functions

## Storage Location

By default, the captures are stored in a `dom_snaps` directory within each recording folder:

```
[recording_timestamp]/
├── dom_snaps/
│   ├── a11y_click_123456.json
│   ├── dom_click_123456.mhtml
│   └── ...
├── events.jsonl
└── ...
```

If DuckTrack cannot create this directory, it will fallback to `~/DuckTrack_dom_snaps/`.

## Additional Tools

We've included several debugging tools to help troubleshoot capture issues:

- `debug_chrome_cdp.py` - Tests Chrome DevTools Protocol connectivity with any available browser
- `debug_accessibility.py` - Tests macOS Accessibility API functionality
- `launch_chrome_debug.py` - Launches any Chromium-based browser with debugging enabled
- `check_recording.py` - Examines recordings to check if DOM and accessibility captures are working

## Need More Help?

If you're still having issues with DOM or accessibility tree capture, please check the application logs or submit an issue on our GitHub repository with the specific error messages you're seeing. 