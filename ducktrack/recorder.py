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
import socket # For port scanning
import hashlib
import filelock # Add filelock for thread safety
import tempfile
import threading

from pynput import keyboard, mouse
from pynput.keyboard import KeyCode
from PyQt6.QtCore import QThread, pyqtSignal, pyqtSlot

# Import PyObjC and framework modules conditionally for macOS
if system() == "Darwin":
    try:
        import objc
        import AppKit
        import Foundation
        import Quartz
        import ApplicationServices
        # ctypes and find_library are not needed for this revised approach

        # Set up default values in case we can't get the real ones
        kAXValueCGPointType = getattr(ApplicationServices, 'kAXValueCGPointType', 1)  # Fallback to 1
        kAXValueCGSizeType = getattr(ApplicationServices, 'kAXValueCGSizeType', 2)   # Fallback to 2
        kAXValueCGRectType = getattr(ApplicationServices, 'kAXValueCGRectType', 3)   # Fallback to 3
        kAXValueCFRangeType = getattr(ApplicationServices, 'kAXValueCFRangeType', 4) # Fallback to 4

        # Check if we can properly initialize Accessibility constants
        _has_ax_constants = (hasattr(ApplicationServices, 'kAXValueCGPointType') and
                            hasattr(ApplicationServices, 'kAXValueCGSizeType') and
                            hasattr(ApplicationServices, 'kAXValueCGRectType') and
                            hasattr(ApplicationServices, 'kAXValueCFRangeType'))
                            
        if _has_ax_constants:
            logging.info("Successfully initialized ApplicationServices constants")
        else:
            logging.warning("Could not initialize all ApplicationServices constants, using fallback values")

        _AXUIElementCreateApplication_func = None
        if hasattr(ApplicationServices, 'AXUIElementCreateApplication'):
            _AXUIElementCreateApplication_func = ApplicationServices.AXUIElementCreateApplication
            logging.info("Using ApplicationServices.AXUIElementCreateApplication directly.")
        else:
            logging.warning("AXUIElementCreateApplication not found directly on ApplicationServices. Trying bundle load then objc.function.")
            try:
                # First try to load the bundle
                try:
                    bundle = objc.loadBundle("ApplicationServices", 
                                             bundle_path=AppKit.NSBundle.bundleWithIdentifier_("com.apple.ApplicationServices").bundlePath(), 
                                             module_globals=globals())
                    if hasattr(bundle, "AXUIElementCreateApplication"):
                         _AXUIElementCreateApplication_func = bundle.AXUIElementCreateApplication
                         logging.info("Loaded AXUIElementCreateApplication via bundle loading.")
                except Exception as bundle_ex:
                    logging.warning(f"Failed to load ApplicationServices bundle: {bundle_ex}")
                    
                # If bundle loading failed, try objc.function
                if _AXUIElementCreateApplication_func is None and hasattr(objc, 'lookUpClass'):
                    try:
                        if objc.lookUpClass("AXUIElementRef") is not None: # Check if AX types are known at all
                            # This is a C function, not a method of a class.
                            # Signature: AXUIElementRef AXUIElementCreateApplication(pid_t pid);
                            # AXUIElementRef -> '@', pid_t -> 'i'
                            _AXUIElementCreateApplication_func = objc.function(
                                name='AXUIElementCreateApplication',
                                signature=b'@i' # Returns id (AXUIElementRef), takes int (pid_t)
                            )
                            logging.info("Loaded AXUIElementCreateApplication via objc.function(signature='@i').")
                    except Exception as func_ex:
                        logging.warning(f"Failed to create function with objc.function: {func_ex}")
                
                # Final fallback - try to dynamically load from dlsym if all else fails
                if _AXUIElementCreateApplication_func is None:
                    logging.error("Cannot define AXUIElementCreateApplication: PyObjC/CoreFoundation types seem unavailable or bundle load failed.")
                    try:
                        # Create a simpler stub function that will log errors but not crash
                        def ax_app_stub(pid):
                            logging.error(f"Attempted to call AXUIElementCreateApplication({pid}) but function is not available")
                            return None
                        _AXUIElementCreateApplication_func = ax_app_stub
                        logging.warning("Using stub implementation for AXUIElementCreateApplication")
                    except Exception as stub_ex:
                        logging.error(f"Failed to create stub function: {stub_ex}")
            except Exception as e_func:
                logging.error(f"Failed to load AXUIElementCreateApplication via bundle or objc.function: {e_func}", exc_info=True)
                # Create a stub function as a last resort
                def ax_app_stub(pid):
                    logging.error(f"Attempted to call AXUIElementCreateApplication({pid}) but function is not available")
                    return None
                _AXUIElementCreateApplication_func = ax_app_stub
                logging.warning("Using stub implementation for AXUIElementCreateApplication after errors")

        # Check if we have accessibility API permissions
        try:
            if hasattr(ApplicationServices, 'AXIsProcessTrustedWithOptions'):
                trusted = ApplicationServices.AXIsProcessTrustedWithOptions(None)
                if trusted:
                    logging.info("✅ Application has Accessibility API permissions")
                else:
                    logging.warning("⚠️ Application does NOT have Accessibility API permissions!")
                    logging.warning("Please enable in System Preferences > Security & Privacy > Privacy > Accessibility")
            else:
                logging.warning("⚠️ Cannot check Accessibility permissions - AXIsProcessTrustedWithOptions not available")
        except Exception as perm_e:
            logging.warning(f"⚠️ Error checking Accessibility permissions: {perm_e}")

        HAS_PYOBJC = True
    except ImportError as e:
        logging.error(f"PyObjC framework import failed: {e}")
        HAS_PYOBJC = False
    except Exception as e:
        logging.error(f"Unexpected error initializing PyObjC frameworks: {e}")
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
        if value is None:
            return None
            
        try:
            # Check if AXValueGetType is available
            if not hasattr(ApplicationServices, 'AXValueGetType'):
                logging.debug("AXValueGetType function not available")
                return f"<AXValue decode not supported>"
                
            # Access constants directly via our module variables
            value_type = ApplicationServices.AXValueGetType(value)
            
            # Check if constants are available
            constants_available = True
            if 'kAXValueCGPointType' not in globals():
                logging.debug("AXValue constants not available")
                constants_available = False
            
            # Use ctypes style byref for newer PyObjC, don't use objc.byref directly
            # as it may not exist in newer versions
            if constants_available and value_type == kAXValueCGPointType:
                point = Quartz.CGPoint()
                try:
                    # Try multiple approaches to handle different PyObjC versions
                    try:
                        if hasattr(objc, 'byref'):
                            ApplicationServices.AXValueGetValue(value, kAXValueCGPointType, objc.byref(point))
                        else:
                            # Alternative method for newer PyObjC
                            ApplicationServices.AXValueGetValue(value, kAXValueCGPointType, ctypes.byref(point))
                    except TypeError:
                        # Try without byref as a last resort
                        point = ApplicationServices.AXValueGetValue(value, kAXValueCGPointType)
                except Exception as e:
                    logging.error(f"Error decoding CGPoint: {e}")
                    return {"x": 0, "y": 0, "error": str(e)}  # Return a valid object with error info
                    
                # Make sure we have valid x/y values, PyObjC might return strange objects
                try:
                    return {'x': float(point.x), 'y': float(point.y)}
                except (TypeError, ValueError) as e:
                    logging.error(f"Invalid point coordinates: {e}")
                    return {"x": 0, "y": 0, "error": "Invalid coordinates"}
                    
            elif constants_available and value_type == kAXValueCGSizeType:
                size = Quartz.CGSize()
                try:
                    try:
                        if hasattr(objc, 'byref'):
                            ApplicationServices.AXValueGetValue(value, kAXValueCGSizeType, objc.byref(size))
                        else:
                            # Alternative method for newer PyObjC
                            ApplicationServices.AXValueGetValue(value, kAXValueCGSizeType, ctypes.byref(size))
                    except TypeError:
                        # Try without byref as a last resort
                        size = ApplicationServices.AXValueGetValue(value, kAXValueCGSizeType)
                except Exception as e:
                    logging.error(f"Error decoding CGSize: {e}")
                    return {"width": 0, "height": 0, "error": str(e)}
                    
                # Ensure valid values
                try:
                    return {'width': float(size.width), 'height': float(size.height)}
                except (TypeError, ValueError):
                    return {"width": 0, "height": 0, "error": "Invalid dimensions"}
                    
            elif constants_available and value_type == kAXValueCGRectType:
                rect = Quartz.CGRect()
                try:
                    try:
                        if hasattr(objc, 'byref'):
                            ApplicationServices.AXValueGetValue(value, kAXValueCGRectType, objc.byref(rect))
                        else:
                            # Alternative method for newer PyObjC
                            ApplicationServices.AXValueGetValue(value, kAXValueCGRectType, ctypes.byref(rect))
                    except TypeError:
                        # Try without byref as a last resort
                        rect = ApplicationServices.AXValueGetValue(value, kAXValueCGRectType)
                except Exception as e:
                    logging.error(f"Error decoding CGRect: {e}")
                    return {"x": 0, "y": 0, "width": 0, "height": 0, "error": str(e)}
                    
                # Ensure valid values
                try:
                    return {
                        'x': float(rect.origin.x), 
                        'y': float(rect.origin.y), 
                        'width': float(rect.size.width), 
                        'height': float(rect.size.height)
                    }
                except (TypeError, ValueError, AttributeError):
                    return {"x": 0, "y": 0, "width": 0, "height": 0, "error": "Invalid rectangle"}
                    
            elif constants_available and value_type == kAXValueCFRangeType:
                range_val = Quartz.CFRange()
                try:
                    try:
                        if hasattr(objc, 'byref'):
                            ApplicationServices.AXValueGetValue(value, kAXValueCFRangeType, objc.byref(range_val))
                        else:
                            # Alternative method for newer PyObjC
                            ApplicationServices.AXValueGetValue(value, kAXValueCFRangeType, ctypes.byref(range_val))
                    except TypeError:
                        # Try without byref as a last resort
                        range_val = ApplicationServices.AXValueGetValue(value, kAXValueCFRangeType)
                except Exception as e:
                    logging.error(f"Error decoding CFRange: {e}")
                    return {"location": 0, "length": 0, "error": str(e)}
                    
                # Ensure valid values
                try:
                    return {'location': int(range_val.location), 'length': int(range_val.length)}
                except (TypeError, ValueError, AttributeError):
                    return {"location": 0, "length": 0, "error": "Invalid range"}
            
            # If we got this far, we couldn't properly decode the value
            return f"<AXValue type {value_type}>" # Fallback for unknown types
        except AttributeError as e:
            logging.error(f"Missing attribute for AXValue decoding: {e}")
            return f"<AXValue attribute missing: {e}>"
        except Exception as e:
            logging.error(f"Error decoding AXValue: {e}")
            return f"<AXValue decode error: {e}>"

    def sanitize_for_json(obj):
        """Recursively convert known problematic types in a dict/list for JSON serialization."""
        if obj is None:
            return None
            
        try:
            # Handle dictionaries - recursively sanitize values
            if isinstance(obj, dict):
                return {str(k): sanitize_for_json(v) for k, v in obj.items()}
                
            # Handle lists and tuples - recursively sanitize elements
            elif isinstance(obj, (list, tuple)):
                return [sanitize_for_json(item) for item in obj]
                
            # Convert PyObjC Unicode strings to Python strings
            elif hasattr(objc, 'pyobjc_unicode') and isinstance(obj, objc.pyobjc_unicode):
                return str(obj)
                
            # Handle generic objc_object instances
            elif hasattr(objc, 'objc_object') and isinstance(obj, objc.objc_object):
                try:
                    # Try to convert to JSON-serializable type
                    if hasattr(obj, 'description'):
                        return str(obj.description())
                    else:
                        return str(obj)
                except Exception as e:
                    logging.debug(f"Error converting objc_object to string: {e}")
                    return f"<ObjC object: {type(obj).__name__}>"
                    
            # Handle NSDate objects
            elif hasattr(Foundation, 'NSDate') and isinstance(obj, Foundation.NSDate):
                try:
                    # Convert to ISO format string
                    time_interval = obj.timeIntervalSince1970()
                    from datetime import datetime
                    dt = datetime.fromtimestamp(time_interval)
                    return dt.isoformat()
                except Exception as e:
                    logging.debug(f"Error converting NSDate: {e}")
                    return str(obj)
                    
            # Handle NSNumber objects
            elif hasattr(AppKit, 'NSNumber') and isinstance(obj, AppKit.NSNumber):
                # Try to convert NSNumber types appropriately based on their type
                try:
                    if hasattr(obj, 'boolValue'):
                        return bool(obj.boolValue())
                    elif hasattr(obj, 'floatValue'):
                        return float(obj.floatValue())
                    elif hasattr(obj, 'intValue'):
                        return int(obj.intValue())
                    else:
                        return str(obj)
                except Exception as e:
                    logging.debug(f"Error converting NSNumber: {e}")
                    return str(obj)
                    
            # Handle NSArray/NSMutableArray
            elif hasattr(Foundation, 'NSArray') and isinstance(obj, Foundation.NSArray):
                return [sanitize_for_json(obj.objectAtIndex_(i)) for i in range(obj.count())]
                
            # Handle NSDictionary/NSMutableDictionary
            elif hasattr(Foundation, 'NSDictionary') and isinstance(obj, Foundation.NSDictionary):
                result = {}
                keys = obj.allKeys()
                for i in range(keys.count()):
                    key = keys.objectAtIndex_(i)
                    key_str = str(key)
                    val = obj.objectForKey_(key)
                    result[key_str] = sanitize_for_json(val)
                return result
                
            # Handle NSData by converting to Base64
            elif hasattr(Foundation, 'NSData') and isinstance(obj, Foundation.NSData):
                try:
                    # Convert NSData to base64 string
                    base64_data = obj.base64EncodedStringWithOptions_(0)
                    return f"<base64data:{base64_data}>"
                except Exception as e:
                    logging.debug(f"Error converting NSData: {e}")
                    return "<NSData object>"
                    
            # Special case for UI elements that might have circular references
            elif hasattr(obj, '_as_parameter_') and str(type(obj)).find('UI') >= 0:
                return f"<UI element: {type(obj).__name__}>"
                
            # For basic types (int, float, str, bool, None) just return as is
            elif isinstance(obj, (int, float, str, bool, type(None))):
                return obj
                
            # Any other type - convert to string
            else:
                return str(obj)
                
        except Exception as e:
            logging.error(f"Error in sanitize_for_json: {e}")
            return f"<Error sanitizing {type(obj).__name__}: {str(e)}>"

    def get_element_info(element):
        """Recursively get information about an AXUIElement and its children."""
        if not element:
            return {}
            
        info = {}
        attributes = [
            ApplicationServices.kAXRoleAttribute, 
            ApplicationServices.kAXSubroleAttribute, 
            ApplicationServices.kAXTitleAttribute,
            ApplicationServices.kAXIdentifierAttribute, 
            ApplicationServices.kAXValueAttribute
        ]
        
        # Make sure we have all attributes - if any are missing, skip them
        available_attributes = []
        for attr in attributes:
            if attr is None or not hasattr(ApplicationServices, attr.replace('kAX', '').replace('Attribute', '')):
                logging.debug(f"Skipping unavailable attribute: {attr}")
                continue
            available_attributes.append(attr)
        
        for attr in available_attributes:
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
                            # Use a safe string representation instead of failing
                            try:
                                info[attr.replace('kAX', '').replace('Attribute', '')] = str(value)
                            except:
                                info[attr.replace('kAX', '').replace('Attribute', '')] = "<decode error>"
                    elif isinstance(value, (list, tuple)):
                        child_elements = []
                        for el in value:
                            if el is not None and not isinstance(el, (str, int, float, bool, list, dict)):
                                try:
                                    child_elements.append(get_element_info(el))
                                except Exception as nested_e:
                                    logging.debug(f"Error processing child element: {nested_e}")
                                    # Add a placeholder instead of failing
                                    child_elements.append({"error": str(nested_e)})
                            else:
                                child_elements.append(el)
                        if child_elements:
                            info[attr.replace('kAX', '').replace('Attribute', '')] = child_elements
                        else:
                            info[attr.replace('kAX', '').replace('Attribute', '')] = value
                    else:
                        info[attr.replace('kAX', '').replace('Attribute', '')] = value
            except AttributeError as e:
                # If the attribute itself is missing from ApplicationServices, just skip it
                logging.debug(f"Attribute {attr} not available in ApplicationServices: {e}")
            except Exception as e:
                logging.debug(f"Error getting attribute {attr}: {e}")
                # Don't fail completely, just note the error and continue
                info[f"error_{attr.replace('kAX', '').replace('Attribute', '')}"] = str(e)

        # Get children recursively with better error handling
        try:
            if hasattr(ApplicationServices, 'kAXChildrenAttribute'):
                try:
                    result_children, children = ApplicationServices.AXUIElementCopyAttributeValue(element, ApplicationServices.kAXChildrenAttribute, None)
                    if result_children == 0 and children:  # kAXErrorSuccess is 0
                        info['Children'] = []
                        # Limit recursion depth and number of children to avoid huge trees
                        max_children = 50  # Reasonable limit to prevent excessive trees
                        for i, child in enumerate(children[:max_children]):
                            try:
                                child_info = get_element_info(child)
                                if child_info:
                                    info['Children'].append(child_info)
                            except Exception as child_e:
                                logging.debug(f"Error processing child {i}: {child_e}")
                                # Include error info instead of failing
                                info['Children'].append({"error": f"Child processing error: {str(child_e)}"})
                        
                        # If we limited the children, note that fact
                        if len(children) > max_children:
                            info['Children'].append({"note": f"Limited to {max_children} of {len(children)} children"})
                except Exception as children_e:
                    logging.debug(f"Error getting children attribute: {children_e}")
                    info['Children_error'] = str(children_e)
        except AttributeError:
            logging.debug("kAXChildrenAttribute not available")
        except Exception as e:
            logging.debug(f"Error getting children: {e}")
            info['Children_error'] = str(e)

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
            
            if not _AXUIElementCreateApplication_func:
                logging.error("AXUIElementCreateApplication function is not available (remained None). Cannot get app element.")
                return None
            
            # Call the function (it's either a direct PyObjC function or one defined by objc.function)
            app_element = _AXUIElementCreateApplication_func(pid)
            
            if not app_element:
                # If app_element is None (e.g. from objc.NULL or if the function returned null legitimately)
                logging.warning(f"AXUIElementCreateApplication returned null or an equivalent for PID {pid}.")
                return None

            # No need to bridge with objc.objc_object(c_void_p=...) if _AXUIElementCreateApplication_func 
            # is a proper PyObjC function (either direct or via objc.function), as it should return a PyObjC object.

            # Get focused window - use try/except for each API call to handle PyObjC binding issues
            focused_window = None
            try:
                # Only attempt this if the constants are available
                if hasattr(ApplicationServices, 'kAXFocusedWindowAttribute'):
                    result, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
                        app_element, 
                        ApplicationServices.kAXFocusedWindowAttribute, 
                        None
                    )
                    
                    if result != 0 or not focused_window:  # kAXErrorSuccess is 0
                        logging.debug(f"Could not get focused window (result={result}), trying to get any window")
                        focused_window = None
                else:
                    logging.warning("kAXFocusedWindowAttribute not available, falling back to windows list")
            except (AttributeError, ValueError, TypeError) as e:
                logging.warning(f"Error accessing focused window attribute: {e}")
                focused_window = None
            except Exception as e:
                logging.warning(f"Unexpected error getting focused window: {e}")
                focused_window = None
            
            # If focused window failed, try getting any window
            if not focused_window:
                try:
                    # Only attempt this if the constants are available
                    if hasattr(ApplicationServices, 'kAXWindowsAttribute'):
                        result_windows, windows = ApplicationServices.AXUIElementCopyAttributeValue(
                            app_element, 
                            ApplicationServices.kAXWindowsAttribute, 
                            None
                        )
                        
                        if result_windows == 0 and windows and len(windows) > 0:
                            focused_window = windows[0]
                            logging.debug("Using first window from list as fallback.")
                except (AttributeError, ValueError, TypeError) as e:
                    logging.warning(f"Error accessing windows attribute: {e}")
                except Exception as e:
                    logging.warning(f"Unexpected error getting window list: {e}")
            
            if not focused_window:
                # Last resort: try to create a simple representation of the application
                logging.warning(f"Accessibility Capture: Could not get any windows for app {app_name}.")
                return {
                    "application": app_name,
                    "pid": pid,
                    "error": "No accessible windows found",
                    "timestamp": datetime.now().isoformat()
                }

            # Use a safer version of get_element_info with better error handling
            try:
                logging.debug("Starting to build accessibility tree...")
                tree = get_element_info(focused_window)
                if not tree:
                    logging.warning("Generated empty accessibility tree")
                    return {
                        "application": app_name,
                        "pid": pid,
                        "window": "Unknown",
                        "error": "Empty accessibility tree",
                        "timestamp": datetime.now().isoformat()
                    }

                # Sanitize the tree before returning
                sanitized_tree = sanitize_for_json(tree)
                if not sanitized_tree:
                    logging.warning("Sanitized accessibility tree is empty")
                    return {
                        "application": app_name,
                        "pid": pid,
                        "window": "Unknown",
                        "error": "Empty sanitized tree",
                        "timestamp": datetime.now().isoformat()
                    }
                    
                logging.debug(f"Successfully captured accessibility tree for {app_name}")
                return sanitized_tree
            except Exception as tree_e:
                logging.error(f"Error building accessibility tree: {tree_e}")
                return {
                    "application": app_name,
                    "pid": pid,
                    "error": f"Tree building failed: {str(tree_e)}",
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            logging.error(f"Error capturing macOS accessibility tree: {e}", exc_info=True)
            # Return a minimal fallback that's valid JSON but indicates the error
            return {
                "error": f"Accessibility capture failed: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
else:
    # Provide a dummy function if not on macOS or Accessibility fails
    def capture_macos_accessibility_tree():
        logging.debug("capture_macos_accessibility_tree called but not on macOS or PyObjC failed")
        return None

# --- Constants ---
# Common Chrome debugging ports
CHROMIUM_DEBUG_PORTS = [9222, 9223, 9224, 9333, 8080]

CHROMIUM_BUNDLE_IDS = {
    "com.google.Chrome",
    "com.microsoft.Edge",
    "com.brave.Browser",
    "com.operasoftware.Opera",
    "com.vivaldi.Vivaldi",
    "org.chromium.Chromium",
    "com.google.Chrome.canary"
    # Add others as needed
}

# Keys that should trigger DOM capture
DOM_CAPTURE_KEYS = {
    'enter', 'tab', 'backspace', 'delete',
    'esc', 'space', 
    'left', 'right', 'up', 'down',
    'pageup', 'pagedown', 'home', 'end',
    'shift', 'ctrl', 'alt', 'cmd',
}

# Keys that should trigger accessibility tree captures
A11Y_CAPTURE_KEYS = {
    'enter', 'tab', 'backspace', 'delete',
    'esc', 'space', 
    'left', 'right', 'up', 'down',
    'pageup', 'pagedown', 'home', 'end',
    'shift', 'ctrl', 'alt', 'cmd',
}

# Minimum interval between captures to avoid duplicates
MIN_A11Y_CAPTURE_INTERVAL = 2.0  # Changed from 3.0 to match DOM interval
MIN_DOM_CAPTURE_INTERVAL = 2.0  # Reduced from 3.0 (previously 5.0)

# URL monitoring
PAGE_CHECK_INTERVAL = 2.0
PERIODIC_CAPTURE_INTERVAL = 30.0

# Page loading verification - RESTORED TO PREVIOUS WORKING VALUES
PAGE_LOAD_MIN_MHTML_SIZE = 500       # Reduced from 50_000 to accept even small placeholders
PAGE_LOAD_MIN_HTML_CONTENT_SIZE = 500  # Min documentElement.outerHTML.length
PAGE_LOAD_TIMEOUT = 15.0                # Max seconds for entire smart capture process
PAGE_LOAD_ATTEMPTS = 3
PAGE_LOAD_DELAY = 1.0                   # Reduced from 2.0 seconds (was too long)

# Content stability check parameters - RELAXED
PAGE_LOAD_STABILITY_ATTEMPTS = 1        # Reduced from 2
PAGE_LOAD_STABILITY_DELAY = 0.5         # Reduced from 1.0 second
PAGE_LOAD_STABILITY_THRESHOLD = 1.5     # Increased from 1.1 (more forgiving)

# Deduplication capacity
RECENT_DOM_HASH_CAPACITY = 30
RECENT_A11Y_HASH_CAPACITY = 20
RECENT_HTML_FALLBACK_HASH_CAPACITY = 15 # For HTML fallbacks

# Flag to prevent creating folders during shutdown
SHUTDOWN_IN_PROGRESS = False

# Add a constant for minimum DOM size
MIN_DOM_CONTENT_SIZE = 500  # Minimum size in bytes to consider a DOM valid

# Add a fixed version of pychrome's Tab class to handle empty messages properly
# Keep a reference to the original _recv_loop method
original_tab_recv_loop = pychrome.Tab._recv_loop

# We'll revert to a simpler approach without modifying pychrome's internals
pychrome.Tab._recv_loop = original_tab_recv_loop

class Recorder(QThread):
    """
    Makes recordings.
    """
    
    recording_stopped = pyqtSignal()
    # Signal to potentially inform main thread about focus (optional)
    # focus_changed = pyqtSignal(dict)

    def __init__(self, natural_scrolling: bool):
        super().__init__()
        
        # Reset shutdown flag to ensure new recording path is created correctly
        global SHUTDOWN_IN_PROGRESS
        SHUTDOWN_IN_PROGRESS = False
        
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
        
        # Initialize DOM capture timing trackers 
        self.last_a11y_capture_time = 0
        self.last_dom_capture_time = 0
        
        # Add tracking for previously captured DOMs and URLs to prevent duplicates
        self.last_captured_url = None
        self.last_dom_capture_time_by_url = {}  # Track time of last DOM capture by URL
        self.dom_capture_cooldown = 5.0  # Increase from 2.0 to 5.0 seconds to reduce duplicates
        self.last_dom_url_hash = None  # Track last URL hash for better deduplication
        
        # Add tracking for a11y tree captures to prevent duplicates
        self.last_a11y_content_hash = None  # Track last a11y tree hash for deduplication
        self.a11y_capture_cooldown = 5.0  # Minimum seconds between a11y captures for similar content
        
        # Track the last DOM snapshot's hash to avoid duplicates
        self.last_dom_hash = None
        
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
        
        # Initialize managers later in run() or ensure thread safety if needed earlier
        self.metadata_manager = None
        self.obs_client = None

        # Listeners setup
        # Listeners are initialized here but started in run()
        logging.info("Initializing mouse listener with on_click, on_move, and on_scroll handlers")
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
        self.macos_mouse_monitor = None # Holder for potential macOS-specific mouse monitor

        # Add tracking for current browser URL to detect page changes
        self.current_browser_url = None
        self.last_browser_url = None
        self.url_check_timer = None
        self.periodic_capture_timer = None
        self.background_workers = []
        
        # Add tracking for window focus to better detect switches
        self.current_window_id = None
        self.last_window_id = None
        
        # Add tracking of recent DOM hashes to avoid duplicates
        self.recent_dom_hashes = []
        # Add tracking of recent a11y tree hashes to avoid duplicates
        self.recent_a11y_hashes = []
        self.recent_html_fallback_hashes = [] # For deduplicating HTML fallbacks

        # Add lock for DOM capture critical sections
        self.dom_capture_lock = threading.Lock()
        # Add lock for a11y capture critical sections (good practice, though less contention expected)
        self.a11y_capture_lock = threading.Lock()

    def on_move(self, x, y):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "move", 
                                  "x": x, 
                                  "y": y}, block=False)
        
    def on_click(self, x, y, button, pressed):
        """Process mouse click events and capture DOM/accessibility data"""
        if not self._is_paused:
            logging.info(f"Mouse {'press' if pressed else 'release'} detected at ({x},{y}) - button: {button.name}")
            
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)

            # Create the click event dictionary
            click_event = {
                "time_stamp": time.perf_counter(),
                "action": "click",
                "x": x,
                "y": y,
                "button": button.name,
                "pressed": pressed,
                "accessibility_tree": None,
                "dom_snapshot": None
            }

            # ONLY process captures on mouse RELEASE events (not press) to reduce duplicate captures
            if not pressed and (button.name == 'left' or button.name == 'right') and self.capture_data_path:
                # Use the actual button name in the capture_type
                button_type = button.name.lower()  # 'left' or 'right'
                
                # Capture accessibility tree on macOS with less frequency (only for specific events)
                if system() == "Darwin" and HAS_PYOBJC:
                    current_time = time.perf_counter()
                    # Check if enough time has elapsed since last a11y tree capture
                    if current_time - self.last_a11y_capture_time >= self.a11y_capture_cooldown:
                        logging.info(f"Capturing accessibility tree for {button_type} mouse release")
                        tree = capture_macos_accessibility_tree()
                        if tree:
                            try:
                                # Check for duplicates by hashing the tree content
                                tree_str = json.dumps(tree)
                                tree_hash = hashlib.md5(tree_str.encode()).hexdigest()
                                
                                # Skip if this tree is very similar to the last one
                                if tree_hash == self.last_a11y_content_hash:
                                    logging.info(f"Skipping duplicate a11y tree capture (hash: {tree_hash[:8]})")
                                else:
                                    # Create directory for accessibility trees if it doesn't exist
                                    os.makedirs(self.capture_data_path, exist_ok=True)
                                    
                                    # Construct the filename for the accessibility tree JSON file
                                    a11y_file = os.path.join(self.capture_data_path, f"a11y_{button_type}_click_{current_time:.6f}.json")
                                    
                                    # Save the tree to a file
                                    with open(a11y_file, 'w', encoding='utf-8') as f:
                                        f.write(json.dumps(tree))
                                    
                                    logging.info(f"Captured accessibility tree on {button_type} click: {a11y_file}")
                                    
                                    # Update tracking info
                                    self.last_a11y_content_hash = tree_hash
                                    self.last_a11y_capture_time = current_time
                                    
                                    # Add the a11y path to the click event
                                    click_event["accessibility_tree"] = a11y_file
                            except Exception as e:
                                logging.error(f"Failed to save accessibility tree: {e}")
                        else:
                            logging.info(f"No accessibility tree available for {button_type} click")
                    else:
                        logging.info(f"Skipping a11y tree capture - cooldown period active ({current_time - self.last_a11y_capture_time:.2f}s < {self.a11y_capture_cooldown}s)")
                    
                    # Get URL and title for DOM capture
                    url, title = self._get_active_tab_url_title() or ("", "")
                    
                    # Record DOM snapshot using specific capture type with button name
                    dom_path = self._smart_dom_capture(
                        url=url,
                        title=title,
                        capture_type=f"click_{button_type}_click",
                        x=x,
                        y=y,
                        button=button_type
                    )
                    
                    # Add the DOM snapshot path to the click event
                    click_event["dom_snapshot"] = dom_path
                
                # Queue the click event
                self.event_queue.put(click_event, block=False)

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
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "press", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)

    def on_release(self, key):
        if not self._is_paused:
            self.event_queue.put({"time_stamp": time.perf_counter(), 
                                  "action": "release", 
                                  "name": key.char if type(key) == KeyCode else key.name}, block=False)
    
    def run(self):
        self._is_recording = True
        self._is_paused = False
        self.mouse_buttons_pressed.clear()
        self.macos_key_monitor = None # Ensure monitor is reset
        self.macos_mouse_monitor = None # Ensure monitor is reset
        self.capture_data_path = None # Initialize path for captures
        self.recent_dom_hashes = [] # Initialize empty list of DOM hashes
        self.recent_a11y_hashes = [] # Initialize empty list of a11y tree hashes
        self.recent_html_fallback_hashes = [] # Initialize HTML fallback hash list
        
        # Reset URL tracking
        self.current_browser_url = None
        self.last_browser_url = None
        self.current_window_id = None
        self.last_window_id = None
        
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
            
            # Explicitly log mouse/keyboard listener info
            logging.info("Starting mouse listener for click, move, and scroll events")
            
            # ON MACOS: Also add a supplementary monitor for mouse events using AppKit
            # This gives us redundancy in case pynput misses some events
            if system() == "Darwin" and HAS_PYOBJC:
                logging.info("Setting up additional AppKit mouse monitor for redundancy")
                try:
                    # Move SyntheticButton class definition outside the event handler
                    class SyntheticButton:
                        def __init__(self, name):
                            self.name = name
                            
                    # Define mouse event handler that works with AppKit NSEvents
                    def macos_mouse_handler_wrapper(event):
                        try:
                            event_type = event.type()
                            
                            # Handle left mouse down/up events (primaryMouseUp/Down = 1/2)
                            if event_type == AppKit.NSEventTypeLeftMouseDown:
                                location = event.locationInWindow()
                                x, y = location.x, location.y
                                logging.info(f"AppKit detected mouse down at ({x},{y})")
                                # Create a synthetic mouse object with a name property for our handler
                                button = SyntheticButton("left")
                                # Call our regular handler (will handle DOM capture)
                                self.on_click(x, y, button, True)
                            elif event_type == AppKit.NSEventTypeLeftMouseUp:
                                location = event.locationInWindow()
                                x, y = location.x, location.y
                                logging.info(f"AppKit detected mouse up at ({x},{y})")
                                button = SyntheticButton("left")
                                self.on_click(x, y, button, False)
                            # Handle right mouse down/up events
                            elif event_type == AppKit.NSEventTypeRightMouseDown:
                                location = event.locationInWindow()
                                x, y = location.x, location.y
                                logging.info(f"AppKit detected right mouse down at ({x},{y})")
                                button = SyntheticButton("right")
                                self.on_click(x, y, button, True)
                            elif event_type == AppKit.NSEventTypeRightMouseUp:
                                location = event.locationInWindow()
                                x, y = location.x, location.y
                                logging.info(f"AppKit detected right mouse up at ({x},{y})")
                                button = SyntheticButton("right")
                                self.on_click(x, y, button, False)
                        except Exception as e:
                            logging.error(f"Error in AppKit mouse handler: {e}")
                        return event
                    
                    # Add a global monitor for mouse events
                    event_mask = (
                        AppKit.NSEventMaskLeftMouseDown | 
                        AppKit.NSEventMaskLeftMouseUp | 
                        AppKit.NSEventMaskRightMouseDown | 
                        AppKit.NSEventMaskRightMouseUp
                    )
                    self.macos_mouse_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                        event_mask,
                        macos_mouse_handler_wrapper
                    )
                    logging.info("AppKit mouse monitor created successfully")
                except Exception as e:
                    logging.error(f"Failed to create AppKit mouse monitor: {e}")
            
            # Start standard pynput mouse listener (works on all platforms)
            self.mouse_listener.start()
            logging.info("Mouse listener started successfully")

            if self.keyboard_listener: # Use pynput if available
                logging.info("Starting pynput keyboard listener")
                self.keyboard_listener.start()
                logging.info("Pynput keyboard listener started successfully")
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

            # Add periodic page checking for more reliable capturing
            self._start_page_monitoring()

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

    def _start_page_monitoring(self):
        """Start monitoring browser pages for changes"""
        if not self.capture_data_path:
            logging.error("No capture path, can't start page monitoring")
            return
            
        # Create a timer that periodically checks browser URL
        if system() == "Darwin":
            try:
                import threading
                self.url_check_timer = threading.Timer(PAGE_CHECK_INTERVAL, self._check_browser_page)
                self.url_check_timer.daemon = True
                self.url_check_timer.start()
                logging.info("Started browser page monitoring timer")
                
                # Also add periodic DOM capture timer - with longer interval
                self.periodic_capture_timer = threading.Timer(PERIODIC_CAPTURE_INTERVAL, self._perform_periodic_capture)
                self.periodic_capture_timer.daemon = True
                self.periodic_capture_timer.start()
                logging.info(f"Started periodic DOM capture timer (every {PERIODIC_CAPTURE_INTERVAL} seconds)")
            except Exception as e:
                logging.error(f"Failed to start page monitoring: {e}")
    
    def _check_browser_page(self):
        """Check if browser URL or window has changed and capture DOM if needed"""
        if not self._is_recording or self._is_paused:
            # Restart timer if recording isn't paused
            if self._is_recording and not self._is_paused:
                try:
                    import threading
                    self.url_check_timer = threading.Timer(PAGE_CHECK_INTERVAL, self._check_browser_page)
                    self.url_check_timer.daemon = True
                    self.url_check_timer.start()
                except Exception as e:
                    logging.error(f"Failed to restart URL check timer: {e}")
            return
            
        # Run the page check in a thread to avoid blocking
        try:
            import threading
            worker = threading.Thread(target=self._background_page_check, daemon=True)
            worker.start()
            
            # Restart timer
            self.url_check_timer = threading.Timer(PAGE_CHECK_INTERVAL, self._check_browser_page)
            self.url_check_timer.daemon = True
            self.url_check_timer.start()
        except Exception as e:
            logging.error(f"Error in _check_browser_page: {e}")
    
    def _background_page_check(self):
        """Check for browser page changes"""
        try:
            # Skip if browser is not focused
            if not self.is_chromium_focused:
                return
            
            # Check for open Chrome debugging port
            port = self._find_chrome_debugging_port()
            if not port:
                return
        
            # Get list of tabs
            try:
                tabs_response = requests.get(f"http://localhost:{port}/json/list", timeout=1)
                if tabs_response.status_code != 200:
                    return
                
                tabs = tabs_response.json()
                if not tabs:
                    return
            
                # Find active tab
                active_tab = None
                for tab in tabs:
                    if tab.get('type') == 'page' and tab.get('url'):
                        url = tab.get('url')
                        # Skip browser UI pages and blank or loading pages
                        if not (url.startswith('chrome') or 
                                url.startswith('edge:') or 
                                url.startswith('brave:') or
                                url == 'about:blank' or
                                url.startswith('chrome://newtab') or
                                url.startswith('edge://newtab') or
                                url.startswith('brave://newtab')):
                            if tab.get('active'):
                                active_tab = tab
                                break
                            elif not active_tab:
                                active_tab = tab
            
                if active_tab:
                    url = active_tab.get('url')
                    title = active_tab.get('title', 'Unknown')
                    window_id = active_tab.get('id', 'Unknown')
                    
                    # Check if mouse button is currently pressed - if so, delay capture
                    if self.mouse_buttons_pressed:
                        logging.info("Delaying page change capture because mouse button is pressed")
                        return
                    
                    # Check if URL or window changed
                    if url != self.current_browser_url or window_id != self.current_window_id:
                        self.last_browser_url = self.current_browser_url
                        self.current_browser_url = url
                        self.last_window_id = self.current_window_id
                        self.current_window_id = window_id
                        
                        # Extra check: if this URL was captured very recently (by a click handler), skip it
                        url_hash = hashlib.md5(url.encode()).hexdigest()[:8] if url else None
                        
                        # Skip if we just captured this exact URL hash very recently
                        current_time = time.perf_counter()
                        if url_hash == self.last_dom_url_hash:
                            time_since_last_capture = current_time - self.last_dom_capture_time
                            if time_since_last_capture < self.dom_capture_cooldown * 0.5:
                                logging.info(f"Skipping page change capture - URL hash {url_hash} captured too recently")
                                return
                        
                        logging.info(f"Browser page changed to: {title} ({url})")
                        
                        # Skip for "empty" or "loading" titles that indicate the page isn't ready
                        if (title == 'about:blank' or 
                            title == 'New Tab' or 
                            title == 'Loading...' or
                            not title or 
                            len(title) < 3):
                            logging.info(f"Skipping DOM capture for empty/loading page: {title}")
                            return
                        
                        # Capture DOM in background thread with a longer delay for page changes
                        import threading
                        dom_thread = threading.Thread(
                            target=self._capture_dom_for_page_change,
                            args=(url, title),
                            daemon=True
                        )
                        dom_thread.start()
            except Exception as e:
                logging.debug(f"Error checking browser tabs: {e}")
        except Exception as e:
            logging.error(f"Error in background page check: {e}")
    
    def _capture_dom_for_page_change(self, url, title):
        """Capture DOM snapshot when the page changes"""
        if not self.capture_data_path:
            return
            
        logging.info(f"Capturing DOM for page change: {title}")
        
        # Add a more substantial delay to give the page time to fully load
        # This helps avoid capturing blank/loading pages
        time.sleep(PAGE_LOAD_DELAY * 1.5)  # Increased delay
        
        # Capture DOM with multiple attempts to ensure it's fully loaded
        dom_path = self._smart_dom_capture(url, title, "page_change")
        
        # If it failed or detected a blank page, try one more time after a longer delay
        if not dom_path:
            logging.info("First attempt to capture page change failed, trying again after delay...")
            time.sleep(PAGE_LOAD_DELAY * 2)  # Even longer delay for second attempt
            self._smart_dom_capture(url, title, "page_change")

    def _smart_dom_capture(self, url, title, capture_type, max_retries=PAGE_LOAD_ATTEMPTS, x=None, y=None, button=None):
        """Smart DOM capture with duplicate detection to avoid capturing identical/similar pages."""
        # Protect the critical section with a lock
        with self.dom_capture_lock:
            # Don't capture if recording is paused or we're not in a browser
            if not self._is_recording or self._is_paused or not self.is_chromium_focused:
                return None
                
            logging.info(f"Starting DOM capture for {capture_type} (URL: {url})")
            
            current_time = time.perf_counter()
            
            # Generate a URL hash to detect same pages even with different URL params
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8] if url else None
            
            # Skip if we just captured this exact URL hash very recently (unless it's a page change)
            if url_hash == self.last_dom_url_hash and not capture_type.startswith("page_change"):
                time_since_last_capture = current_time - self.last_dom_capture_time
                if time_since_last_capture < self.dom_capture_cooldown * 0.5:  # Use stricter cooldown for same URL hash
                    logging.info(f"Skipping DOM capture for {url_hash} - very recent duplicate ({time_since_last_capture:.2f}s < {self.dom_capture_cooldown * 0.5}s)")
                    return None
            
            # Check if we've captured too recently for this URL
            if url in self.last_dom_capture_time_by_url:
                time_since_last_capture = current_time - self.last_dom_capture_time_by_url[url]
                # If this is a click on the same URL and it's been less than cooldown seconds, skip capturing
                if capture_type.startswith("click_") and time_since_last_capture < self.dom_capture_cooldown:
                    logging.info(f"Skipping DOM capture for {url} - cooldown period active ({time_since_last_capture:.2f}s < {self.dom_capture_cooldown}s)")
                    return None
            
            # Special case for page_change - always capture those
            # For clicks, check if we already captured this URL recently
            if not capture_type.startswith("page_change") and url == self.last_captured_url:
                # If the last capture was too recent, skip this one
                if current_time - self.last_dom_capture_time_by_url.get(url, 0) < self.dom_capture_cooldown:
                    logging.info(f"Skipping DOM capture for click on same URL ({url}), captured too recently")
                    return None
            
            # Skip empty or about:blank pages
            if not url or url == "about:blank" or not title:
                logging.info(f"Skipping DOM capture for empty/blank page: {url}")
                return None
            
            # Attempt to capture the DOM snapshot
            port = self._find_chrome_debugging_port()
            if not port:
                logging.warning("No Chrome debugging port found")
                return None
                
            try:
                # Capture the DOM snapshot
                snapshot_data = capture_chromium_dom_snapshot(port)
                
                if not snapshot_data or snapshot_data == "{}":
                    logging.warning("Empty DOM snapshot returned")
                    return None
                    
                # Check if this DOM is too similar to the last one
                dom_hash = self._calculate_dom_hash(snapshot_data)
                if dom_hash == self.last_dom_hash:
                    logging.info("Skipping DOM capture - identical to previous capture")
                    return None
                    
                # Create the folder for DOM snapshots if it doesn't exist
                os.makedirs(self.capture_data_path, exist_ok=True)
                
                # Create a unique filename
                dom_file = f"dom_{capture_type}_{url_hash}_{current_time:.6f}.mhtml"
                dom_file_path = os.path.join(self.capture_data_path, dom_file)
                
                # Save the DOM snapshot
                with open(dom_file_path, 'w', encoding='utf-8') as f:
                    f.write(snapshot_data)
                    
                # Update tracking for this URL and DOM
                self.last_captured_url = url
                self.last_dom_capture_time_by_url[url] = current_time
                self.last_dom_hash = dom_hash
                self.last_dom_url_hash = url_hash
                
                # Log the capture
                logging.info(f"DOM snapshot captured: {dom_file_path}")
                
                # Update the event with the DOM snapshot info
                self._add_dom_event(dom_file_path, url, title, True, capture_type, x, y, button)
                
                return dom_file_path
                
            except Exception as e:
                logging.error(f"Error capturing DOM snapshot: {e}")
                return None

    def _calculate_dom_hash(self, dom_data):
        """Calculate a hash of the DOM data to detect duplicate captures.
        This extracts the key parts of the DOM that would indicate if it's a different page.
        """
        try:
            # Use only the first 50KB of the DOM to create a hash - this speeds up comparison
            # and still captures enough to detect duplicates
            sample = dom_data[:50000]
            return hashlib.md5(sample.encode()).hexdigest()
        except Exception as e:
            logging.error(f"Error calculating DOM hash: {e}")
            return None

    def _find_chrome_debugging_port(self):
        """Find an available Chrome debugging port"""
        # ... (current implementation is okay, but pychrome calls later might fail)
        # No changes needed here for now, as this uses requests, not pychrome directly for discovery
        for port in range(9222, 9232):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.3)
                    if sock.connect_ex(('127.0.0.1', port)) == 0:
                        try:
                            response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=0.5)
                            if response.status_code == 200:
                                browser_info = response.json()
                                logging.info(f"Found active Chrome port: {port} ({browser_info.get('Browser')})")
                                return port
                        except (requests.exceptions.RequestException, json.JSONDecodeError):
                            try:
                                response = requests.get(f"http://localhost:{port}/json/version", timeout=0.5)
                                if response.status_code == 200:
                                    browser_info = response.json()
                                    logging.info(f"Found active Chrome port (localhost): {port} ({browser_info.get('Browser')})")
                                    return port
                            except (requests.exceptions.RequestException, json.JSONDecodeError):
                                pass 
            except socket.error:
                pass
        logging.warning("No active Chrome debugging port found.")
        return None

    def _capture_dom_snapshot_with_details(self, port):
        """Captures DOM snapshot. Returns MHTML if successful, otherwise tries for HTML fallback."""
        logging.info(f"[_capture_debug] Attempting connection for DOM snapshot on port {port}")
        browser = None
        actual_cdp_tab = None
        # Initialize return dictionary with defaults
        result_details = {
            "mhtml_data": None, "mhtml_size": 0, 
            "html_data": None, "html_size": 0,
            "is_content_complete": False, "html_length": 0,
            "is_fallback": False
        }

        try:
            browser = pychrome.Browser(url=f"http://127.0.0.1:{port}")
            logging.info(f"[_capture_debug] Browser object created for 127.0.0.1:{port}")
        except Exception as e_conn:
            logging.warning(f"[_capture_debug] Failed Browser() for 127.0.0.1:{port}, trying localhost. Error: {e_conn}")
            try:
                browser = pychrome.Browser(url=f"http://localhost:{port}")
                logging.info(f"[_capture_debug] Browser object created for localhost:{port}")
            except Exception as e_conn_localhost:
                logging.error(f"[_capture_debug] All Browser() connection attempts failed for port {port}: {e_conn_localhost}")
                return result_details # Return defaults indicating failure
        
        if not browser:
            logging.error("[_capture_debug] Browser object None after attempts.")
            return result_details

        try:
            # First try to get all tabs
            try:
                tabs_list = browser.list_tab()
                if not tabs_list:
                    logging.warning("[_capture_debug] No tabs from browser.list_tab().")
                    return result_details
            except Exception as e_list:
                logging.error(f"[_capture_debug] Error listing tabs: {e_list}")
                return result_details
            
            # Simplified tab selection: first 'page' type not chrome:// or edge:// or brave://
            selected_tab = None
            for tab in tabs_list:
                tab_url = getattr(tab, 'url', None) if hasattr(tab, 'url') else tab.get('url', '')
                tab_type = getattr(tab, 'type', None) if hasattr(tab, 'type') else tab.get('type', '')
                
                if tab_type == 'page' and tab_url and not (
                    tab_url.startswith('chrome:') or 
                    tab_url.startswith('edge:') or
                    tab_url.startswith('brave:') or
                    tab_url.startswith('about:')
                ):
                    selected_tab = tab
                    break
            
            # If no suitable tab found, use first tab
            if not selected_tab and tabs_list:
                selected_tab = tabs_list[0]
                
            if not selected_tab:
                logging.warning("[_capture_debug] No tabs available to capture.")
                return result_details
                
            # Get tab ID to find the actual tab object
            tab_id = None
            if isinstance(selected_tab, dict):
                tab_id = selected_tab.get('id')
            elif hasattr(selected_tab, 'id'):
                tab_id = selected_tab.id
            
            if not tab_id:
                logging.warning("[_capture_debug] Cannot determine tab ID.")
                return result_details
                
            # Find actual tab object - try to get it directly if it's already a pychrome.Tab
            if hasattr(selected_tab, 'start') and callable(getattr(selected_tab, 'start')):
                actual_cdp_tab = selected_tab
                logging.info(f"[_capture_debug] Using selected tab directly - ID: {actual_cdp_tab.id}")
            else:
                # Search for the tab by ID
                try:
                    for tab in browser.list_tab():
                        if hasattr(tab, 'id') and tab.id == tab_id:
                            actual_cdp_tab = tab
                            logging.info(f"[_capture_debug] Found tab by ID matching: {tab_id}")
                            break
                except Exception as e_search:
                    logging.error(f"[_capture_debug] Error searching for tab: {e_search}")
                    return result_details
                    
            if not actual_cdp_tab:
                logging.warning(f"[_capture_debug] Could not find tab with ID {tab_id}")
                return result_details
                
            # Start the tab with proper error handling
            try:
                logging.info(f"[_capture_debug] Attempting to start tab {actual_cdp_tab.id}")
                actual_cdp_tab.start()
                logging.info(f"[_capture_debug] Tab {actual_cdp_tab.id} started successfully.")
            except Exception as e_start:
                logging.error(f"[_capture_debug] Error starting tab: {e_start}")
                return result_details
            
            # Try to get readyState
            try:
                result = actual_cdp_tab.call_method("Runtime.evaluate", 
                                       expression="document.readyState",
                                       returnByValue=True,
                                       _timeout=3.0)
                if result and 'result' in result and 'value' in result['result']:
                    result_details["is_content_complete"] = (result['result']['value'] == 'complete')
                    logging.info(f"[_capture_debug] Document ready state: {result['result']['value']}")
            except Exception as e:
                logging.warning(f"[_capture_debug] Error getting ready state: {e}")
                
            # Capture MHTML first (preferred format)
            try:
                # IMPROVED: Use the direct method call with a reasonable timeout
                mhtml_result = actual_cdp_tab.call_method("Page.captureSnapshot", 
                                                         format="mhtml", 
                                                         _timeout=8.0)
                
                if mhtml_result and 'data' in mhtml_result:
                    result_details["mhtml_data"] = mhtml_result['data']
                    result_details["mhtml_size"] = len(mhtml_result['data'])
                    logging.info(f"[_capture_debug] MHTML capture successful: {result_details['mhtml_size']} bytes")
                else:
                    logging.warning("[_capture_debug] MHTML capture returned no data")
                    result_details["is_fallback"] = True
            except Exception as e:
                logging.warning(f"[_capture_debug] Error in MHTML capture: {e}")
                result_details["is_fallback"] = True
                
            # Try HTML fallback if MHTML failed
            if result_details["is_fallback"]:
                try:
                    html_result = actual_cdp_tab.call_method("Runtime.evaluate",
                                                           expression="document.documentElement.outerHTML",
                                                           returnByValue=True,
                                                           _timeout=5.0)
                    
                    if html_result and 'result' in html_result and 'value' in html_result['result']:
                        html_content = html_result['result']['value']
                        if html_content:
                            result_details["html_data"] = html_content
                            result_details["html_size"] = len(html_content.encode('utf-8', 'replace'))
                            logging.info(f"[_capture_debug] HTML fallback successful: {result_details['html_size']} bytes")
                        else:
                            logging.warning("[_capture_debug] HTML fallback returned empty string")
                    else:
                        logging.warning("[_capture_debug] HTML fallback evaluation failed")
                except Exception as e:
                    logging.warning(f"[_capture_debug] Error in HTML fallback: {e}")
                    
        except Exception as e:
            logging.error(f"[_capture_debug] General error in tab operations: {e}")
        finally:
            # Always stop the tab to clean up
            if actual_cdp_tab:
                try:
                    logging.info(f"[_capture_debug] Stopping tab {actual_cdp_tab.id}")
                    actual_cdp_tab.stop()
                    logging.info(f"[_capture_debug] Tab {actual_cdp_tab.id} stopped successfully")
                except Exception as e:
                    logging.debug(f"[_capture_debug] Error stopping tab: {e}")
                    
        return result_details

    def _perform_periodic_capture(self):
        """Periodically capture DOM to ensure we don't miss anything"""
        if not self._is_recording or self._is_paused or not self.is_chromium_focused:
            # Restart timer if recording is active
            if self._is_recording and not self._is_paused:
                try:
                    import threading
                    self.periodic_capture_timer = threading.Timer(PERIODIC_CAPTURE_INTERVAL, self._perform_periodic_capture)
                    self.periodic_capture_timer.daemon = True
                    self.periodic_capture_timer.start()
                except Exception as e:
                    logging.error(f"Failed to restart periodic capture timer: {e}")
            return
            
        # Only perform periodic capture if it's been a while since the last one
        current_time = time.perf_counter()
        if current_time - self.last_dom_capture_time >= PERIODIC_CAPTURE_INTERVAL:
            logging.info("Performing periodic DOM capture")
            
            # Get current URL if possible
            url = "unknown"
            title = "periodic"
            for port in range(9222, 9232):
                try:
                    response = requests.get(f"http://localhost:{port}/json/list", timeout=1)
                    if response.status_code == 200:
                        tabs = response.json()
                        for tab in tabs:
                            if tab.get('type') == 'page' and tab.get('url') and tab.get('active'):
                                url = tab.get('url')
                                title = tab.get('title', 'Unknown')
                                break
                        if url != "unknown":
                            break
                except:
                    continue
            
            # Capture DOM
            self._smart_dom_capture(url, title, "periodic")
        
        # Restart timer
        try:
            import threading
            self.periodic_capture_timer = threading.Timer(PERIODIC_CAPTURE_INTERVAL, self._perform_periodic_capture)
            self.periodic_capture_timer.daemon = True
            self.periodic_capture_timer.start()
        except Exception as e:
            logging.error(f"Failed to restart periodic capture timer: {e}")

    def _delayed_click_capture(self, x, y, button_name):
        """Perform a delayed capture after waiting for page to load"""
        try:
            if not self._is_recording or self._is_paused or not self.is_chromium_focused:
                return
            
            # Verify page is loaded now
            is_loaded = self._verify_page_is_loaded()
            if not is_loaded:
                logging.warning("Page still not fully loaded after delay")
                
                # Add one final attempt with longer delay for complex pages
                try:
                    import threading
                    
                    def final_click_capture():
                        try:
                            if not self._is_recording or self._is_paused or not self.is_chromium_focused:
                                return
                                
                            logging.info(f"Final attempt to capture DOM after click at ({x},{y})")
                            snapshot_mhtml = capture_chromium_dom_snapshot()
                            
                            if snapshot_mhtml and len(snapshot_mhtml) > 5000:
                                # Check for duplicate
                                content_hash = hashlib.md5(snapshot_mhtml.encode()[:50000]).hexdigest()
                                if content_hash in self.recent_dom_hashes:
                                    logging.info(f"Skipping duplicate final DOM snapshot (hash: {content_hash[:8]})")
                                    return
                                
                                # Add to recent hashes
                                self.recent_dom_hashes.append(content_hash)
                                # Maintain limited size
                                if len(self.recent_dom_hashes) > RECENT_DOM_HASH_CAPACITY:
                                    self.recent_dom_hashes.pop(0)
                                    
                                timestamp = time.perf_counter()
                                self.last_dom_capture_time = timestamp
                                filename = f"dom_click_final_{timestamp:.6f}.mhtml"
                                filepath = os.path.join(self.capture_data_path, filename)
                                
                                with open(filepath, 'w', encoding='utf-8') as f:
                                    f.write(snapshot_mhtml)
                                logging.info(f"Final DOM snapshot saved to: {filepath}")
                                
                                # Add an update event to the queue
                                update_event = {
                                    "time_stamp": timestamp,
                                    "action": "final_dom_capture",
                                    "dom_snapshot": filepath,
                                    "original_x": x,
                                    "original_y": y,
                                    "button": button_name
                                }
                                self.event_queue.put(update_event, block=False)
                        except Exception as e:
                            logging.error(f"Error in final click DOM capture: {e}")
                    
                    # Try one more time after another 2 seconds
                    final_thread = threading.Timer(2.0, final_click_capture)
                    final_thread.daemon = True
                    final_thread.start()
                except Exception as e:
                    logging.error(f"Failed to schedule final click capture: {e}")
            
            logging.info(f"Performing delayed DOM capture after click at ({x},{y})")
            snapshot_mhtml = capture_chromium_dom_snapshot()
            
            if snapshot_mhtml and len(snapshot_mhtml) > 5000:  # Increased minimum content requirement
                # Check if duplicate
                content_hash = hashlib.md5(snapshot_mhtml.encode()[:50000]).hexdigest()
                if content_hash in self.recent_dom_hashes:
                    logging.info(f"Skipping duplicate delayed DOM snapshot (hash: {content_hash[:8]})")
                    return
                
                # Add to recent hashes
                self.recent_dom_hashes.append(content_hash)
                # Maintain limited size
                if len(self.recent_dom_hashes) > RECENT_DOM_HASH_CAPACITY:
                    self.recent_dom_hashes.pop(0)
                
                timestamp = time.perf_counter()
                self.last_dom_capture_time = timestamp
                filename = f"dom_click_delayed_{timestamp:.6f}.mhtml"
                filepath = os.path.join(self.capture_data_path, filename)
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(snapshot_mhtml)
                logging.info(f"Delayed DOM snapshot after click saved to: {filepath}")
                
                # Add an update event to the queue
                update_event = {
                    "time_stamp": timestamp,
                    "action": "delayed_dom_capture",
                    "dom_snapshot": filepath,
                    "original_x": x,
                    "original_y": y,
                    "button": button_name,
                    "page_fully_loaded": is_loaded
                }
                self.event_queue.put(update_event, block=False)
        except Exception as e:
            logging.error(f"Error in delayed DOM capture: {e}")

    def _schedule_delayed_capture(self, x, y, button_name):
        """Schedule a delayed capture after a click"""
        try:
            import threading
            logging.info("Scheduling a delayed capture after click in case page is changing...")
            
            # Increased delay to 1.5 seconds (from 0.8) to allow more time for page to load
            delay_thread = threading.Timer(1.5, lambda: self._delayed_click_capture(x, y, button_name))
            delay_thread.daemon = True
            delay_thread.start()
        except Exception as e:
            logging.error(f"Error scheduling delayed capture: {e}")

    def _cleanup(self):
        logging.debug("Recorder cleanup started.")
        logging.debug("Stopping input listeners/monitors...")

        # Stop timers
        if self.url_check_timer:
            self.url_check_timer.cancel()
            self.url_check_timer = None
            
        if self.periodic_capture_timer:
            self.periodic_capture_timer.cancel()
            self.periodic_capture_timer = None

        # Stop AppKit monitors first if they exist
        if HAS_PYOBJC:
            if self.macos_key_monitor:
                try:
                    logging.info("Removing AppKit global key monitor.")
                    AppKit.NSEvent.removeMonitor_(self.macos_key_monitor)
                    self.macos_key_monitor = None
                except Exception as e:
                    logging.error(f"Error removing AppKit key monitor: {e}")
                    
            if self.macos_mouse_monitor:
                try:
                    logging.info("Removing AppKit global mouse monitor.")
                    AppKit.NSEvent.removeMonitor_(self.macos_mouse_monitor)
                    self.macos_mouse_monitor = None
                except Exception as e:
                    logging.error(f"Error removing AppKit mouse monitor: {e}")

        # Stop pynput listeners
        if hasattr(self, 'mouse_listener') and self.mouse_listener.is_alive():
            try:
                logging.info("Stopping mouse listener")
                self.mouse_listener.stop()
                self.mouse_listener.join(timeout=1.0)
                logging.info("Mouse listener stopped successfully")
            except Exception as e:
                logging.error(f"Error stopping mouse listener: {e}")
                
        if self.keyboard_listener and hasattr(self, 'keyboard_listener') and self.keyboard_listener.is_alive():
            try:
                logging.info("Stopping keyboard listener")
                self.keyboard_listener.stop()
                self.keyboard_listener.join(timeout=1.0)
                logging.info("Keyboard listener stopped successfully")
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
            # Set global shutdown flag to prevent new folder creation during cleanup
            global SHUTDOWN_IN_PROGRESS
            SHUTDOWN_IN_PROGRESS = True
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
        """Create a unique recording path with proper locking to prevent duplicates"""
        import os  # Ensure os is available in this method
        
        # Don't create new folders during shutdown
        global SHUTDOWN_IN_PROGRESS
        if SHUTDOWN_IN_PROGRESS:
            # Return the existing path if available, otherwise use a temp dir
            if hasattr(self, 'recording_path') and self.recording_path:
                return self.recording_path
            import tempfile
            return tempfile.mkdtemp(prefix="ducktrack_temp_")
        
        recordings_dir = get_recordings_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        base_path = os.path.join(recordings_dir, timestamp)
        
        # Use a lockfile to prevent race conditions between multiple instances
        lock_file = os.path.join(recordings_dir, ".folder_creation.lock")
        
        try:
            # Get an exclusive lock with a timeout
            with filelock.FileLock(lock_file, timeout=10):
                # Check if the exact path already exists
                if os.path.exists(base_path):
                    logging.warning(f"Recording path already exists: {base_path}")
                    
                    # Find a unique suffix by incrementing until we get a new one
                    suffix = 1
                    while True:
                        path = os.path.join(recordings_dir, f"{timestamp}_{suffix}")
                        if not os.path.exists(path):
                            break
                        suffix += 1
                else:
                    path = base_path
                
                # Create the folder
                try:
                    os.makedirs(path, exist_ok=False)  # Use exist_ok=False to detect race conditions
                    logging.info(f"Created recording path: {path}")
                except FileExistsError:
                    # If folder somehow exists despite our checks, create a truly unique one
                    path = os.path.join(recordings_dir, f"{timestamp}_{int(time.time())}")
                    os.makedirs(path, exist_ok=True)
                    logging.warning(f"Using alternative path due to concurrent creation: {path}")
                    
        except filelock.Timeout:
            logging.error("Timeout acquiring folder creation lock")
            # Fallback to a path with timestamp + pid which should be unique
            path = os.path.join(recordings_dir, f"{timestamp}_{os.getpid()}")
            os.makedirs(path, exist_ok=True)
            logging.warning(f"Using fallback path with PID: {path}")
        except Exception as e:
            logging.error(f"Error creating recording path: {e}")
            # Fallback to temp directory if needed
            import tempfile
            path = tempfile.mkdtemp(prefix="ducktrack_")
            logging.warning(f"Using fallback recording path in temp dir: {path}")
        
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

        try:
            # Use integer type codes
            event_type = int(event.type()) # Ensure integer type
            key_code = event.keyCode()
            modifierFlags = event.modifierFlags()

            # Determine action type for filename early (needed for capture decisions)
            action_type_for_file = "unknown_key_action"
            if event_type == AppKit.NSEventTypeKeyDown: 
                action_type_for_file = "keypress"
            elif event_type == AppKit.NSEventTypeKeyUp: 
                action_type_for_file = "keyrelease"
            elif event_type == AppKit.NSEventTypeFlagsChanged: 
                action_type_for_file = "flagschanged"
            else:
                return event  # Skip other event types

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
            
            # Determine if we should capture a11y tree (only for specific keys and respect throttling)
            accessibility_tree_path = None
            current_time = time.perf_counter()
            should_capture_a11y = False
            
            # Important keys that should always trigger captures regardless of timing
            important_keys = {'enter', 'return', 'tab', 'space', 'esc', 'escape'}
            
            # Capture a11y tree ONLY on key RELEASE events, not on press
            # This gives the UI time to update and avoids duplicates
            should_schedule_delayed_capture = False

            # For key release events (capturing after the action completes)
            if action == "release" and (
                final_name in important_keys or 
                (final_name in A11Y_CAPTURE_KEYS and 
                 current_time - self.last_a11y_capture_time >= self.a11y_capture_cooldown)):
                should_schedule_delayed_capture = True
                logging.info(f"Should schedule delayed capture for key release: {final_name}")
            # Also capture for modifier key changes if enough time has passed
            elif (action_type_for_file == "flagschanged" and 
                 current_time - self.last_a11y_capture_time >= self.a11y_capture_cooldown):
                should_capture_a11y = True  # Immediate capture for modifier changes
                logging.info(f"Should capture a11y tree for modifier change: {final_name}")
            
            # Schedule a delayed capture to give UI time to update
            if should_schedule_delayed_capture and self.capture_data_path:
                try:
                    import threading
                    
                    def delayed_key_capture(key_name):
                        try:
                            if not self._is_recording or self._is_paused:
                                return
                                
                            time.sleep(0.3)  # Small delay to let UI update
                            logging.info(f"Performing delayed a11y capture for key: {key_name}")
                            
                            tree = capture_macos_accessibility_tree()
                            if not tree:
                                logging.error(f"Failed to capture delayed a11y tree for key: {key_name}")
                                return
                                
                            # Check for duplicates
                            tree_str = json.dumps(tree)
                            tree_hash = hashlib.md5(tree_str.encode()).hexdigest()
                            
                            with self.a11y_capture_lock:
                                # Skip if this tree is very similar to the last one
                                if tree_hash == self.last_a11y_content_hash:
                                    logging.info(f"Skipping duplicate delayed a11y tree (hash: {tree_hash[:8]})")
                                    return
                                
                                # Add to recent hashes
                                self.last_a11y_content_hash = tree_hash
                                self.last_a11y_capture_time = time.perf_counter()
                                
                                filename = f"a11y_delayed_{key_name}_{self.last_a11y_capture_time:.6f}.json"
                                filepath = os.path.join(self.capture_data_path, filename)
                                
                                with open(filepath, 'w') as f:
                                    json.dump(tree, f, indent=2)
                                logging.info(f"Delayed a11y tree saved: {filepath}")
                                
                                # Create an event for the delayed capture
                                event = {
                                    "time_stamp": self.last_a11y_capture_time,
                                    "action": "delayed_a11y_capture",
                                    "key": key_name,
                                    "accessibility_tree": filepath
                                }
                                self.event_queue.put(event, block=False)
                                
                            # Also try to capture DOM if in a browser
                            if self.is_chromium_focused:
                                logging.info(f"Also capturing DOM for delayed key: {key_name}")
                                snapshot_mhtml = capture_chromium_dom_snapshot()
                                if snapshot_mhtml:
                                    # Check for duplicate
                                    content_hash = hashlib.md5(snapshot_mhtml.encode('utf-8', 'replace')[:10000]).hexdigest()
                                    
                                    if content_hash != self.last_dom_hash:
                                        dom_timestamp = time.perf_counter()
                                        self.last_dom_capture_time = dom_timestamp
                                        self.last_dom_hash = content_hash
                                        
                                        dom_filename = f"dom_delayed_{key_name}_{dom_timestamp:.6f}.mhtml"
                                        dom_filepath = os.path.join(self.capture_data_path, dom_filename)
                                        
                                        with open(dom_filepath, 'w', encoding='utf-8') as f:
                                            f.write(snapshot_mhtml)
                                        logging.info(f"Delayed DOM snapshot saved: {dom_filepath}")
                                        
                                        # Add an event for the delayed DOM capture
                                        dom_event = {
                                            "time_stamp": dom_timestamp,
                                            "action": "delayed_dom_capture",
                                            "key": key_name,
                                            "dom_snapshot": dom_filepath
                                        }
                                        self.event_queue.put(dom_event, block=False)
                                    else:
                                        logging.info(f"Skipping duplicate delayed DOM (hash: {content_hash[:8]})")
                        except Exception as e:
                            logging.error(f"Error in delayed key capture: {e}")
                    
                    # Start a separate thread for the delayed capture
                    thread = threading.Thread(target=delayed_key_capture, args=(final_name,))
                    thread.daemon = True
                    thread.start()
                except Exception as e:
                    logging.error(f"Failed to schedule delayed key capture: {e}")
            
            # Only capture a11y tree immediately if determined necessary
            if should_capture_a11y and self.capture_data_path:
                logging.info(f"Attempting to capture accessibility tree for {action_type_for_file} {final_name}")
                tree = capture_macos_accessibility_tree()
                if tree:
                    # Check for duplicate tree content
                    tree_str = json.dumps(tree)
                    tree_hash = hashlib.md5(tree_str.encode()).hexdigest()
                    
                    if tree_hash == self.last_a11y_content_hash:
                        logging.info(f"Skipping duplicate a11y tree for key {final_name} (hash: {tree_hash[:8]})")
                    else:
                        # Update tracking
                        self.last_a11y_content_hash = tree_hash
                        self.last_a11y_capture_time = current_time
                        
                        tree_timestamp = current_time
                        
                        filename = f"a11y_{action_type_for_file}_{tree_timestamp:.6f}.json"
                        filepath = os.path.join(self.capture_data_path, filename)
                        try:
                            with open(filepath, 'w') as f:
                                json.dump(tree, f, indent=2)
                            logging.info(f"Successfully saved accessibility tree: {filepath}")
                            accessibility_tree_path = filepath
                        except Exception as e:
                            logging.error(f"Error saving accessibility tree to {filepath} (macOS handler): {e}", exc_info=True)
                else:
                    logging.error(f"Failed to capture accessibility tree for {action_type_for_file} {final_name}")
            
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
                
                # Capture DOM snapshot if Chromium is focused and key is relevant
                dom_snapshot_path = None
                if self.is_chromium_focused and self.capture_data_path:
                    # Only capture DOM snapshots on RELEASE events to match our a11y approach
                    should_capture_dom = False
                    
                    # For important keys on key RELEASE only, not press
                    important_keys = {'enter', 'return', 'tab', 'space', 'esc', 'escape'}
                    
                    # Key RELEASE events only
                    if action == "release" and (
                        final_name in important_keys or 
                        (final_name in DOM_CAPTURE_KEYS and 
                         current_time - self.last_dom_capture_time >= MIN_DOM_CAPTURE_INTERVAL)):
                        should_capture_dom = True
                        logging.info(f"Should capture DOM for key release: {final_name}")
                    
                    # Modifier key changes 
                    elif (action_type_for_file == "flagschanged" and 
                          current_time - self.last_dom_capture_time >= MIN_DOM_CAPTURE_INTERVAL):
                        should_capture_dom = True
                        logging.info(f"Should capture DOM for modifier change: {final_name}")
                    
                    if should_capture_dom:
                        logging.info(f"Attempting DOM snapshot for {action_type_for_file} {final_name}")
                        
                        # Try multiple times for important key presses
                        max_attempts = 3 if final_name in important_keys else 1
                        snapshot_mhtml = None
                        
                        for attempt in range(max_attempts):
                            if attempt > 0:
                                logging.info(f"Retrying DOM capture, attempt {attempt+1}/{max_attempts}")
                                time.sleep(0.2)  # Brief delay between attempts
                                
                            snapshot_mhtml = capture_chromium_dom_snapshot()
                            if snapshot_mhtml:
                                break
                        
                        if snapshot_mhtml:
                            snap_timestamp = time.perf_counter()
                            self.last_dom_capture_time = snap_timestamp  # Update last capture time
                            
                            # Include key name in filename if applicable
                            key_suffix = f"_{final_name}" if final_name else ""
                            filename = f"dom_{action_type_for_file}{key_suffix}_{snap_timestamp:.6f}.mhtml"
                            filepath = os.path.join(self.capture_data_path, filename)
                            try:
                                with open(filepath, 'w', encoding='utf-8') as f:
                                    f.write(snapshot_mhtml)
                                key_event["dom_snapshot"] = filepath # Add path to existing event dict
                                logging.info(f"DOM snapshot saved to: {filepath}")
                            except Exception as e:
                                logging.error(f"Error saving DOM snapshot (macOS handler): {e}")
                        else:
                            logging.error(f"Failed to capture DOM snapshot for {action_type_for_file} {final_name}")
                
                # Add the event to the queue
                self.event_queue.put(key_event, block=False)

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

    def _add_dom_event(self, dom_file_path, url, title, is_mhtml, capture_type, x=None, y=None, button=None):
        """Helper method to add a DOM capture event to the event queue"""
        try:
            current_time = time.perf_counter()
            
            # Create event data based on capture type
            if capture_type.startswith("click_") and x is not None and y is not None:
                # Click-based DOM capture
                event_data = {
                    "time_stamp": current_time,
                    "action": "dom_capture",
                    "dom_snapshot": dom_file_path,
                    "is_mhtml": is_mhtml,
                    "x": x,
                    "y": y,
                    "button": button,
                    "capture_type": capture_type
                }
            elif capture_type.startswith("page_change"):
                # Page change DOM capture
                event_data = {
                    "time_stamp": current_time,
                    "action": "dom_capture",
                    "dom_snapshot": dom_file_path,
                    "is_mhtml": is_mhtml,
                    "url": url,
                    "title": title,
                    "capture_type": capture_type
                }
            else:
                # Generic DOM capture
                event_data = {
                    "time_stamp": current_time,
                    "action": "dom_capture",
                    "dom_snapshot": dom_file_path,
                    "is_mhtml": is_mhtml,
                    "capture_type": capture_type
                }
                
            # Add the event to the queue
            self.event_queue.put(event_data, block=False)
            logging.info(f"Added DOM event to queue: {capture_type}")
            
        except Exception as e:
            logging.error(f"Error adding DOM event: {e}")

    def _get_active_tab_url_title(self):
        """Get the URL and title of the active Chrome tab.
        Returns:
            Tuple[str, str]: (url, title) or None if not available
        """
        try:
            # Check if Chrome is active
            if not self.is_chromium_focused:
                return None
                
            # Find Chrome debugging port
            port = self._find_chrome_debugging_port()
            if not port:
                return None
                
            # Get list of tabs
            try:
                import requests
                tabs_response = requests.get(f"http://localhost:{port}/json/list", timeout=1)
                if tabs_response.status_code != 200:
                    return None
                    
                tabs = tabs_response.json()
                if not tabs:
                    return None
                    
                # Find active tab
                active_tab = None
                for tab in tabs:
                    if tab.get('type') == 'page' and tab.get('url'):
                        if tab.get('active'):
                            active_tab = tab
                            break
                        elif not active_tab:
                            active_tab = tab
                            
                if active_tab:
                    url = active_tab.get('url', '')
                    title = active_tab.get('title', 'Unknown')
                    return (url, title)
            except Exception as e:
                logging.debug(f"Error getting tab info: {e}")
                return None
        except Exception as e:
            logging.error(f"Error in _get_active_tab_url_title: {e}")
            return None

