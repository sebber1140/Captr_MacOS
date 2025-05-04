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

def find_installed_browsers() -> Dict[str, str]:
    """Find installed Chromium-based browsers on the system
    
    Returns:
        Dict[str, str]: Dictionary mapping browser keys to display names
    """
    installed = {}
    
    for browser_key, browser_info in BROWSERS.items():
        display_name = browser_info.get('name', browser_key.capitalize())
        
        # For macOS, check if the app exists
        if system() == 'darwin':
            app_name = browser_info.get('darwin_app', display_name)
            app_path = f"/Applications/{app_name}.app"
            if os.path.exists(app_path):
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