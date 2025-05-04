import json
import os
import time
from datetime import datetime
from platform import system
from queue import Queue, Empty
import logging
import sys
import ctypes
import pychrome
from pychrome.exceptions import TimeoutException
import requests.exceptions
import websocket # For websocket specific exceptions

from pynput import keyboard, mouse
from pynput.keyboard import KeyCode
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

# Import PyObjC and framework modules conditionally for macOS
if system() == "Darwin":
    try:
        # Import top-level frameworks
        import objc
        import AppKit
        import Foundation
        import Quartz
        import ApplicationServices
        
        # For better compatibility, we'll use constants directly from ApplicationServices
        # as confirmed by our test script
        kAXValueCGPointType = ApplicationServices.kAXValueCGPointType
        kAXValueCGSizeType = ApplicationServices.kAXValueCGSizeType
        kAXValueCGRectType = ApplicationServices.kAXValueCGRectType
        kAXValueCFRangeType = ApplicationServices.kAXValueCFRangeType
        
        # Track successful import
        HAS_PYOBJC = True
    except ImportError as e:
        logging.error(f"PyObjC framework import failed: {e}")
        HAS_PYOBJC = False
else:
    HAS_PYOBJC = False

from .metadata import MetadataManager
from .obs_client import OBSClient
from .util import fix_windows_dpi_scaling, get_recordings_dir