# --- Helper function for CDP DOM Snapshot ---
def capture_chromium_dom_snapshot(port=9222):
    """Connects to Chrome via CDP and captures DOM snapshot of the active tab."""
    try:
        logging.debug(f"Attempting to connect to Chromium on port {port}...")
        
        # First, check if Chrome is available with the debugging port
        try:
            import requests
            # Import pychrome and websocket here to ensure they're accessible
            import pychrome
            import websocket
            
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
                
            # Find a real tab that's not blank/empty
            active_tab = None
            for tab in tabs:
                if tab.get('type') == 'page' and tab.get('url'):
                    url = tab.get('url')
                    # Skip browser internal pages and empty tabs
                    if not (url.startswith('chrome:') or
                            url.startswith('edge:') or
                            url.startswith('brave:') or
                            url == 'about:blank' or
                            "newtab" in url.lower()):
                        if tab.get('active'):
                            active_tab = tab
                            break
                        elif not active_tab:
                            active_tab = tab
            
            # Fallback to the first tab as last resort
            if not active_tab and tabs:
                active_tab = tabs[0]
                
            if not active_tab:
                logging.warning("Could not find an active tab")
                return None
                
            logging.debug(f"Found active tab: {active_tab.get('title')} - {active_tab.get('url')}")
            
            # Check if tab is likely still loading or empty
            tab_url = active_tab.get('url', '')
            tab_title = active_tab.get('title', '')
            
            if (tab_url == 'about:blank' or 
                'newtab' in tab_url or
                tab_title == 'New Tab' or 
                tab_title == 'Loading...' or 
                not tab_title):
                logging.info(f"Skipping likely blank/loading tab: {tab_title} ({tab_url})")
                return None
                
            # Now use pychrome to connect to this tab
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
                    # Check if response is too small (likely blank page)
                    content = snapshot_data.get('data', '')
                    if len(content) < 1000:
                        logging.warning(f"DOM capture too small ({len(content)} bytes), likely blank page")
                        return None
                        
                    logging.debug(f"Captured DOM snapshot: {len(content)} bytes")
                    return content
                else:
                    logging.warning("CDP: captureSnapshot returned empty or invalid data")
                    return None
            finally:
                target_tab.stop()
                
        except requests.exceptions.ConnectionError as e:
            logging.warning(f"Connection error to Chrome debugging port: {e}")
            return None
        except pychrome.exceptions.TimeoutException as e:
            logging.warning(f"CDP timeout exception: {e}")
            return None
        except websocket.WebSocketException as e:
            logging.warning(f"WebSocket exception: {e}")
            return None
        except Exception as e:
            logging.warning(f"Other CDP connection/capture error: {e}")
            return None
            
    except Exception as e:
        logging.error(f"Unexpected error during CDP capture: {e}", exc_info=True)
        return None

