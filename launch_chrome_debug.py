#!/usr/bin/env python3
"""
Utility script to launch Chrome with remote debugging enabled.
This is necessary for the DOM snapshot feature in DuckTrack to work.
"""

import os
import sys
import subprocess
import webbrowser
import time
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def find_chrome_path():
    """Find the path to Chrome or other Chromium-based browsers"""
    if sys.platform == 'darwin':  # macOS
        chrome_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
            '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
            '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser',
            # Add other browsers as needed
        ]
        
        for path in chrome_paths:
            if os.path.exists(path):
                return path
                
        # Also check if Chrome is in PATH
        try:
            result = subprocess.run(['which', 'google-chrome'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
            
    elif sys.platform == 'win32':  # Windows
        chrome_paths = [
            r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            # Add other browsers as needed
        ]
        
        for path in chrome_paths:
            if os.path.exists(path):
                return path
                
    elif sys.platform.startswith('linux'):  # Linux
        chrome_paths = [
            '/usr/bin/google-chrome',
            '/usr/bin/chromium-browser',
            '/usr/bin/microsoft-edge',
            # Add other browsers as needed
        ]
        
        for path in chrome_paths:
            if os.path.exists(path):
                return path
    
    return None

def check_chrome_debug_already_running():
    """Check if Chrome is already running with debugging enabled"""
    import requests
    try:
        response = requests.get('http://localhost:9222/json/version', timeout=2)
        if response.status_code == 200:
            version_info = response.json()
            logging.info(f"Chrome debugging already running: {version_info.get('Browser')}")
            return True
    except Exception:
        pass
    return False

def launch_chrome_with_debugging(url=None):
    """Launch Chrome with remote debugging enabled"""
    # Check if Chrome with debugging is already running
    if check_chrome_debug_already_running():
        logging.info("Chrome is already running with debugging enabled on port 9222")
        if url:
            # Open URL in the existing Chrome instance
            try:
                subprocess.run(['open', '-a', 'Google Chrome', url])
                logging.info(f"Opened {url} in existing Chrome instance")
            except Exception as e:
                logging.error(f"Error opening URL in existing Chrome: {e}")
        return True
        
    # Find Chrome path
    chrome_path = find_chrome_path()
    if not chrome_path:
        logging.error("Could not find Chrome or other Chromium browser")
        return False
        
    logging.info(f"Found browser at: {chrome_path}")
    
    # Launch Chrome with debugging enabled
    try:
        if sys.platform == 'darwin':  # macOS
            # On macOS, just use the simpler version that's guaranteed to work
            cmd = ['open', '-a', 'Google Chrome', '--args', '--remote-debugging-port=9222']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif sys.platform == 'win32':  # Windows
            cmd = [chrome_path, '--remote-debugging-port=9222']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif sys.platform.startswith('linux'):  # Linux
            cmd = [chrome_path, '--remote-debugging-port=9222']
            if url:
                cmd.append(url)
                
            logging.info(f"Running command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        # Wait a moment for Chrome to start
        time.sleep(3)
        
        # Check if Chrome debugging is now running
        if check_chrome_debug_already_running():
            logging.info("Chrome successfully launched with debugging enabled on port 9222")
            return True
        else:
            logging.warning("Chrome seems to have started, but debugging port is not responding")
            # Increase the wait time and try one more check
            logging.info("Waiting a bit longer for Chrome to initialize...")
            time.sleep(5)
            if check_chrome_debug_already_running():
                logging.info("Chrome debugging port is now available!")
                return True
            return False
            
    except Exception as e:
        logging.error(f"Error launching Chrome with debugging: {e}")
        return False

def main():
    """Main function"""
    logging.info("Chrome Debugging Launcher")
    
    # Optional URL to open
    url = "https://example.com" if len(sys.argv) < 2 else sys.argv[1]
    
    if launch_chrome_with_debugging(url):
        logging.info("Success! Chrome is now running with debugging enabled.")
        logging.info("DuckTrack can now capture DOM snapshots when Chrome is in focus.")
    else:
        logging.error("Failed to launch Chrome with debugging enabled.")
        
if __name__ == "__main__":
    main() 