# --- Helper function for macOS Accessibility Tree ---
if system() == "Darwin" and HAS_PYOBJC:
    def decode_axvalue(value):
        """Decodes AXValueRef types into Python types."""
        try:
            # Access constants directly via our module variables
            value_type = ApplicationServices.AXValueGetType(value)
            
            # Use ctypes style byref for newer PyObjC, don't use objc.byref directly
            # as it may not exist in newer versions
            if value_type == kAXValueCGPointType:
                point = Quartz.CGPoint()
                try:
                    if hasattr(objc, 'byref'):
                        ApplicationServices.AXValueGetValue(value, kAXValueCGPointType, objc.byref(point))
                    else:
                        # Alternative method for newer PyObjC
                        ApplicationServices.AXValueGetValue(value, kAXValueCGPointType, ctypes.byref(point))
                except Exception as e:
                    logging.error(f"Error decoding CGPoint: {e}")
                    return "<CGPoint decode error>"
                return {'x': point.x, 'y': point.y}
            elif value_type == kAXValueCGSizeType:
                size = Quartz.CGSize()
                try:
                    if hasattr(objc, 'byref'):
                        ApplicationServices.AXValueGetValue(value, kAXValueCGSizeType, objc.byref(size))
                    else:
                        # Alternative method for newer PyObjC
                        ApplicationServices.AXValueGetValue(value, kAXValueCGSizeType, ctypes.byref(size))
                except Exception as e:
                    logging.error(f"Error decoding CGSize: {e}")
                    return "<CGSize decode error>"
                return {'width': size.width, 'height': size.height}
            elif value_type == kAXValueCGRectType:
                rect = Quartz.CGRect()
                try:
                    if hasattr(objc, 'byref'):
                        ApplicationServices.AXValueGetValue(value, kAXValueCGRectType, objc.byref(rect))
                    else:
                        # Alternative method for newer PyObjC
                        ApplicationServices.AXValueGetValue(value, kAXValueCGRectType, ctypes.byref(rect))
                except Exception as e:
                    logging.error(f"Error decoding CGRect: {e}")
                    return "<CGRect decode error>"
                return {'x': rect.origin.x, 'y': rect.origin.y, 'width': rect.size.width, 'height': rect.size.height}
            elif value_type == kAXValueCFRangeType:
                range_val = Quartz.CFRange()
                try:
                    if hasattr(objc, 'byref'):
                        ApplicationServices.AXValueGetValue(value, kAXValueCFRangeType, objc.byref(range_val))
                    else:
                        # Alternative method for newer PyObjC
                        ApplicationServices.AXValueGetValue(value, kAXValueCFRangeType, ctypes.byref(range_val))
                except Exception as e:
                    logging.error(f"Error decoding CFRange: {e}")
                    return "<CFRange decode error>"
                return {'location': range_val.location, 'length': range_val.length}
            
            return f"<AXValue type {value_type}>" # Fallback for unknown types
        except Exception as e:
            logging.error(f"Error decoding AXValue: {e}")
            return f"<AXValue decode error: {e}>"

    def sanitize_for_json(obj):
        """Recursively convert known problematic types in a dict/list for JSON serialization."""
        if isinstance(obj, dict):
            return {k: sanitize_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [sanitize_for_json(item) for item in obj]
        # Add specific type conversions here as needed
        elif hasattr(objc, 'pyobjc_unicode') and isinstance(obj, objc.pyobjc_unicode):
            return str(obj)
        elif hasattr(objc, 'objc_object') and isinstance(obj, objc.objc_object):
            # Handle generic objc_object - might need more specific checks if complex
            return str(obj) # Simple string conversion
        elif hasattr(Foundation, 'NSDate') and isinstance(obj, Foundation.NSDate):
            return str(obj) # Or format as ISO string etc.
        elif hasattr(AppKit, 'NSNumber') and isinstance(obj, AppKit.NSNumber):
            # Try to convert NSNumber types appropriately
            try:
                if hasattr(obj, 'boolValue'):
                    return bool(obj.boolValue())
                elif hasattr(obj, 'floatValue'):
                    return float(obj.floatValue())
                elif hasattr(obj, 'intValue'):
                    return int(obj.intValue())
            except:
                pass # Ignore conversion errors, fall back to str
            return str(obj) # Fallback
        # Add other potential types like NSData, etc. if encountered
        return obj # Return basic types (int, float, str, bool, None) and unknowns as is

    def get_element_info(element):
        """Recursively get information about an AXUIElement and its children."""
        info = {}
        attributes = [
            ApplicationServices.kAXRoleAttribute, 
            ApplicationServices.kAXSubroleAttribute, 
            ApplicationServices.kAXTitleAttribute,
            ApplicationServices.kAXIdentifierAttribute, 
            ApplicationServices.kAXValueAttribute
        ]
        
        for attr in attributes:
            try:
                # Use AXUIElementCopyAttributeValue with error checking
                result, value = ApplicationServices.AXUIElementCopyAttributeValue(element, attr, None)
                if result == 0 and value is not None:  # kAXErrorSuccess is 0
                    # Handle different value types appropriately
                    if not isinstance(value, (str, int, float, bool, list, dict)):
                        try:
                            info[attr.replace('kAX', '').replace('Attribute', '')] = decode_axvalue(value)
                        except Exception as e:
                            logging.debug(f"Failed to decode AXValue for {attr}: {e}")
                            info[attr.replace('kAX', '').replace('Attribute', '')] = str(value)
                    elif isinstance(value, (list, tuple)):
                        child_elements = []
                        for el in value:
                            if el is not None and not isinstance(el, (str, int, float, bool, list, dict)):
                                try:
                                    child_elements.append(get_element_info(el))
                                except Exception as nested_e:
                                    logging.debug(f"Error processing child element: {nested_e}")
                            else:
                                child_elements.append(el)
                        if child_elements:
                            info[attr.replace('kAX', '').replace('Attribute', '')] = child_elements
                        else:
                            info[attr.replace('kAX', '').replace('Attribute', '')] = value
                    else:
                        info[attr.replace('kAX', '').replace('Attribute', '')] = value
            except Exception as e:
                logging.debug(f"Error getting attribute {attr}: {e}")

        # Get children recursively
        try:
            result_children, children = ApplicationServices.AXUIElementCopyAttributeValue(element, ApplicationServices.kAXChildrenAttribute, None)
            if result_children == 0 and children:  # kAXErrorSuccess is 0
                info['Children'] = []
                for child in children:
                    try:
                        child_info = get_element_info(child)
                        if child_info:
                            info['Children'].append(child_info)
                    except Exception as child_e:
                        logging.debug(f"Error processing child: {child_e}")
        except Exception as e:
            logging.debug(f"Error getting children: {e}")

        return info

    def capture_macos_accessibility_tree():
        """Captures the accessibility tree of the focused application window on macOS."""
        try:
            logging.debug("Attempting to capture macOS accessibility tree...")
            workspace = AppKit.NSWorkspace.sharedWorkspace()
            active_app = workspace.frontmostApplication()
            if not active_app:
                logging.warning("Accessibility Capture: No active application found.")
                return None

            pid = active_app.processIdentifier()
            app_name = active_app.localizedName()
            logging.debug(f"Active app: {app_name} (PID: {pid})")
            app_element = ApplicationServices.AXUIElementCreateApplication(pid)

            if not app_element:
                logging.warning(f"Accessibility Capture: AXUIElementCreateApplication failed for PID {pid}.")
                return None

            # Get focused window
            result, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
                app_element, 
                ApplicationServices.kAXFocusedWindowAttribute, 
                None
            )
            
            if result != 0 or not focused_window:  # kAXErrorSuccess is 0
                logging.debug(f"Could not get focused window (result={result}), trying to get any window")
                # Fallback: Try getting the first window from the list
                result_windows, windows = ApplicationServices.AXUIElementCopyAttributeValue(
                    app_element, 
                    ApplicationServices.kAXWindowsAttribute, 
                    None
                )
                
                if result_windows == 0 and windows and len(windows) > 0:
                    focused_window = windows[0]
                    logging.debug("Using first window from list as fallback.")
                else:
                    logging.warning(f"Accessibility Capture: Could not get focused or any window for app {app_name}.")
                    return None  # No window found

            logging.debug("Starting to build accessibility tree...")
            tree = get_element_info(focused_window)
            if not tree:
                logging.warning("Generated empty accessibility tree")
                return None

            # Sanitize the tree before returning
            sanitized_tree = sanitize_for_json(tree)
            if not sanitized_tree:
                logging.warning("Sanitized accessibility tree is empty")
                return None
                
            logging.debug(f"Successfully captured accessibility tree for {app_name}")
            return sanitized_tree

        except Exception as e:
            logging.error(f"Error capturing macOS accessibility tree: {e}", exc_info=True)
            return None
