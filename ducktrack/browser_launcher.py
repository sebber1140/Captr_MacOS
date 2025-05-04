"""
Browser launcher for DuckTrack

This module handles detection and launching of Chromium-based browsers with debugging enabled.
"""

import os
import sys
import subprocess
import socket
import logging
import webbrowser
import time
from platform import system
from typing import Dict, List, Optional, Tuple

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Default debugging port
DEFAULT_DEBUG_PORT = 9222

# Known Chromium-based browsers and their paths
BROWSERS = {
    'chrome': {
        'name': 'Google Chrome',
        'darwin': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'darwin_app': 'Google Chrome',
        'win32': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        'win32_alt': r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        'linux': '/usr/bin/google-chrome',
    },
    'edge': {
        'name': 'Microsoft Edge',
        'darwin': '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        'darwin_app': 'Microsoft Edge',
        'win32': r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        'win32_alt': r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'linux': '/usr/bin/microsoft-edge',
    },
    'brave': {
        'name': 'Brave Browser',
        'darwin': '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
        'darwin_app': 'Brave Browser',
        'win32': r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
        'win32_alt': r'C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe',
        'linux': '/usr/bin/brave-browser',
    },
    'opera': {
        'name': 'Opera',
        'darwin': '/Applications/Opera.app/Contents/MacOS/Opera',
        'darwin_app': 'Opera',
        'win32': r'C:\Program Files\Opera\launcher.exe',
        'win32_alt': r'C:\Program Files (x86)\Opera\launcher.exe',
        'linux': '/usr/bin/opera',
    },
    'vivaldi': {
        'name': 'Vivaldi',
        'darwin': '/Applications/Vivaldi.app/Contents/MacOS/Vivaldi',
        'darwin_app': 'Vivaldi',
        'win32': r'C:\Program Files\Vivaldi\Application\vivaldi.exe',
        'win32_alt': r'C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe',
        'linux': '/usr/bin/vivaldi-stable',
    },
    'chromium': {
        'name': 'Chromium',
        'darwin': '/Applications/Chromium.app/Contents/MacOS/Chromium',
        'darwin_app': 'Chromium',
        'win32': r'C:\Program Files\Chromium\Application\chrome.exe',
        'win32_alt': r'C:\Program Files (x86)\Chromium\Application\chrome.exe',
        'linux': '/usr/bin/chromium-browser',
    },
}

def find_macos_browsers_via_applescript() -> Dict[str, str]:
    """Find browsers on macOS using AppleScript
    
    Returns:
        Dict[str, str]: Dictionary of detected browsers
    """
    browsers = {}
    
    try:
        import subprocess
        
        # Use AppleScript to list installed applications
        script = """
        tell application "System Events"
            set appList to name of every application process whose visible is true
        end tell
        return appList
        """
        
        cmd = ["osascript", "-e", script]
        result = subprocess.run(cmd, capture_output=True, text=True)
        visible_apps = result.stdout.strip().split(", ")
        
        # Check for common browser names in the list
        browser_mapping = {
            "Google Chrome": "chrome",
            "Chrome": "chrome",
            "Microsoft Edge": "edge",
            "Edge": "edge",
            "Brave Browser": "brave",
            "Brave": "brave",
            "Safari": "safari",
            "Firefox": "firefox",
            "Opera": "opera",
            "Vivaldi": "vivaldi"
        }
        
        for app in visible_apps:
            for browser_name, browser_key in browser_mapping.items():
                if browser_name.lower() in app.lower():
                    browsers[browser_key] = browser_name
                    logging.info(f"Found browser via AppleScript: {browser_name}")
                    break
        
        # If no visible browsers, try to find all installed browsers
        if not browsers:
            script = """
            tell application "Finder"
                set appList to name of every application file of folder "Applications" of startup disk
            end tell
            return appList
            """
            
            cmd = ["osascript", "-e", script]
            result = subprocess.run(cmd, capture_output=True, text=True)
            installed_apps = result.stdout.strip().split(", ")
            
            for app in installed_apps:
                for browser_name, browser_key in browser_mapping.items():
                    if browser_name.lower() in app.lower():
                        browsers[browser_key] = browser_name
                        logging.info(f"Found browser via AppleScript in Applications: {browser_name}")
                        break
    except Exception as e:
        logging.error(f"Error running AppleScript browser detection: {e}")
    
    return browsers

