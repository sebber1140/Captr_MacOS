# DOM and Accessibility Tree Capture Setup Guide

DuckTrack can capture DOM snapshots from web browsers and accessibility trees from native applications. These captures provide valuable context for your screen recordings. This guide will help you set up and troubleshoot these features.

## Requirements

1. **For DOM Capture:**
   - A Chromium-based browser (Chrome, Edge, Brave)
   - The browser must be started with remote debugging enabled
   
2. **For Accessibility Tree Capture:**
   - macOS only
   - Accessibility permissions must be granted to DuckTrack

## Setting Up Chrome for DOM Capture

For DuckTrack to capture DOM snapshots from Chrome (or other Chromium browsers), you must start the browser with remote debugging enabled:

### Option 1: Use our helper script

We've included a helper script to launch Chrome with the correct settings:

```bash
# From the DuckTrack directory:
python3 launch_chrome_debug.py
```

This will automatically find and launch Chrome with debugging enabled.

### Option 2: Manual launch

#### macOS:
```bash
open -a "Google Chrome" --args --remote-debugging-port=9222
```

#### Windows:
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```

#### Linux:
```bash
google-chrome --remote-debugging-port=9222
```

## Granting Accessibility Permissions (macOS)

For DuckTrack to capture accessibility trees from native apps on macOS:

1. Go to System Preferences > Security & Privacy > Privacy
2. Select "Accessibility" from the left panel
3. Click the lock to make changes (requires admin password)
4. Check the box next to DuckTrack.app
5. Restart DuckTrack if it's already running

## Troubleshooting

### DOM Snapshots Not Being Captured

1. **Check if Chrome is running with debugging enabled:**
   ```bash
   python3 debug_chrome_cdp.py
   ```
   This will tell you if Chrome is properly configured.

2. **Common issues:**
   - Chrome not started with `--remote-debugging-port=9222`
   - Another application is using port 9222
   - DuckTrack doesn't have network access to connect to Chrome

3. **Check the logs:**
   - Look for error messages mentioning "CDP connection failed"
   - Verify that Chrome was detected as the focused application

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
   - Check for specific errors related to "AXUIElement" or "kAXValueCGPointType"

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

- `debug_chrome_cdp.py` - Tests Chrome DevTools Protocol connectivity
- `debug_accessibility.py` - Tests macOS Accessibility API functionality
- `launch_chrome_debug.py` - Launches Chrome with debugging enabled

## Need More Help?

If you're still having issues with DOM or accessibility tree capture, please check the application logs or submit an issue on our GitHub repository with the specific error messages you're seeing. 