else:
    # Provide a dummy function if not on macOS or Accessibility fails
    def capture_macos_accessibility_tree():
        logging.debug("capture_macos_accessibility_tree called but not on macOS or PyObjC failed")
        return None

# --- Helper function for CDP DOM Snapshot ---
def capture_chromium_dom_snapshot(port=9222):
    """Connects to Chrome via CDP and captures DOM snapshot of the active tab."""
    try:
        logging.debug(f"Attempting to connect to Chromium on port {port}...")
        
        # First, check if Chrome is available with the debugging port
        try:
            import requests
            version_response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2)
            if version_response.status_code != 200:
                logging.warning(f"Chrome debugging port returned status code {version_response.status_code}")
                return None
                
            # Get the list of tabs
            tabs_response = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=2)
            if tabs_response.status_code != 200:
                logging.warning("Failed to get list of tabs")
                return None
                
            tabs = tabs_response.json()
            if not tabs:
                logging.warning("No tabs found in Chrome/Edge")
                return None
                
            # Find the first real page tab (not DevTools, extensions, etc.)
            active_tab = None
            for tab in tabs:
                if tab.get('type') == 'page' and tab.get('url') and not tab.get('url').startswith('chrome'):
                    active_tab = tab
                    break
                    
            # If no suitable tab found, try the first tab of any type as fallback
            if not active_tab and tabs:
                active_tab = tabs[0]
                
            if not active_tab:
                logging.warning("Could not find an active tab")
                return None
                
            logging.debug(f"Found active tab: {active_tab.get('title')} - {active_tab.get('url')}")
            
            # Now use pychrome to connect to this tab
            import pychrome
            browser = pychrome.Browser(url=f"http://127.0.0.1:{port}")
            
            # Get the tab by ID
            tab_id = active_tab.get('id')
            if not tab_id:
                logging.warning("Tab is missing ID")
                return None
                
            # Use the browser.list_tab() to get the actual tab object
            browser_tabs = browser.list_tab()
            target_tab = None
            
            for bt in browser_tabs:
                if hasattr(bt, 'id') and bt.id == tab_id:
                    target_tab = bt
                    break
                    
            if not target_tab:
                logging.warning(f"Could not find tab with ID {tab_id} in browser tabs")
                return None
                
            # Start the tab
            target_tab.start()
            
            try:
                # Call Page.captureSnapshot - returns MHTML data
                logging.debug("Calling Page.captureSnapshot...")
                snapshot_data = target_tab.call_method("Page.captureSnapshot", format='mhtml', _timeout=5)
                
                if snapshot_data and 'data' in snapshot_data:
                    logging.debug(f"Captured DOM snapshot: {len(snapshot_data['data'])} bytes")
                    return snapshot_data.get('data')
                else:
                    logging.warning("CDP: captureSnapshot returned empty or invalid data")
                    return None
            finally:
                target_tab.stop()
                
        except (requests.exceptions.ConnectionError, pychrome.exceptions.TimeoutException, websocket.WebSocketException) as e:
            logging.warning(f"CDP connection/capture failed (port {port}): {e}")
            return None
            
    except Exception as e:
        logging.error(f"Unexpected error during CDP capture: {e}", exc_info=True)
        return None

# --- Constants ---
CHROMIUM_BUNDLE_IDS = {
    "com.google.Chrome",
    "com.microsoft.Edge",
    "com.brave.Browser",
    # Add others like Opera, Vivaldi if needed
    # "com.operasoftware.Opera",
    # "com.vivaldi.Vivaldi"
}

# Keys that should trigger DOM capture (besides clicks and modifier changes)
# Using a set for efficient lookup. Includes common command/navigation keys.
DOM_CAPTURE_KEYS = {
    'enter', 'tab', 'backspace', 'delete', # delete might be fn+backspace
    'esc', 'space', 
    'left', 'right', 'up', 'down', # Arrow keys
    'pageup', 'pagedown', 'home', 'end', # Navigation
    # Add modifier keys
    'shift', 'ctrl', 'alt', 'cmd', 'control', 'option', 'command',
    # Add function keys (F1-F12) if desired: 'f1', 'f2', ...
}

