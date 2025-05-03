#!/usr/bin/env python3
"""
Utility script to launch Chromium-based browsers with remote debugging enabled.
This is necessary for the DOM snapshot feature in DuckTrack to work.
"""

import os
import sys
import subprocess
import webbrowser
import time
import logging
import argparse

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Default port for Chrome debugging
DEFAULT_PORT = 9222

# Known Chromium-based browsers
BROWSERS = {
    'chrome': {
        'darwin': '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        'darwin_app': 'Google Chrome',
        'win32': r'C:\Program Files\Google\Chrome\Application\chrome.exe',
        'win32_alt': r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        'linux': '/usr/bin/google-chrome',
    },
    'edge': {
        'darwin': '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
        'darwin_app': 'Microsoft Edge',
        'win32': r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
        'win32_alt': r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
        'linux': '/usr/bin/microsoft-edge',
    },
    'brave': {
        'darwin': '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
        'darwin_app': 'Brave Browser',
        'win32': r'C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe',
        'win32_alt': r'C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe',
        'linux': '/usr/bin/brave-browser',
    },
    'opera': {
        'darwin': '/Applications/Opera.app/Contents/MacOS/Opera',
        'darwin_app': 'Opera',
        'win32': r'C:\Program Files\Opera\launcher.exe',
        'win32_alt': r'C:\Program Files (x86)\Opera\launcher.exe',
        'linux': '/usr/bin/opera',
    },
    'vivaldi': {
        'darwin': '/Applications/Vivaldi.app/Contents/MacOS/Vivaldi',
        'darwin_app': 'Vivaldi',
        'win32': r'C:\Program Files\Vivaldi\Application\vivaldi.exe',
        'win32_alt': r'C:\Program Files (x86)\Vivaldi\Application\vivaldi.exe',
        'linux': '/usr/bin/vivaldi-stable',
    },
    'chromium': {
        'darwin': '/Applications/Chromium.app/Contents/MacOS/Chromium',
        'darwin_app': 'Chromium',
        'win32': r'C:\Program Files\Chromium\Application\chrome.exe',
        'win32_alt': r'C:\Program Files (x86)\Chromium\Application\chrome.exe',
        'linux': '/usr/bin/chromium-browser',
    },
}

def get_installed_browsers():
    """Find installed Chromium-based browsers"""
    installed = {}
    
    for browser_name, paths in BROWSERS.items():
        if sys.platform in paths:
            if os.path.exists(paths[sys.platform]):
                installed[browser_name] = paths[sys.platform]
            elif sys.platform == 'win32' and 'win32_alt' in paths and os.path.exists(paths['win32_alt']):
                installed[browser_name] = paths['win32_alt']
                
    return installed

def check_browser_debug_already_running(port=DEFAULT_PORT):
    """Check if any browser is already running with debugging enabled"""
    import requests
    try:
        response = requests.get(f'http://localhost:{port}/json/version', timeout=2)
        if response.status_code == 200:
            version_info = response.json()
            logging.info(f"Browser debugging already running on port {port}: {version_info.get('Browser')}")
            return True
    except Exception:
        pass
    return False

def launch_browser_with_debugging(browser_name='chrome', port=DEFAULT_PORT, url=None):
    """Launch a Chromium-based browser with remote debugging enabled"""
    # Check if browser debugging is already running on the specified port
    if check_browser_debug_already_running(port):
        logging.info(f"Browser is already running with debugging enabled on port {port}")
        if url:
            # Try to open URL in the existing browser instance
            try:
                if sys.platform == 'darwin':
                    app_name = BROWSERS[browser_name].get('darwin_app', browser_name)
                    subprocess.run(['open', '-a', app_name, url])
                    logging.info(f"Opened {url} in existing {browser_name} instance")
                else:
                    # On other platforms, just try to open with the default browser
                    webbrowser.open(url)
            except Exception as e:
                logging.error(f"Error opening URL in existing browser: {e}")
        return True
    
    # Get installed browsers
    installed_browsers = get_installed_browsers()
    
    if browser_name not in installed_browsers:
        logging.error(f"{browser_name} is not installed or not found in standard locations")
        
        # Suggest an alternative if available
        if installed_browsers:
            alt_browser = next(iter(installed_browsers.keys()))
            logging.info(f"Try using '{alt_browser}' instead, which is installed on this system")
        return False
    
    browser_path = installed_browsers[browser_name]
    logging.info(f"Using {browser_name} at: {browser_path}")
    
    # Launch browser with debugging enabled
    try:
        if sys.platform == 'darwin':  # macOS
            # Get the app name for open command
            app_name = BROWSERS[browser_name].get('darwin_app', browser_name)
            cmd = ['open', '-a', app_name, '--args', f'--remote-debugging-port={port}']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif sys.platform == 'win32':  # Windows
            cmd = [browser_path, f'--remote-debugging-port={port}']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif sys.platform.startswith('linux'):  # Linux
            cmd = [browser_path, f'--remote-debugging-port={port}']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        # Wait a moment for browser to start
        time.sleep(3)
        
        # Check if browser debugging is now running
        if check_browser_debug_already_running(port):
            logging.info(f"Successfully launched {browser_name} with debugging enabled on port {port}")
            return True
        else:
            logging.warning(f"{browser_name} seems to have started, but debugging port is not responding")
            # Try waiting a bit longer
            logging.info("Waiting a bit longer for browser to initialize...")
            time.sleep(5)
            if check_browser_debug_already_running(port):
                logging.info(f"Debugging port {port} is now available!")
                return True
            return False
            
    except Exception as e:
        logging.error(f"Error launching {browser_name} with debugging: {e}")
        return False

def main():
    """Main function"""
    parser = argparse.ArgumentParser(description='Launch a Chromium-based browser with debugging enabled')
    parser.add_argument('--browser', '-b', choices=list(BROWSERS.keys()), default='chrome',
                        help='Which Chromium browser to launch (default: chrome)')
    parser.add_argument('--port', '-p', type=int, default=DEFAULT_PORT,
                        help=f'Port to use for remote debugging (default: {DEFAULT_PORT})')
    parser.add_argument('--url', '-u', help='URL to open in the browser')
    parser.add_argument('--list', '-l', action='store_true', help='List installed browsers and exit')
    
    args = parser.parse_args()
    
    logging.info("Chromium Browser Debugging Launcher")
    
    # Show installed browsers if requested
    installed_browsers = get_installed_browsers()
    if args.list or not installed_browsers:
        print("\nInstalled Chromium-based browsers:")
        if installed_browsers:
            for browser in installed_browsers:
                print(f"  - {browser}")
        else:
            print("  No Chromium-based browsers found in standard locations")
        
        if args.list:
            return
    
    # Default to Chrome if specified browser isn't installed
    browser_to_use = args.browser
    if browser_to_use not in installed_browsers:
        if installed_browsers:
            browser_to_use = next(iter(installed_browsers.keys()))
            logging.warning(f"{args.browser} not found. Using {browser_to_use} instead.")
        else:
            logging.error("No supported browsers found. Please install Chrome, Edge, or another Chromium browser.")
            return
    
    url = args.url or "https://example.com"
    
    if launch_browser_with_debugging(browser_to_use, args.port, url):
        logging.info(f"Success! {browser_to_use.capitalize()} is now running with debugging enabled on port {args.port}.")
        logging.info("DuckTrack can now capture DOM snapshots when this browser is in focus.")
    else:
        logging.error(f"Failed to launch {browser_to_use} with debugging enabled.")
        
if __name__ == "__main__":
    main() 