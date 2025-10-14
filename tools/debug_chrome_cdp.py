#!/usr/bin/env python3
"""
Debug tool to check if Chrome's debugging port is available and functioning.
Run this script while Chrome is running with debugging port enabled.
"""

import sys
import requests
import json
import time
import subprocess
import logging
import pychrome
from pychrome.exceptions import TimeoutException
import websocket

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def check_chrome_running():
    """Check if Chrome or other Chromium browsers are running"""
    try:
        if sys.platform == 'darwin':  # macOS
            # Try a different command for macOS
            result = subprocess.run(['ps', 'aux', '|', 'grep', '-i', 'chrome\\|edge\\|brave'], 
                                  shell=True, capture_output=True, text=True)
            if result.stdout and "Google Chrome" in result.stdout:
                logging.info(f"Found running Chromium browser(s)")
                return True
            else:
                # Try direct process check
                chrome_check = subprocess.run(['pgrep', 'Chrome'], 
                                     capture_output=True, text=True)
                if chrome_check.stdout.strip():
                    logging.info(f"Found Chrome process: {chrome_check.stdout.strip()}")
                    return True
                
                logging.warning("No running Chromium browsers detected")
                return False
        else:
            logging.warning("Platform detection not implemented for this OS")
            return True  # Assume true for other platforms
    except Exception as e:
        logging.error(f"Error checking for running browsers: {e}")
        return False

def test_chrome_connection(port=9222):
    """Test connecting to Chrome debugging port"""
    try:
        url = f"http://localhost:{port}/json/version"
        logging.info(f"Testing connection to {url}")
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            logging.info("Successfully connected to Chrome debugging port")
            version_info = response.json()
            logging.info(f"Chrome version: {version_info.get('Browser')}")
            logging.info(f"Protocol version: {version_info.get('Protocol-Version')}")
            return True
        else:
            logging.error(f"Failed to connect: Status code {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error: Chrome debugging port {port} not available")
        logging.info("Make sure Chrome is started with the --remote-debugging-port flag")
        logging.info("Example: open -a \"Google Chrome\" --args --remote-debugging-port=9222")
        return False
    except Exception as e:
        logging.error(f"Error connecting to Chrome: {e}")
        return False

def list_chrome_tabs(port=9222):
    """List available tabs in Chrome"""
    try:
        url = f"http://localhost:{port}/json/list"
        logging.info(f"Getting tabs from {url}")
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            tabs = response.json()
            logging.info(f"Found {len(tabs)} tabs")
            for i, tab in enumerate(tabs):
                logging.info(f"Tab {i+1}: {tab.get('title', 'No title')} - {tab.get('url')}")
            return tabs
        else:
            logging.error(f"Failed to get tabs: Status code {response.status_code}")
            return []
    except Exception as e:
        logging.error(f"Error listing Chrome tabs: {e}")
        return []

def try_capture_snapshot(port=9222):
    """Attempt to capture a DOM snapshot using pychrome"""
    browser = None
    try:
        logging.info(f"Connecting to Chrome with pychrome on port {port}")
        browser = pychrome.Browser(url=f"http://localhost:{port}")
        
        # Get tabs directly from browser
        tabs = browser.list_tab()
        logging.info(f"Found {len(tabs)} tabs with browser.list_tab()")
        
        valid_tabs = []
        for tab in tabs:
            if hasattr(tab, 'id') and hasattr(tab, 'url') and hasattr(tab, 'type'):
                if getattr(tab, 'type') == 'page' and not getattr(tab, 'url', '').startswith('chrome-extension://'):
                    valid_tabs.append(tab)
                    
        if not valid_tabs:
            # If there are tabs but none match our criteria, just use the first one
            if tabs:
                valid_tabs.append(tabs[0])
                
        if valid_tabs:
            active_tab = valid_tabs[0]
            logging.info(f"Using tab with ID: {getattr(active_tab, 'id', 'unknown')}")
            
            logging.info("Starting tab connection")
            active_tab.start()
            
            try:
                logging.info("Attempting to capture DOM snapshot")
                snapshot = active_tab.call_method("Page.captureSnapshot", format='mhtml', _timeout=10)
                
                if snapshot and 'data' in snapshot:
                    size = len(snapshot['data'])
                    logging.info(f"Successfully captured snapshot ({size} bytes)")
                    sample = snapshot['data'][:100] + "..." # Show the beginning
                    logging.info(f"Sample: {sample}")
                    
                    # Save to file for testing
                    with open('test_snapshot.mhtml', 'w', encoding='utf-8') as f:
                        f.write(snapshot['data'])
                    logging.info("Snapshot saved to test_snapshot.mhtml")
                    return True
                else:
                    logging.warning("Empty or invalid snapshot data")
                    return False
            finally:
                logging.info("Stopping tab connection")
                active_tab.stop()
        else:
            logging.warning("No valid tabs found")
            return False
            
    except (requests.exceptions.ConnectionError, TimeoutException, websocket.WebSocketException) as e:
        logging.error(f"CDP connection failed: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error during CDP capture: {e}", exc_info=True)
        return False

def main():
    """Main function"""
    logging.info("Chrome/CDP Debugging Tool")
    
    if not check_chrome_running():
        logging.warning("Please start Chrome before running this tool")
        return
    
    port = 9222  # Default Chrome debugging port
    
    if not test_chrome_connection(port):
        logging.error("Could not connect to Chrome debugging port")
        logging.info("On macOS, start Chrome with:")
        logging.info("open -a \"Google Chrome\" --args --remote-debugging-port=9222")
        logging.info("On Windows, start Chrome with:")
        logging.info("chrome.exe --remote-debugging-port=9222")
        return
    
    tabs = list_chrome_tabs(port)
    if not tabs:
        return
        
    if try_capture_snapshot(port):
        logging.info("DOM snapshot capture test was successful!")
    else:
        logging.error("DOM snapshot capture test failed")
    
if __name__ == "__main__":
    main() 