class Recorder(QThread):
    """
    Makes recordings.
    """
    
    recording_stopped = pyqtSignal()
    # Signal to potentially inform main thread about focus (optional)
    # focus_changed = pyqtSignal(dict)

    def __init__(self, natural_scrolling: bool):
        super().__init__()
        
        if system() == "Windows":
            fix_windows_dpi_scaling()
            
        self.recording_path = self._get_recording_path()
        self.mouse_buttons_pressed = set()
        self.natural_scrolling = natural_scrolling
        
        self._is_recording = False
        self._is_paused = False
        
        self.event_queue = Queue()
        self.events_file = None
        
        # State for browser DOM capture
        self.is_chromium_focused = False
        self.focused_pid = None
        self.capture_data_path = None # Path for both a11y trees and DOM snaps
        
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        
        # Initialize managers later in run() or ensure thread safety if needed earlier
        self.metadata_manager = None
        self.obs_client = None

        # Listeners setup
        # Listeners are initialized here but started in run()
        self.mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll
        )

        # Initialize pynput keyboard listener ONLY if not macOS or PyObjC failed
        self.keyboard_listener = None
        if system() != "Darwin" or not HAS_PYOBJC:
            logging.info("Using pynput keyboard listener (not macOS or PyObjC unavailable).")
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_press,
                on_release=self.on_release)
        else:
            logging.info("Will use AppKit for macOS keyboard events.")

        self.macos_key_monitor = None # Holder for the NSEvent monitor

    def on_move(self, x, y):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "move", 
                                  "x": x, 
                                  "y": y}, block=False)
        
    def on_click(self, x, y, button, pressed):
        if not self._is_paused:
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)

            # Capture accessibility tree on macOS
            accessibility_tree_path = None
            if system() == "Darwin" and HAS_PYOBJC and self.capture_data_path:
                logging.debug(f"Mouse {'press' if pressed else 'release'} at ({x},{y}), attempting to capture accessibility tree...")
                tree = capture_macos_accessibility_tree()
                if tree:
                    timestamp = time.perf_counter()
                    filename = f"a11y_click_{timestamp:.6f}.json"
                    filepath = os.path.join(self.capture_data_path, filename)
                    try:
                        with open(filepath, 'w') as f:
                            json.dump(tree, f, indent=2)
                        logging.info(f"Accessibility tree saved to: {filepath}")
                        accessibility_tree_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving accessibility tree to {filepath}: {e}", exc_info=True)
                else:
                    logging.warning("Failed to capture accessibility tree on click")

            # Capture DOM snapshot if Chromium is focused
            dom_snapshot_path = None
            if self.is_chromium_focused and self.capture_data_path:
                logging.debug(f"Mouse {'press' if pressed else 'release'} in Chromium app (PID: {self.focused_pid}), attempting DOM snapshot...")
                snapshot_mhtml = capture_chromium_dom_snapshot() # Using default port 9222
                if snapshot_mhtml:
                    timestamp = time.perf_counter()
                    filename = f"dom_click_{timestamp:.6f}.mhtml"
                    filepath = os.path.join(self.capture_data_path, filename)
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(snapshot_mhtml)
                        logging.info(f"DOM snapshot saved to: {filepath}")
                        dom_snapshot_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving DOM snapshot: {e}", exc_info=True)
                else:
                    logging.warning("Failed to capture DOM snapshot on click")
                    logging.info("Make sure Chrome is running with --remote-debugging-port=9222")

            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed,
                "accessibility_tree": accessibility_tree_path,
                "dom_snapshot": dom_snapshot_path
            }, block=False)
        
    def on_scroll(self, x, y, dx, dy):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "scroll", 
                                  "x": x, 
                                  "y": y, 
                                  "dx": dx, 
                                  "dy": dy}, block=False)
    
    def on_press(self, key):
        if not self._is_paused:
            # Capture accessibility tree on macOS
            accessibility_tree_path = None
            if system() == "Darwin" and self.capture_data_path:
                tree = capture_macos_accessibility_tree()
                if tree:
                    timestamp = time.perf_counter()
                    filename = f"a11y_keypress_{timestamp:.6f}.json"
                    filepath = os.path.join(self.capture_data_path, filename)
                    logging.debug(f"Attempting to save accessibility tree to: {filepath}")
                    try:
                        with open(filepath, 'w') as f:
                            json.dump(tree, f, indent=2)
                        logging.debug(f"Successfully saved accessibility tree: {filepath}")
                        accessibility_tree_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving accessibility tree to {filepath}: {e}", exc_info=True)

            # Capture DOM snapshot if Chromium is focused and key is relevant
            dom_snapshot_path = None
            key_name = key.char if type(key) == KeyCode else key.name
            if self.is_chromium_focused and self.capture_data_path and key_name in DOM_CAPTURE_KEYS:
                snapshot_mhtml = capture_chromium_dom_snapshot()
                if snapshot_mhtml:
                    timestamp = time.perf_counter()
                    filename = f"dom_keypress_{key_name}_{timestamp:.6f}.mhtml"
                    filepath = os.path.join(self.capture_data_path, filename)
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(snapshot_mhtml)
                        dom_snapshot_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving DOM snapshot: {e}")

            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "press",
                "name": key.char if type(key) == KeyCode else key.name,
                "accessibility_tree": accessibility_tree_path,
                "dom_snapshot": dom_snapshot_path
            }, block=False)

    def on_release(self, key):
        if not self._is_paused:
            # We might not need to capture on release, but doing it for consistency for now.
            # Consider removing if it generates too much redundant data.
            accessibility_tree_path = None
            if system() == "Darwin" and self.capture_data_path:
                tree = capture_macos_accessibility_tree()
                if tree:
                    timestamp = time.perf_counter()
                    filename = f"a11y_keyrelease_{timestamp:.6f}.json"
                    filepath = os.path.join(self.capture_data_path, filename)
                    logging.debug(f"Attempting to save accessibility tree to: {filepath}")
                    try:
                        with open(filepath, 'w') as f:
                            json.dump(tree, f, indent=2)
                        logging.debug(f"Successfully saved accessibility tree: {filepath}")
                        accessibility_tree_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving accessibility tree to {filepath}: {e}", exc_info=True)

            # Capture DOM snapshot if Chromium is focused and key is relevant
            dom_snapshot_path = None
            key_name = key.char if type(key) == KeyCode else key.name
            if self.is_chromium_focused and self.capture_data_path and key_name in DOM_CAPTURE_KEYS:
                snapshot_mhtml = capture_chromium_dom_snapshot()
                if snapshot_mhtml:
                    timestamp = time.perf_counter()
                    filename = f"dom_keyrelease_{key_name}_{timestamp:.6f}.mhtml"
                    filepath = os.path.join(self.capture_data_path, filename)
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(snapshot_mhtml)
                        dom_snapshot_path = filepath
                    except Exception as e:
                        logging.error(f"Error saving DOM snapshot: {e}")

            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "release",
                "name": key.char if type(key) == KeyCode else key.name,
                "accessibility_tree": accessibility_tree_path,
                "dom_snapshot": dom_snapshot_path
            }, block=False)
    
    def run(self):
        self._is_recording = True
        self._is_paused = False
        self.mouse_buttons_pressed.clear()
        self.macos_key_monitor = None # Ensure monitor is reset
        self.capture_data_path = None # Initialize path for captures

        try:
            self.events_file = open(os.path.join(self.recording_path, "events.jsonl"), "a")

            # Create directory for DOM/Accessibility captures
            self.capture_data_path = os.path.join(self.recording_path, "dom_snaps")
            try:
                if not os.path.exists(self.capture_data_path):
                    logging.info(f"Creating dom_snaps directory at: {self.capture_data_path}")
                    os.makedirs(self.capture_data_path, exist_ok=True)
                
                # Test if we can write to the directory
                test_file_path = os.path.join(self.capture_data_path, "test_write.txt")
                with open(test_file_path, 'w') as f:
                    f.write("Test write access")
                os.remove(test_file_path)
                logging.info(f"Successfully created and tested write access to: {self.capture_data_path}")
            except Exception as e:
                logging.error(f"Error creating or writing to dom_snaps directory: {e}")
                # Fallback to a different location
                alt_path = os.path.join(os.path.expanduser('~'), 'DuckTrack_dom_snaps')
                logging.info(f"Trying alternate dom_snaps path: {alt_path}")
                try:
                    os.makedirs(alt_path, exist_ok=True)
                    self.capture_data_path = alt_path
                    logging.info(f"Using alternate dom_snaps path: {self.capture_data_path}")
                except Exception as e2:
                    logging.error(f"Failed to create alternate dom_snaps directory: {e2}")
                    self.capture_data_path = None

            self.metadata_manager = MetadataManager(
                recording_path=self.recording_path,
                natural_scrolling=self.natural_scrolling
            )
            self.obs_client = OBSClient(
                recording_path=self.recording_path,
                metadata=self.metadata_manager.metadata
            )

            self.metadata_manager.collect()

            logging.debug("Starting input listeners/monitors...")
            self.mouse_listener.start()

            if self.keyboard_listener: # Use pynput if available
                self.keyboard_listener.start()
            elif system() == "Darwin" and HAS_PYOBJC: # Use AppKit on macOS if available
                logging.info("Attempting to start AppKit global key monitor.")

                # Define the handler function locally to capture self
                def macos_handler_wrapper(event):
                    # Call the instance method to handle the event
                    return self._macos_key_handler(event)

                # Use module-level constants for event mask
                event_mask = (
                    AppKit.NSEventMaskKeyDown | 
                    AppKit.NSEventMaskKeyUp | 
                    AppKit.NSEventMaskFlagsChanged
                )
                
                # Pass the wrapper function directly
                self.macos_key_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    event_mask,
                    macos_handler_wrapper # Pass the wrapper
                )
                
                # Check if monitor was created
                if not self.macos_key_monitor:
                    logging.error("FAILED TO CREATE AppKit global key monitor! Check Accessibility permissions?")
                else:
                    logging.info("AppKit global key monitor object created successfully.")
            else:
                logging.warning("No keyboard listener available for this platform.")

            time.sleep(0.1)

            # Check if Chrome's debug port is enabled
            if self.capture_data_path:
                try:
                    import requests
                    logging.info("Testing Chrome debugging port connection...")
                    response = requests.get("http://127.0.0.1:9222/json/version", timeout=2)
                    if response.status_code == 200:
                        version_info = response.json()
                        logging.info(f"Chrome debugging port available. Browser: {version_info.get('Browser')}")
                    else:
                        logging.warning("Chrome debugging port returned non-200 status code.")
                except Exception as e:
                    logging.warning(f"Chrome debugging port test failed: {e}")
                    logging.info("To enable Chrome debugging, start Chrome with: --remote-debugging-port=9222")
            
            # Check Accessibility API access if on macOS
            if system() == "Darwin" and HAS_PYOBJC and self.capture_data_path:
                try:
                    trusted = ApplicationServices.AXIsProcessTrustedWithOptions(None)
                    if trusted:
                        logging.info("Application has Accessibility API permissions")
                    else:
                        logging.warning("Application does NOT have Accessibility API permissions!")
                        logging.warning("Please enable in System Preferences > Security & Privacy > Privacy > Accessibility")
                except Exception as e:
                    logging.error(f"Error checking Accessibility permissions: {e}")

            self.obs_client.start_recording()

            while self._is_recording:
                try:
                    event = self.event_queue.get(timeout=0.1)
                    self.events_file.write(json.dumps(event) + "\n")
                    self.events_file.flush() # Force flush after every write
                except Empty:
                    pass
                except Exception as e:
                    logging.error(f"Error in recorder run loop writing event: {e}")
                    time.sleep(0.1)

        except Exception as e:
            logging.error(f"Error initializing or running recorder: {e}")
        finally:
            # Ensure final flush before cleanup attempts
            if self.events_file and not self.events_file.closed:
                 try: self.events_file.flush() 
                 except Exception: pass
            self._cleanup()

    def _cleanup(self):
        logging.debug("Recorder cleanup started.")
        logging.debug("Stopping input listeners/monitors...")

        # Stop AppKit monitor first if it exists
        if self.macos_key_monitor and HAS_PYOBJC:
            try:
                logging.info("Removing AppKit global key monitor.")
                AppKit.NSEvent.removeMonitor_(self.macos_key_monitor)
                self.macos_key_monitor = None
            except Exception as e:
                logging.error(f"Error removing AppKit monitor: {e}")

        # Stop pynput listeners
        if hasattr(self, 'mouse_listener') and self.mouse_listener.is_alive():
            try:
                self.mouse_listener.stop()
                self.mouse_listener.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error stopping mouse listener: {e}")
        if self.keyboard_listener and hasattr(self, 'keyboard_listener') and self.keyboard_listener.is_alive():
            try:
                self.keyboard_listener.stop()
                self.keyboard_listener.join(timeout=1.0)
            except Exception as e:
                logging.error(f"Error stopping keyboard listener: {e}")

        # --- Improved Queue Draining --- 
        logging.debug(f"Events left in queue before final drain: {self.event_queue.qsize()}")
        queued_events = []
        while not self.event_queue.empty():
            try:
                queued_events.append(self.event_queue.get_nowait())
            except Empty:
                break # Should not happen with empty() check, but safety first
        logging.debug(f"Drained {len(queued_events)} events from queue.")
        
        if self.events_file and not self.events_file.closed:
             if queued_events:
                 logging.info(f"Writing {len(queued_events)} remaining events to file...")
                 try:
                     for event in queued_events:
                         self.events_file.write(json.dumps(event) + "\n")
                     self.events_file.flush()
                     logging.info("Finished writing remaining events.")
                 except Exception as e:
                    logging.error(f"Error writing remaining events during cleanup: {e}")

        if self.metadata_manager:
            self.metadata_manager.end_collect()
        if self.obs_client:
            try:
                self.obs_client.stop_recording()
                if self.metadata_manager:
                     self.metadata_manager.add_obs_record_state_timings(self.obs_client.record_state_events)
                # Restore the original OBS profile
                self.obs_client.restore_profile()
            except Exception as e:
                 logging.error(f"Error stopping OBS recording or restoring profile: {e}")

        if self.events_file and not self.events_file.closed:
            self.events_file.close()
        if self.metadata_manager:
            self.metadata_manager.save_metadata()

        logging.debug("Recorder cleanup finished.")
        self.recording_stopped.emit()

    def stop_recording(self):
        if self._is_recording:
            logging.info("Stopping recording...")
            self._is_recording = False

    def toggle_pause(self):
        self._is_paused = not self._is_paused
        state = "paused" if self._is_paused else "resumed"
        logging.info(f"Recording {state}.")
        self.event_queue.put({
            "time_stamp": time.perf_counter(),
            "action": "pause" if self._is_paused else "resume"
        }, block=False)
        if self.obs_client:
            try:
                if self._is_paused:
                    self.obs_client.pause_recording()
                else:
                    self.obs_client.resume_recording()
            except Exception as e:
                logging.error(f"Error toggling OBS pause state: {e}")

    def _get_recording_path(self) -> str:
        recordings_dir = get_recordings_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(recordings_dir, timestamp)
        os.makedirs(path, exist_ok=True)
        return path

    def set_natural_scrolling(self, natural_scrolling: bool):
        self.natural_scrolling = natural_scrolling
        if self.metadata_manager:
            self.metadata_manager.set_scroll_direction(self.natural_scrolling)

    # Methods for main thread to check state
    def is_recording(self) -> bool:
        return self._is_recording

    def is_paused(self) -> bool:
        return self._is_paused

    # Slot to receive window focus data from the main thread
    @pyqtSlot(dict)
    def record_window_focus(self, event_data):
        if not self._is_recording or self._is_paused:
            return

        try:
            # Check if focus changed to/from a Chromium browser
            app_name = event_data.get("app_name", "Unknown")
            pid = event_data.get("pid")
            is_chromium = app_name in CHROMIUM_BUNDLE_IDS

            if is_chromium:
                if not self.is_chromium_focused or self.focused_pid != pid:
                    logging.info(f"Chromium browser detected: {app_name} (PID: {pid})")
                    self.is_chromium_focused = True
                    self.focused_pid = pid
            elif self.is_chromium_focused: # Focus changed away from Chromium
                logging.info("Focus moved away from Chromium browser.")
                self.is_chromium_focused = False
                self.focused_pid = None

            # Determine current mouse button state
            button_name = None
            pressed = False
            if self.mouse_buttons_pressed:
                button = next(iter(self.mouse_buttons_pressed))
                button_name = button.name
                pressed = True

            # Ensure app_name and window_title from event_data are used
            event = {
                "time_stamp": time.perf_counter(),
                "action": "window_focus",
                "app_name": event_data.get("app_name", "Unknown"), # Use fetched name
                "window_title": event_data.get("window_title", ""), # Use fetched title (placeholder)
                "pid": pid, # Keep PID in the event log
                "x": event_data.get("x"),
                "y": event_data.get("y"),
                "button": button_name,
                "pressed": pressed
            }
            self.event_queue.put(event, block=False)
            # logging.debug(f"Window focus event queued: {event}") # Can be noisy
        except Exception as e:
            logging.error(f"Error processing window focus event: {e}")

    # --- macOS Specific Key Handling ---
    def _macos_key_handler(self, event):
        if not HAS_PYOBJC:
            return event
        if not self._is_recording or self._is_paused:
            return event

        # Capture accessibility tree (always on macOS here)
        accessibility_tree_path = None
        if self.capture_data_path: # Check if path was created
            tree = capture_macos_accessibility_tree()
            if tree:
                tree_timestamp = time.perf_counter() # Use separate timestamp for filename
                # Determine filename based on action type for clarity
                action_type_for_file = "unknown_key_action"
                if event.type() == AppKit.NSEventTypeKeyDown: action_type_for_file = "keypress"
                elif event.type() == AppKit.NSEventTypeKeyUp: action_type_for_file = "keyrelease"
                elif event.type() == AppKit.NSEventTypeFlagsChanged: action_type_for_file = "flagschanged"

                filename = f"a11y_{action_type_for_file}_{tree_timestamp:.6f}.json"
                filepath = os.path.join(self.capture_data_path, filename)
                logging.debug(f"Attempting to save accessibility tree to: {filepath}")
                try:
                    with open(filepath, 'w') as f:
                        json.dump(tree, f, indent=2)
                    logging.debug(f"Successfully saved accessibility tree: {filepath}")
                    accessibility_tree_path = filepath
                except Exception as e:
                    logging.error(f"Error saving accessibility tree to {filepath} (macOS handler): {e}", exc_info=True)

        try:
            # Use integer type codes
            event_type = int(event.type()) # Ensure integer type
            key_code = event.keyCode()
            modifierFlags = event.modifierFlags()

            action = None
            final_name = None 

            # Use AppKit constants for event types
            if event_type == AppKit.NSEventTypeKeyDown: # KeyDown
                action = "press"
            elif event_type == AppKit.NSEventTypeKeyUp: # KeyUp
                action = "release"
            elif event_type == AppKit.NSEventTypeFlagsChanged: # FlagsChanged
                modifier_map = {
                    54: 'right_cmd', 55: 'cmd', 56: 'shift', 60: 'right_shift', 
                    58: 'alt', 61: 'right_alt', 59: 'ctrl', 62: 'right_ctrl', 
                    63: 'fn', 57: 'caps_lock'
                }
                mod_name = modifier_map.get(key_code)
                if mod_name:
                    # Check current flag state using AppKit constants
                    try: 
                        flag_map = {
                             'shift': AppKit.NSShiftKeyMask, 'right_shift': AppKit.NSShiftKeyMask,
                             'cmd': AppKit.NSCommandKeyMask, 'right_cmd': AppKit.NSCommandKeyMask,
                             'alt': AppKit.NSAlternateKeyMask, 'right_alt': AppKit.NSAlternateKeyMask,
                             'ctrl': AppKit.NSControlKeyMask, 'right_ctrl': AppKit.NSControlKeyMask,
                             'fn': AppKit.NSFunctionKeyMask, 
                             'caps_lock': AppKit.NSAlphaShiftKeyMask
                        }
                        modifier_flag = flag_map.get(mod_name)
                        if modifier_flag:
                            is_pressed = (modifierFlags & modifier_flag) != 0
                            action = "press" if is_pressed else "release"
                            final_name = mod_name
                        else: action = None 
                    except AttributeError as e_flags: # Catch if AppKit constants fail
                         logging.error(f"ERROR accessing AppKit flag constants in handler: {e_flags}")
                         action = None
                else: action = None
            else: return event

            # Get character info only for KeyDown/KeyUp
            chars = None
            chars_shifted = None
            if event_type == AppKit.NSEventTypeKeyDown or event_type == AppKit.NSEventTypeKeyUp:
                if not final_name: # If not already determined as a modifier
                    chars = event.charactersIgnoringModifiers()
                    chars_shifted = event.characters()
                    temp_name = chars_shifted if chars_shifted else f"KeyCode_{key_code}"
                    final_name = chars if chars and len(chars) == 1 and chars.isprintable() else temp_name
                    key_map = {
                        53: 'esc', 49: 'space', 36: 'enter', 51: 'backspace', 48: 'tab',
                        123: 'left', 124: 'right', 125: 'down', 126: 'up'
                    }
                    if not (chars and len(chars) == 1 and chars.isprintable()):
                        final_name = key_map.get(key_code, f"KeyCode_{key_code}")
            
            # Only queue if we determined a valid action and name
            if action and final_name:
                key_event = {
                    "time_stamp": time.perf_counter(),
                    "action": action,
                    "name": final_name,
                    "macos_key_code": key_code,
                    "macos_raw_chars": chars if chars is not None else None,
                    "macos_chars_shifted": chars_shifted if chars_shifted is not None else None,
                    "macos_modifierFlags": int(modifierFlags),
                    "accessibility_tree": accessibility_tree_path
                }
                self.event_queue.put(key_event, block=False)

            # Capture DOM snapshot if Chromium is focused and key is relevant
            dom_snapshot_path = None
            if self.is_chromium_focused and self.capture_data_path and \
               (action == "press" and final_name in DOM_CAPTURE_KEYS or 
                action == "release" and final_name in DOM_CAPTURE_KEYS or 
                action_type_for_file == "flagschanged"):  # Always capture on modifier key changes
                snapshot_mhtml = capture_chromium_dom_snapshot()
                if snapshot_mhtml:
                    # Reuse tree_timestamp for consistency if available, else use current time
                    snap_timestamp = tree_timestamp if 'tree_timestamp' in locals() else time.perf_counter()
                    # Include key name in filename if applicable
                    key_suffix = f"_{final_name}" if final_name else ""
                    filename = f"dom_{action_type_for_file}{key_suffix}_{snap_timestamp:.6f}.mhtml"
                    filepath = os.path.join(self.capture_data_path, filename)
                    try:
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(snapshot_mhtml)
                        key_event["dom_snapshot"] = filepath # Add path to existing event dict
                    except Exception as e:
                        logging.error(f"Error saving DOM snapshot (macOS handler): {e}")

        except Exception as e:
            logging.error(f"Error handling detailed macOS key event: {e}")

        return event

    # --- pynput Callbacks (used for mouse and non-macOS keys) ---
    def on_move(self, x, y):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "move",
                                  "x": x,
                                  "y": y}, block=False)

    def on_click(self, x, y, button, pressed):
        if not self._is_paused:
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)
            self.event_queue.put({
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed
            }, block=False)

    def on_scroll(self, x, y, dx, dy):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(),
                                  "action": "scroll",
                                  "x": x,
                                  "y": y,
                                  "dx": dx,
                                  "dy": dy}, block=False)

    # on_press/on_release only used for non-macOS or if AppKit fails
    def on_press(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "press", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def on_release(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "release", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)
    # --- End pynput Callbacks ---