def _try_http_capture(port):
    """Try to capture DOM content using direct HTTP requests to the DevTools protocol"""
    try:
        import requests
        
        # Get list of tabs
        tabs_response = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=2)
        if tabs_response.status_code != 200:
            logging.warning(f"Could not get tab list: Status {tabs_response.status_code}")
            return _create_minimal_placeholder("HTTP tabs request failed", "chrome://no-tabs-http")
            
        tabs = tabs_response.json()
        if not tabs:
            logging.warning("No tabs in HTTP response")
            return _create_minimal_placeholder("No tabs found via HTTP", "chrome://no-tabs-http")
            
        # Find a suitable active tab
        active_tab = None
        for tab in tabs:
            tab_url = tab.get('url', '')
            if tab.get('type') == 'page' and not tab_url.startswith('chrome'):
                # Prefer an actual web page (not Chrome internal)
                if tab.get('webSocketDebuggerUrl'):
                    active_tab = tab
                    logging.info(f"Found suitable tab: {tab_url}")
                    break
                    
        if not active_tab:
            # Fallback to any first tab
            active_tab = tabs[0]
            logging.info(f"Falling back to first tab: {active_tab.get('url')}")
            
        # Extract tab info
        tab_id = active_tab.get('id')
        tab_url = active_tab.get('url', 'unknown')
        websocket_url = active_tab.get('webSocketDebuggerUrl', '')
        dev_frontend_url = active_tab.get('devtoolsFrontendUrl', '')
        
        logging.info(f"Attempting to capture DOM for tab: {tab_url}")
        
        # We'll try multiple endpoint patterns since Chrome's API can vary
        endpoints = [
            f"http://127.0.0.1:{port}/json/session/{tab_id}/execute",
            f"http://localhost:{port}/json/session/{tab_id}/execute",
            f"http://127.0.0.1:{port}/devtools/page/{tab_id}/execute",
            f"http://localhost:{port}/devtools/page/{tab_id}/execute",
            f"http://127.0.0.1:{port}/json/execute/{tab_id}",
            f"http://localhost:{port}/json/execute/{tab_id}"
        ]
        
        # HTML command to get the document HTML
        html_cmd = {
            "id": 1, 
            "method": "Runtime.evaluate", 
            "params": {
                "expression": "document.documentElement.outerHTML", 
                "returnByValue": True
            }
        }
        
        # Try each endpoint
        for endpoint in endpoints:
            try:
                logging.info(f"Trying endpoint: {endpoint}")
                response = requests.post(endpoint, json=html_cmd, timeout=2)
                if response.status_code == 200:
                    result = response.json()
                    html_content = result.get('result', {}).get('result', {}).get('value', '')
                    
                    if html_content and len(html_content) > 500:
                        logging.info(f"Successfully captured DOM content via HTTP ({len(html_content)} bytes) using {endpoint}")
                        # Get title for the HTML
                        title_cmd = {"id": 2, "method": "Runtime.evaluate", "params": {"expression": "document.title", "returnByValue": True}}
                        title_response = requests.post(endpoint, json=title_cmd, timeout=1)
                        title = "Untitled Page"
                        if title_response.status_code == 200:
                            title_result = title_response.json()
                            title = title_result.get('result', {}).get('result', {}).get('value', 'Untitled Page')
                        
                        return f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <meta charset="utf-8">
    <meta name="url" content="{tab_url}">
