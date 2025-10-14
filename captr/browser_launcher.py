"""
Browser launcher for Captr

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
    
    # Direct check for common browsers on macOS - CHECK SPECIFIC LOCATIONS FIRST
    if system() == 'darwin':
        common_browsers = [
            ('/Applications/Google Chrome.app', 'chrome', 'Google Chrome'),
            ('/Applications/Microsoft Edge.app', 'edge', 'Microsoft Edge'),
            ('/Applications/Brave Browser.app', 'brave', 'Brave Browser'),
            ('/Applications/Opera.app', 'opera', 'Opera'),
            ('/Applications/Vivaldi.app', 'vivaldi', 'Vivaldi'),
            ('/Applications/Chromium.app', 'chromium', 'Chromium'),
            # User applications folder
            ('~/Applications/Google Chrome.app', 'chrome', 'Google Chrome'),
            ('~/Applications/Microsoft Edge.app', 'edge', 'Microsoft Edge'),
            ('~/Applications/Brave Browser.app', 'brave', 'Brave Browser'),
            ('~/Applications/Opera.app', 'opera', 'Opera')
        ]
        
        for path, key, name in common_browsers:
            expanded_path = os.path.expanduser(path)
            if os.path.exists(expanded_path):
                logging.info(f"Found browser: {name} at {expanded_path}")
                installed[key] = name
    
    # On macOS, try to find browsers through spotlight if direct paths failed
    if system() == 'darwin' and not installed:
        try:
            # First try mdfind with kMDItemCFBundleIdentifier for more specific matching
            import subprocess
            cmd = ["mdfind", "kMDItemCFBundleIdentifier == 'com.google.Chrome' || kMDItemCFBundleIdentifier == 'com.microsoft.Edge' || kMDItemCFBundleIdentifier == 'com.brave.Browser'"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            app_paths = [path for path in result.stdout.strip().split('\n') if path.strip()]
            
            # Log what we found via Spotlight
            if app_paths:
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
            
            # If still no browsers, try more general search for browser names
            if not installed:
                cmd = ["mdfind", "-name", "Chrome", "-name", "Edge", "-name", "Brave Browser", "-name", "Opera"]
                result = subprocess.run(cmd, capture_output=True, text=True)
                app_paths = [path for path in result.stdout.strip().split('\n') if path.strip() and path.endswith('.app')]
                
                logging.info(f"Found potential browsers via general Spotlight search: {app_paths}")
                for path in app_paths:
                    app_name = os.path.basename(path).replace('.app', '')
                    logging.info(f"Potential browser: {app_name} at {path}")
                    if 'Google Chrome' in path or 'Chrome.app' in path:
                        installed['chrome'] = 'Google Chrome'
                    elif 'Microsoft Edge' in path or 'Edge.app' in path:
                        installed['edge'] = 'Microsoft Edge'
                    elif 'Brave' in path or 'Brave Browser.app' in path:
                        installed['brave'] = 'Brave Browser'
                    elif 'Opera' in path:
                        installed['opera'] = 'Opera'
        except Exception as e:
            logging.error(f"Error using Spotlight search: {e}")
    
    # If still no browsers found, try checking for running debuggable browsers
    if not installed:
        try:
            logging.info("Checking for running debuggable browsers since no installed browsers were found")
            running_browsers = find_running_debuggable_browsers()
            if running_browsers:
                for browser_key, port in running_browsers.items():
                    # Add running browsers to the installed list with a note
                    browser_name = {
                        'chrome': 'Google Chrome',
                        'edge': 'Microsoft Edge',
                        'brave': 'Brave Browser',
                        'chromium': 'Chromium'
                    }.get(browser_key, browser_key.capitalize())
                    installed[browser_key] = f"{browser_name} (Running)"
                    logging.info(f"Found running browser: {browser_name} on port {port}")
        except Exception as e:
            logging.error(f"Error checking for running browsers: {e}")
    
    # If we've found browsers by this point, return them
    if installed:
        logging.info(f"Detected browsers: {installed}")
        return installed
    
    # Last attempts with default locations and AppleScript
    if not installed:
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

def find_available_port(start_port: int = DEFAULT_DEBUG_PORT, max_attempts: int = 20) -> int:
    """Find an available port for browser debugging
    
    Args:
        start_port: Port to start checking from
        max_attempts: Maximum number of ports to check
        
    Returns:
        int: Available port number, or original port if checking fails
    """
    # Try a wider range of ports to increase chances of finding an available one
    # 9222-9242 is our search range, with 20 attempts
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', port))
            if result != 0:  # Port is available
                logging.info(f"Found available port: {port}")
                return port
    
    logging.warning(f"Could not find available port in range {start_port}-{start_port+max_attempts-1}")
    # If we couldn't find an available port, return a port in a completely different range
    return 9333  # Try a completely different port as last resort

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
        port = find_available_port(start_port=9222, max_attempts=20)
    
    # Default URL if not specified
    if url is None:
        url = "about:blank"
    
    # Get browser info
    browser_info = BROWSERS.get(browser_key)
    if not browser_info:
        return False, 0, f"Unknown browser: {browser_key}"
    
    # Kill any existing Chrome debugging sessions that might be hanging
    if system() == 'darwin':
        try:
            import subprocess
            # Check if the port is in use
            result = subprocess.run(['lsof', '-i', f':{port}'], 
                                   capture_output=True, text=True)
            if 'Chrome' in result.stdout or 'Google' in result.stdout:
                logging.info(f"Port {port} is in use by Chrome, attempting to close it properly")
                # Try to find PID using the port
                for line in result.stdout.splitlines():
                    if f":{port}" in line:
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                pid = int(parts[1])
                                logging.info(f"Found process using port {port}: PID {pid}")
                                # Send SIGTERM to close it gracefully
                                import signal
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                    logging.info(f"Sent SIGTERM to PID {pid}")
                                    # Wait a moment for it to close
                                    time.sleep(2)
                                except ProcessLookupError:
                                    logging.info(f"Process {pid} no longer exists")
                            except ValueError:
                                pass
                                
            # Additional check: Is Chrome already running? Quit it to avoid conflicts
            apple_script = """
            tell application "System Events"
                set chromeProcesses to a reference to (processes where name is "Google Chrome" or name is "Chrome" or name is "Microsoft Edge" or name is "Brave Browser")
                if exists chromeProcesses then
                    repeat with chromeProcess in chromeProcesses
                        set appName to name of chromeProcess
                        log "Quitting " & appName
                    end repeat
                    tell application "Google Chrome" to quit
                    tell application "Microsoft Edge" to quit
                    tell application "Brave Browser" to quit
                    delay 2
                end if
            end tell
            return "OK"
            """
            try:
                subprocess.run(["osascript", "-e", apple_script], capture_output=True, text=True)
                logging.info("Closed any existing browser instances to avoid conflicts")
                time.sleep(1) # Give a moment for processes to fully close
            except Exception as e:
                logging.error(f"Error closing existing browser instances: {e}")
            
        except Exception as e:
            logging.error(f"Error trying to free port {port}: {e}")
    
    try:
        # SPECIFIC IMPLEMENTATION FOR MACOS
        if system() == 'darwin':
            app_name = browser_info.get('darwin_app')
            if not app_name:
                return False, 0, f"Could not find app name for {browser_key} on macOS"
            
            # Create a unique timestamped user data directory for isolation
            timestamp = int(time.time())
            user_data_dir = os.path.expanduser(f"~/Library/Application Support/Captr/Browser_Debug_{port}_{timestamp}")
            os.makedirs(user_data_dir, exist_ok=True)
            logging.info(f"Created user data directory: {user_data_dir}")
            
            # Different approach for macOS: use direct executable path instead of open -a
            if browser_key == 'chrome':
                exec_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
            elif browser_key == 'edge':
                exec_path = '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge'
            elif browser_key == 'brave':
                exec_path = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
            else:
                # Fallback to standard locations from BROWSERS dict
                exec_path = browser_info.get('darwin', None)
                if not exec_path or not os.path.exists(exec_path):
                    return False, 0, f"Could not find executable for {browser_key} on macOS"
            
            # Verify the executable exists
            if not os.path.exists(exec_path):
                # Try user Applications as fallback
                user_exec_path = exec_path.replace('/Applications/', '~/Applications/')
                user_exec_path = os.path.expanduser(user_exec_path)
                if os.path.exists(user_exec_path):
                    exec_path = user_exec_path
                else:
                    return False, 0, f"Browser executable not found at {exec_path}"
            
            logging.info(f"Using browser executable: {exec_path}")
            
            # Direct launch with debugging arguments
            cmd = [
                exec_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-extensions',  # Disable extensions for clean debug environment
                '--disable-component-extensions-with-background-pages',  # Reduce startup overhead
                '--disable-background-networking',  # Less network noise
                '--disable-backgrounding-occluded-windows',  # Prevent background throttling
                url
            ]
            
            logging.info(f"Launching browser with command: {' '.join(cmd)}")
            
            # Start the browser
            try:
                proc = subprocess.Popen(cmd)
                pid = proc.pid
                logging.info(f"Browser launched with PID: {pid}")
            except Exception as e:
                logging.error(f"Failed to start browser process: {e}")
                return False, 0, f"Failed to start browser process: {e}"
            
            # Give the browser more time to start up
            logging.info(f"Waiting for browser to initialize with debug port {port}...")
            time.sleep(4)  # Increased from 3 seconds
            
        # For Windows
        elif system() == 'windows' or system() == 'win32':
            # Find executable path
            exe_path = browser_info.get('win32')
            if not os.path.exists(exe_path):
                exe_path = browser_info.get('win32_alt')
            
            if not exe_path or not os.path.exists(exe_path):
                return False, 0, f"Could not find executable for {browser_key} on Windows"
            
            # Create a user data directory
            user_data_dir = os.path.join(os.path.expanduser("~"), f"Captr_Browser_Debug_{port}_{int(time.time())}")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser
            cmd = [
                exe_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                '--no-default-browser-check',
                url
            ]
            
            logging.info(f"Launching {browser_key} with command: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd)
            time.sleep(3)  # Increased from 2 seconds
            
        # For Linux
        elif system().startswith('linux'):
            exe_path = browser_info.get('linux')
            if not exe_path or not os.path.exists(exe_path):
                return False, 0, f"Could not find executable for {browser_key} on Linux"
            
            # Create a user data directory
            user_data_dir = os.path.join(os.path.expanduser("~"), f".ducktrack_browser_debug_{port}_{int(time.time())}")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser
            cmd = [
                exe_path,
                f'--remote-debugging-port={port}',
                f'--user-data-dir={user_data_dir}',
                '--no-first-run',
                '--no-default-browser-check',
                url
            ]
            
            logging.info(f"Launching {browser_key} with command: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd)
            time.sleep(3)  # Increased from 2 seconds
        
        # Check if port is now open
        success = False
        for i in range(10):  # Try more times (10 instead of 5)
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2.0)  # Longer timeout
                    result = sock.connect_ex(('127.0.0.1', port))
                    if result == 0:  # Port is now open
                        # Verify we can actually connect via DevTools protocol
                        try:
                            import requests
                            response = requests.get(f"http://localhost:{port}/json/version", timeout=3)
                            if response.status_code == 200:
                                logging.info(f"Successfully connected to browser on port {port} with DevTools protocol")
                                success = True
                                break
                            else:
                                logging.warning(f"Port {port} is open but returned non-200 status: {response.status_code}")
                        except Exception as e:
                            logging.warning(f"Port {port} is open but failed DevTools protocol check: {e}")
                    else:
                        logging.info(f"Port {port} not open yet, attempt {i+1}/10")
            except Exception as e:
                logging.warning(f"Error checking port {port}: {e}")
                
            # Wait longer between attempts
            time.sleep(1.5)  # Wait 1.5 seconds between attempts
            
        if success:
            logging.info(f"Successfully launched {browser_key} with debugging on port {port}")
            return True, port, ""
        else:
            # Try to diagnose the issue
            error_message = f"Browser launched but debugging port {port} is not responding"
            try:
                # Check if the process is still running
                if proc.poll() is None:
                    error_message += ". Browser process is still running (PID: {}) but debug port is not active.".format(proc.pid)
                else:
                    error_message += ". Browser process has terminated with exit code: {}".format(proc.returncode)
                    
                # Additional diagnostics on macOS
                if system() == 'darwin':
                    # Check if browser process is running
                    ps_result = subprocess.run(['ps', '-A'], capture_output=True, text=True)
                    if app_name in ps_result.stdout:
                        browser_procs = [line for line in ps_result.stdout.splitlines() if app_name in line]
                        error_message += f"\nFound {len(browser_procs)} {app_name} processes running."
                    else:
                        error_message += f"\nNo {app_name} processes found running."
                    
                    # Check ports in use
                    port_result = subprocess.run(['lsof', '-i', f':{port}'], capture_output=True, text=True)
                    if port_result.stdout:
                        error_message += f"\nPort {port} is in use by: {port_result.stdout}"
                    else:
                        error_message += f"\nPort {port} is not in use by any process."
                        
                    error_message += "\n\nTry selecting 'Connect to running browser' instead."
            except Exception as e:
                logging.error(f"Error during diagnostics: {e}")
                
            return False, port, error_message
        
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
        import socket
        
        logging.info("Searching for running debuggable browsers...")
        
        # First check if port 9222 is open at all using a low-level socket check
        # This is more reliable than HTTP requests which might fail for other reasons
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        port_9222_open = sock.connect_ex(('127.0.0.1', 9222)) == 0
        sock.close()
        
        logging.info(f"Socket check for port 9222: {port_9222_open}")
        
        # Try direct connection to the default port using HTTP - try both localhost and 127.0.0.1
        direct_ports = [9222, 9223, 9224, 9333]
        for port in direct_ports:
            if port == 9222 and port_9222_open:
                logging.info(f"Port 9222 is open via socket check. Will be added as fallback if HTTP fails.")
                
            # Try both 127.0.0.1 and localhost for each port
            for host in ['127.0.0.1', 'localhost']:
                try:
                    url = f"http://{host}:{port}/json/version"
                    logging.info(f"Checking {url}...")
                    
                    response = requests.get(url, timeout=2)
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            if isinstance(data, dict) and 'Browser' in data:
                                browser_info = data['Browser']
                                logging.info(f"Found running debuggable browser on {host}:{port}: {browser_info}")
                                
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
                                
                                # Break out of the host loop once we've found a browser on this port
                                break
                            else:
                                logging.info(f"Response from {host}:{port} doesn't contain Browser info, adding as generic browser")
                                debuggable_browsers['browser'] = port
                                break
                        except ValueError:
                            logging.info(f"Port {port} returned invalid JSON response, adding as generic browser")
                            debuggable_browsers['browser'] = port
                            break
                    else:
                        logging.info(f"Port {port} at {host} returned status code {response.status_code}")
                except Exception as e:
                    logging.info(f"Port {port} at {host} is not responding to HTTP: {str(e)}")
        
        # If port 9222 is open via socket check but HTTP check failed, still add it as Chrome
        # This is because many browsers use port 9222 but might not respond to HTTP for various reasons
        if port_9222_open and 'chrome' not in debuggable_browsers and 'browser' not in debuggable_browsers:
            logging.info("Adding Chrome on port 9222 as fallback option since socket check passed")
            debuggable_browsers['chrome'] = 9222
    
    except ImportError:
        logging.warning("Requests library not available, can't check for running debuggable browsers")
    except Exception as e:
        logging.error(f"Error checking for running debuggable browsers: {e}")
    
    logging.info(f"Found running debuggable browsers: {debuggable_browsers}")
    return debuggable_browsers

def connect_to_running_browser(port: int) -> Tuple[bool, str]:
    """Connect to an already running browser with debugging enabled
    
    Args:
        port: Port to connect to
        
    Returns:
        Tuple[bool, str]: (success, error message if any)
    """
    try:
        # First, do a simple socket check to confirm the port is open
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        
        # Try to connect to the port
        socket_result = sock.connect_ex(('127.0.0.1', port))
        sock.close()
        
        if socket_result != 0:
            # Port is not open at all
            logging.error(f"Port {port} is not open")
            return False, f"Port {port} is not open. Make sure Chrome is running with debugging enabled."
        
        logging.info(f"Port {port} is open, proceeding with HTTP connection check")
        
        # Now try HTTP connection with requests
        import requests
        
        # Verify the connection to the browser's DevTools Protocol
        urls = [f"http://127.0.0.1:{port}/json/version", f"http://localhost:{port}/json/version"]
        
        connection_success = False
        response_data = None
        last_error = None
        
        for url in urls:
            logging.info(f"Attempting to connect to browser at URL: {url}")
            
            try:
                response = requests.get(url, timeout=3)
                logging.info(f"Response status code: {response.status_code}")
                
                if response.status_code == 200:
                    connection_success = True
                    try:
                        response_data = response.json()
                        logging.info(f"Response data: {response_data}")
                        break  # Successful connection
                    except ValueError as e:
                        logging.warning(f"Failed to parse JSON response from {url}: {e}")
                        last_error = f"Invalid JSON response from browser: {e}"
                        # Continue to next URL even if JSON parsing failed
                else:
                    logging.warning(f"Browser returned non-200 status code: {response.status_code}")
                    last_error = f"Browser returned status code {response.status_code}"
            except requests.exceptions.ConnectionError as e:
                logging.warning(f"Connection error to {url}: {e}")
                last_error = f"Failed to connect to browser at {url}."
            except requests.exceptions.Timeout as e:
                logging.warning(f"Connection timeout to {url}: {e}")
                last_error = f"Connection timed out. Browser may be busy."
        
        # If we had at least one successful connection
        if connection_success:
            # Check if we got valid JSON response data
            if response_data and isinstance(response_data, dict) and 'Browser' in response_data:
                browser_info = response_data['Browser']
                logging.info(f"Successfully connected to browser on port {port}: {browser_info}")
                return True, ""
            
            # If port is open but response wasn't ideal, still consider it a success for port 9222
            # since Chrome debugging socket is definitely there
            if port == 9222:
                logging.info(f"Port 9222 is open but returned unexpected data. Considering it valid.")
                return True, ""
                
            # For other ports, require more strict validation
            logging.warning(f"Invalid response format from browser: {response_data}")
            return False, "Invalid response from browser debugging port"
            
        # No successful connections
        return False, last_error or f"Failed to connect to browser on port {port}"
        
    except ImportError as e:
        logging.error(f"Required modules not available: {e}")
        return False, "Required libraries missing: requests/socket module not found"
    except Exception as e:
        logging.error(f"Unexpected error connecting to browser on port {port}: {e}")
        return False, str(e) 