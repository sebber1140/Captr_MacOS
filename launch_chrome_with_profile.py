#!/usr/bin/env python3
"""
Launch Chrome with Debugging Enabled

This script launches Chrome with debugging enabled on port 9222
while preserving the user's existing profile.
"""

import os
import sys
import time
import socket
import subprocess
import logging
from platform import system

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def check_port_open(port):
    """Check if a port is open using socket"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0

def check_chrome_debugger(port):
    """Check if Chrome debugger is responding on port"""
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
        if response.status_code == 200:
            data = response.json()
            if 'Browser' in data:
                logging.info(f"Chrome debugger detected: {data['Browser']}")
                return True
    except Exception as e:
        logging.debug(f"Error checking Chrome debugger: {e}")
    return False

def close_chrome():
    """Close any running Chrome instances"""
    try:
        if system() == 'Darwin':  # macOS
            subprocess.run(['killall', 'Google Chrome'], 
                          stdout=subprocess.DEVNULL, 
                          stderr=subprocess.DEVNULL)
            return True
        elif system() == 'Windows' or system() == 'win32':
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe'],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
            return True
        elif system().startswith('Linux'):
            subprocess.run(['killall', 'chrome', 'google-chrome'],
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
            return True
    except Exception as e:
        logging.error(f"Error closing Chrome: {e}")
    return False

def launch_chrome_with_debugging(port=9222, close_existing=True, wait_time=3):
    """
    Launch Chrome with debugging enabled
    
    Args:
        port: The debugging port to use
        close_existing: Whether to close existing Chrome instances
        wait_time: Time to wait for Chrome to start (seconds)
    
    Returns:
        bool: True if Chrome was successfully launched with debugging
    """
    # First check if Chrome debugger is already running
    if check_port_open(port):
        if check_chrome_debugger(port):
            logging.info(f"Chrome is already running with debugging on port {port}")
            return True
        else:
            logging.warning(f"Port {port} is in use but not by Chrome debugger")
            if not close_existing:
                return False
    
    # Close Chrome if requested
    if close_existing:
        logging.info("Closing existing Chrome instances...")
        close_chrome()
        # Give Chrome a moment to shut down
        time.sleep(1)
    
    # Launch Chrome with debugging
    try:
        if system() == 'Darwin':  # macOS
            cmd = [
                'open',
                '-a',
                'Google Chrome',
                '--args',
                f'--remote-debugging-port={port}'
            ]
            logging.info(f"Launching Chrome with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif system() == 'Windows' or system() == 'win32':  # Windows
            # Find Chrome executable
            chrome_paths = [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expanduser("~") + r"\AppData\Local\Google\Chrome\Application\chrome.exe"
            ]
            
            chrome_exe = None
            for path in chrome_paths:
                if os.path.exists(path):
                    chrome_exe = path
                    break
            
            if not chrome_exe:
                logging.error("Could not find Chrome executable")
                return False
            
            cmd = [
                chrome_exe,
                f'--remote-debugging-port={port}'
            ]
            logging.info(f"Launching Chrome with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        elif system().startswith('Linux'):  # Linux
            chrome_paths = [
                '/usr/bin/google-chrome',
                '/usr/bin/google-chrome-stable',
                '/usr/bin/chromium-browser',
                '/usr/bin/chromium'
            ]
            
            chrome_exe = None
            for path in chrome_paths:
                if os.path.exists(path):
                    chrome_exe = path
                    break
            
            if not chrome_exe:
                logging.error("Could not find Chrome executable")
                return False
            
            cmd = [
                chrome_exe,
                f'--remote-debugging-port={port}'
            ]
            logging.info(f"Launching Chrome with command: {' '.join(cmd)}")
            subprocess.Popen(cmd)
            
        else:
            logging.error(f"Unsupported operating system: {system()}")
            return False
        
        # Wait for Chrome to start
        logging.info(f"Waiting {wait_time} seconds for Chrome to start...")
        time.sleep(wait_time)
        
        # Check if Chrome is running with debugging
        for _ in range(3):  # Try a few times
            if check_port_open(port) and check_chrome_debugger(port):
                logging.info(f"Chrome launched successfully with debugging on port {port}")
                return True
            time.sleep(1)
        
        if check_port_open(port):
            logging.warning(f"Port {port} is open but Chrome debugger is not responding")
        else:
            logging.warning(f"Port {port} is not open after launching Chrome")
        
        return False
        
    except Exception as e:
        logging.error(f"Error launching Chrome: {e}")
        return False

def main():
    """Main function"""
    port = 9222
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}")
            sys.exit(1)
    
    print(f"Launching Chrome with debugging enabled on port {port}...")
    success = launch_chrome_with_debugging(port=port)
    
    if success:
        print(f"✅ Chrome is now running with debugging enabled on port {port}")
    else:
        print(f"❌ Failed to launch Chrome with debugging on port {port}")
        sys.exit(1)

if __name__ == "__main__":
    main() 