def find_installed_browsers() -> Dict[str, str]:
    """Find installed Chromium-based browsers on the system
    
    Returns:
        Dict[str, str]: Dictionary mapping browser keys to display names
    """
    installed = {}
    logging.info("Searching for installed browsers...")
    
    # On macOS, try to find browsers through spotlight first
    if system() == 'darwin':
        try:
            # Use mdfind to search for Chrome-like browsers through Spotlight
            import subprocess
            cmd = ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome' || kMDItemCFBundleIdentifier == 'com.microsoft.Edge' || kMDItemCFBundleIdentifier == 'com.brave.Browser'"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            app_paths = result.stdout.strip().split('\n')
            
            # Log what we found via Spotlight
            if app_paths and app_paths[0]:
                logging.info(f"Found browsers via Spotlight: {app_paths}")
                for path in app_paths:
                    if path.endswith('.app'):
                        app_name = os.path.basename(path).replace('.app', '')
                        logging.info(f"Detected browser: {app_name} at {path}")
                        if 'Google Chrome' in path or 'Chrome.app' in path:
                            installed['chrome'] = 'Google Chrome'
                        elif 'Microsoft Edge' in path or 'Edge.app' in path:
                            installed['edge'] = 'Microsoft Edge'
                        elif 'Brave' in path or 'Brave Browser.app' in path:
                            installed['brave'] = 'Brave Browser'
        except Exception as e:
            logging.error(f"Error using Spotlight search: {e}")
    
    # Standard directory check (fallback)
    for browser_key, browser_info in BROWSERS.items():
        display_name = browser_info.get('name', browser_key.capitalize())
        
        # For macOS, check if the app exists in standard and common alternate locations
        if system() == 'darwin':
            # Standard location
            app_name = browser_info.get('darwin_app', display_name)
            standard_app_path = f"/Applications/{app_name}.app"
            user_app_path = os.path.expanduser(f"~/Applications/{app_name}.app")
            
            # Log what we're checking
            logging.info(f"Checking for {app_name} at:\n- {standard_app_path}\n- {user_app_path}")
            
            if os.path.exists(standard_app_path):
                logging.info(f"Found {app_name} at {standard_app_path}")
                installed[browser_key] = display_name
            elif os.path.exists(user_app_path):
                logging.info(f"Found {app_name} at {user_app_path}")
                installed[browser_key] = display_name
                
        # For Windows, check both Program Files locations
        elif system() == 'windows' or system() == 'win32':
            main_path = browser_info.get('win32')
            alt_path = browser_info.get('win32_alt')
            
            if main_path and os.path.exists(main_path):
                installed[browser_key] = display_name
            elif alt_path and os.path.exists(alt_path):
                installed[browser_key] = display_name
                
        # For Linux, check standard locations
        elif system().startswith('linux'):
            linux_path = browser_info.get('linux')
            if linux_path and os.path.exists(linux_path):
                installed[browser_key] = display_name
    
    # Log results
    if installed:
        logging.info(f"Detected browsers: {installed}")
    else:
        logging.warning("No browsers detected! Trying to detect any browser...")
        
        # Try AppleScript detection on macOS
        if system() == 'darwin':
            applescript_browsers = find_macos_browsers_via_applescript()
            if applescript_browsers:
                logging.info(f"Found browsers via AppleScript: {applescript_browsers}")
                installed.update(applescript_browsers)
            
        # Last resort for macOS: check if any browser exists
        if system() == 'darwin' and not installed:
            for app in ['Google Chrome', 'Firefox', 'Safari', 'Microsoft Edge', 'Brave Browser']:
                app_path = f"/Applications/{app}.app"
                if os.path.exists(app_path):
                    # Add at least Safari or Firefox even if not fully supported
                    if app == 'Safari':
                        logging.info(f"Found Safari (limited support) at {app_path}")
                        installed['safari'] = 'Safari (limited support)'
                    elif app == 'Firefox':
                        logging.info(f"Found Firefox (limited support) at {app_path}")
                        installed['firefox'] = 'Firefox (limited support)'
                    elif app not in ['Google Chrome', 'Microsoft Edge', 'Brave Browser']:
                        logging.info(f"Found browser {app} at {app_path}")
                        key = app.lower().replace(' ', '_')
                        installed[key] = f"{app}"
    
    return installed

