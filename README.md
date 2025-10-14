# Captr for macOS

**Captr** is a screen recording and computer interaction capture tool that records keyboard/mouse input, screen video, DOM snapshots, and accessibility trees. Perfect for creating datasets to train and evaluate computer-use AI models.

![Captr Logo](assets/captr.png)

## Features

- **Screen & Input Recording:** Captures all mouse movements, clicks, scrolls, and keyboard inputs with precise timestamps
- **OBS Integration:** Automatic screen recording via OBS Studio
- **DOM Capture:** Automatically captures webpage structure from Chromium browsers (Chrome, Edge, Brave, etc.)
- **Accessibility Trees:** Records macOS accessibility information from native applications
- **System Metadata:** Captures detailed system information (OS, screen resolution, installed apps, etc.)
- **Privacy Controls:** Pause/resume recording to hide sensitive information
- **Playback:** Replay recorded sessions to verify captures

## Installation

### Option 1: Download Pre-built App (Recommended)

1. Download the latest `Captr.dmg` from the [Releases](../../releases) page
2. Open the DMG file and drag `Captr.app` to your Applications folder
3. Install and configure OBS Studio (see [OBS Setup](#obs-setup))
4. Grant required macOS permissions when prompted

### Option 2: Build from Source

Requirements: Python ≥3.11, OBS Studio

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/Captr_MacOS.git
cd Captr_MacOS

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build the app
python build.py
```

The built app will be in the `dist` folder as `Captr.dmg`.

## OBS Setup

Captr requires OBS Studio for screen recording:

1. Download and install [OBS Studio](https://obsproject.com/)
2. Open OBS and go to **Tools → WebSocket Server Settings**
3. Enable **WebSocket server** and disable **Authentication**
4. Add a **macOS Screen Capture** source in OBS
5. Close OBS (Captr will control it automatically)

For detailed instructions, see [OBS_SETUP.md](OBS_SETUP.md).

## macOS Permissions

Captr needs these permissions to function:

1. **Accessibility:** `System Settings → Privacy & Security → Accessibility`
   - Required for recording keyboard inputs and playing back actions
2. **Input Monitoring:** `System Settings → Privacy & Security → Input Monitoring`
   - Required for keyboard capture
3. **Screen Recording:** `System Settings → Privacy & Security → Screen Recording`
   - Required by OBS for screen capture

macOS will prompt for these permissions on first run.

## Usage

### Recording

1. Launch Captr from Applications
2. Click **Start Recording**
3. Perform your computer tasks
4. Use **Pause/Resume** to hide sensitive information (passwords, credit cards, etc.)
5. Click **Stop Recording**
6. Optionally name and describe your recording

Recordings are saved to `~/Documents/Captr_Recordings/`.

### DOM Capture (Optional)

To capture webpage DOM snapshots:

1. Click **Launch Browser for DOM Capture** in Captr
2. Select your preferred Chromium browser (Chrome, Edge, Brave, etc.)
3. Click **Launch**
4. Use the launched browser for web browsing during recording

DOM snapshots will be automatically captured when you click or navigate. See [DOM_CAPTURE_SETUP.md](DOM_CAPTURE_SETUP.md) for details.

### Playback

- **Play Latest Recording:** Replays the most recent recording
- **Play Custom Recording:** Choose any recording to replay
- Press `Shift+Esc` to stop playback

## Recording Format

Each recording creates a folder in `~/Documents/Captr_Recordings/` containing:

- `events.jsonl` - All keyboard/mouse actions with timestamps
- `metadata.json` - System information
- `*.mp4` - Screen recording video from OBS
- `dom_snaps/` - DOM snapshots from web pages (if DOM capture enabled)
- `a11y_snaps/` - Accessibility tree captures from native apps
- `README.md` - Optional recording description

### Sample Event Format

```json
{"time_stamp": 1234567.89, "action": "move", "x": 100.0, "y": 200.0}
{"time_stamp": 1234568.01, "action": "click", "x": 100.0, "y": 200.0, "button": "left", "pressed": true}
{"time_stamp": 1234568.15, "action": "key", "key": "a", "pressed": true}
```

## Troubleshooting

### DOM Captures Not Working

Run the diagnostic tool:
```bash
cd tools
python3 check_recording.py
```

Make sure you're using a browser launched through Captr's **Launch Browser** feature.

### App Crashes or Permissions Issues

Check detailed logs:
```bash
open dist/Captr.app --stdout-path=/tmp/captr.log --stderr-path=/tmp/captr_err.log
cat /tmp/captr.log
```

### Other Issues

See [DOM_CAPTURE_SETUP.md](DOM_CAPTURE_SETUP.md) for DOM/accessibility tree troubleshooting.

## Known Limitations

- After many playbacks, a segfault may occur (restart Captr)
- Mouse input not captured in video games that use raw input
- Google Docs and similar canvas-based web apps have limited DOM capture (by design for privacy)
- Banking sites may limit DOM capture content due to security policies

## Development

### Running from Source

```bash
source venv/bin/activate
python main.py
```

### Utility Scripts

Located in `tools/`:
- `launch_chrome_debug.py` - Launch browsers with debugging enabled
- `check_recording.py` - Verify recordings and diagnose issues
- `debug_accessibility.py` - Test accessibility API access
- `debug_chrome_cdp.py` - Test Chrome DevTools Protocol connection

## Attribution

Captr is derived from [DuckTrack](https://github.com/TheDuckAI/DuckTrack) by DuckAI, released under the MIT License. We've added significant enhancements including DOM capture, accessibility trees, enhanced macOS support, and improved debugging tools.

See [LICENSE](LICENSE) for full details.

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

**Created by Anais Howland at Paradigm Shift AI** | Based on DuckTrack by DuckAI