</head>
<body>
{html_content}
</body>
</html>"""
            except Exception as e:
                logging.warning(f"Endpoint {endpoint} failed: {str(e)}")
                continue
        
        # Last attempt - try the Page.captureSnapshot method
        snapshot_url = f"http://127.0.0.1:{port}/json/protocol/Page.captureSnapshot"
        try:
            response = requests.post(snapshot_url, json={"method": "Page.captureSnapshot"}, timeout=3)
            if response.status_code == 200:
                snapshot_data = response.json()
                if snapshot_data.get('result', {}).get('data'):
                    logging.info("Successfully captured Page.captureSnapshot via HTTP")
                    return snapshot_data['result']['data']
        except Exception as e:
            logging.warning(f"Page.captureSnapshot failed: {str(e)}")
            
        # All attempts failed - create a placeholder
        logging.warning(f"All HTTP capture attempts failed for {tab_url}")
        return _create_minimal_placeholder(f"HTTP capture failed for {tab_url}", tab_url)
    except Exception as e:
        logging.error(f"HTTP capture failed: {str(e)}")
        return _create_minimal_placeholder(str(e), "error://http-capture-failed")

def _create_minimal_placeholder(reason, url):
    """Create a minimal HTML placeholder when capture fails"""
    logging.warning(f"Created minimal placeholder for {url}")
    return f"""<!DOCTYPE html>
<html>
<head>
    <title>DuckTrack DOM Capture Placeholder</title>
    <meta charset="utf-8">
    <meta name="url" content="{url}">
    <meta name="capture-error" content="{reason}">
</head>
<body>
    <h1>DOM Capture Failed</h1>
    <p>URL: {url}</p>
    <p>Reason: {reason}</p>
    <p>Time: {datetime.now().isoformat()}</p>
</body>
</html>"""

def _is_port_available(port):
    """Check if a browser debugging port is available and responding"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(('127.0.0.1', port)) == 0:
                try:
                    import requests
                    # Try 127.0.0.1 first
                    response = requests.get(f"http://127.0.0.1:{port}/json/version", timeout=0.5)
                    if response.status_code == 200:
                        browser_info = response.json()
                        logging.info(f"Found browser debugging port: {port} ({browser_info.get('Browser')})")
                        return True
                except Exception:
                    # Try with localhost as fallback
                    try:
                        response = requests.get(f"http://localhost:{port}/json/version", timeout=0.5)
                        if response.status_code == 200:
                            return True
                    except Exception:
                        pass
        return False
    except Exception:
        return False