def find_available_port(start_port: int = DEFAULT_DEBUG_PORT, max_attempts: int = 10) -> int:
    """Find an available port for browser debugging
    
    Args:
        start_port: Port to start checking from
        max_attempts: Maximum number of ports to check
        
    Returns:
        int: Available port number, or original port if checking fails
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', port))
            if result != 0:  # Port is available
                return port
    
    # If we couldn't find an available port, return the original
    return start_port

def launch_browser(browser_key: str, port: Optional[int] = None, url: Optional[str] = None) -> Tuple[bool, int, str]:
    """Launch a browser with remote debugging enabled
    
    Args:
        browser_key: Key of the browser to launch
        port: Port to use for remote debugging (will find available port if None)
        url: URL to open in the browser (optional)
        
    Returns:
        Tuple[bool, int, str]: (success, port used, error message if any)
    """
    # Find an available port if not specified
    if port is None:
        port = find_available_port()
    
    # Default URL if not specified
    if url is None:
        url = "about:blank"
    
    # Get browser info
    browser_info = BROWSERS.get(browser_key)
    if not browser_info:
        return False, 0, f"Unknown browser: {browser_key}"
    
    try:
        # For macOS
        if system() == 'darwin':
            app_name = browser_info.get('darwin_app')
            if not app_name:
                return False, 0, f"Could not find app name for {browser_key} on macOS"
            
            # Create a user data directory for the debugging session
            user_data_dir = os.path.expanduser(f"~/Library/Application Support/DuckTrack/Browser_Debug_{port}")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser with debugging enabled
            cmd = [
                'open', '-a', app_name, '--args',
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                url
            ]
            
            logging.info(f"Launching {app_name} with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        # For Windows
        elif system() == 'windows' or system() == 'win32':
            # Find executable path
            exe_path = browser_info.get('win32')
            if not os.path.exists(exe_path):
                exe_path = browser_info.get('win32_alt')
            
            if not exe_path or not os.path.exists(exe_path):
                return False, 0, f"Could not find executable for {browser_key} on Windows"
            
            # Create a user data directory
            user_data_dir = os.path.join(os.path.expanduser("~"), f"DuckTrack_Browser_Debug_{port}")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser
            cmd = [
                exe_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                url
            ]
            
            logging.info(f"Launching {browser_key} with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        # For Linux
        elif system().startswith('linux'):
            exe_path = browser_info.get('linux')
            if not exe_path or not os.path.exists(exe_path):
                return False, 0, f"Could not find executable for {browser_key} on Linux"
            
            # Create a user data directory
            user_data_dir = os.path.join(os.path.expanduser("~"), f".ducktrack_browser_debug_{port}")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser
            cmd = [
                exe_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                url
            ]
            
            logging.info(f"Launching {browser_key} with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
        
        # Wait for browser to start and verify port is open
        time.sleep(2)  # Brief delay for process to start
        
        # Check if port is now open
        for _ in range(5):  # Try 5 times
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(1.0)
                result = sock.connect_ex(('127.0.0.1', port))
                if result == 0:  # Port is now open
                    logging.info(f"Successfully launched {browser_key} with debugging on port {port}")
                    return True, port, ""
            time.sleep(1)  # Wait 1 second between attempts
        
        return False, port, f"Browser launched but debugging port {port} is not responding"
        
    except Exception as e:
        logging.error(f"Error launching {browser_key}: {e}")
        return False, 0, str(e)

def get_default_browser() -> str:
    """Get the default browser key"""
    # Start with Chrome as default
    default = 'chrome'
    
    # Find installed browsers
    installed = find_installed_browsers()
    
    # If Chrome is not installed, use the first available
    if default not in installed and installed:
        default = next(iter(installed.keys()))
        
    return default

def test_port_connection(port: int = DEFAULT_DEBUG_PORT) -> bool:
    """Test if a Chrome debugging port is responding"""
    try:
        import requests
        url = f"http://127.0.0.1:{port}/json/version"
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except:
        return False

def find_running_debuggable_browsers() -> Dict[str, int]:
    """Find already running browsers with debugging enabled
    
    Returns:
        Dict[str, int]: Dictionary mapping browser keys to their debug ports
    """
    debuggable_browsers = {}
    
    try:
        import requests
        import json
        
        # Check common debugging ports
        for port in range(9222, 9232):
            try:
                # Try to connect to Chrome DevTools Protocol
                url = f"http://localhost:{port}/json/version"
                response = requests.get(url, timeout=1)
                
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and 'Browser' in data:
                        browser_info = data['Browser']
                        logging.info(f"Found running debuggable browser on port {port}: {browser_info}")
                        
                        # Try to determine browser type from the name
                        if 'Chrome' in browser_info:
                            debuggable_browsers['chrome'] = port
                        elif 'Edge' in browser_info:
                            debuggable_browsers['edge'] = port
                        elif 'Brave' in browser_info:
                            debuggable_browsers['brave'] = port
                        else:
                            # Generic Chromium-based browser
                            debuggable_browsers['chromium'] = port
            except Exception as e:
                # Silently ignore connection errors
                pass
    except ImportError:
        logging.warning("Requests library not available, can't check for running debuggable browsers")
    
    return debuggable_browsers

def connect_to_running_browser(port: int) -> Tuple[bool, str]:
    """Connect to an already running browser with debugging enabled
    
    Args:
        port: Port to connect to
        
    Returns:
        Tuple[bool, str]: (success, error message if any)
    """
    try:
        import requests
        
        # Verify the connection to the browser's DevTools Protocol
        url = f"http://localhost:{port}/json/version"
        response = requests.get(url, timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict) and 'Browser' in data:
                logging.info(f"Successfully connected to browser on port {port}: {data['Browser']}")
                return True, ""
            else:
                return False, "Invalid response from browser debugging port"
        else:
            return False, f"Browser returned status code {response.status_code}"
    except Exception as e:
        logging.error(f"Error connecting to browser on port {port}: {e}")
        return False, str(e) 