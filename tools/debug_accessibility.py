#!/usr/bin/env python3
"""
Debug tool to test macOS Accessibility API functionality.
This script will attempt to capture the accessibility tree of the current frontmost application.
"""

import sys
import os
import json
import logging
import time

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

try:
    # Import macOS-specific modules
    import objc
    import AppKit
    import Foundation
    import Quartz
    import ApplicationServices
    
    HAS_PYOBJC = True
    logging.info("Successfully imported PyObjC frameworks")
    logging.info(f"Python version: {sys.version}")
    logging.info(f"objc version: {objc.__version__ if hasattr(objc, '__version__') else 'unknown'}")
except ImportError as e:
    HAS_PYOBJC = False
    logging.error(f"Failed to import PyObjC frameworks: {e}")
    sys.exit(1)

# --- Accessibility API Test Functions ---

def check_accessibility_permissions():
    """
    Check if the application has accessibility permissions
    """
    try:
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(None)
        if trusted:
            logging.info("Application has Accessibility permissions")
        else:
            logging.warning("Application does NOT have Accessibility permissions!")
            logging.warning("Please enable accessibility permissions in System Preferences > Security & Privacy > Privacy > Accessibility")
        return trusted
    except Exception as e:
        logging.error(f"Error checking accessibility permissions: {e}")
        return False

def sanitize_for_json(obj):
    """Recursively convert PyObjC types in a dict/list for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item) for item in obj]
    # Add specific type conversions here as needed
    elif isinstance(obj, objc.pyobjc_unicode):
        return str(obj)
    elif isinstance(obj, Foundation.NSDate):
        return str(obj) # Or format as ISO string etc.
    elif isinstance(obj, (AppKit.NSNumber, objc.pyobjc_object)):
        # Handle generic pyobjc_object - attempt string representation
        try:
            if hasattr(obj, 'boolValue'):
                pass # Fall through to str() for now
            elif hasattr(obj, 'floatValue'):
                return float(obj)
            elif hasattr(obj, 'intValue'):
                return int(obj)
        except:
            pass # Ignore conversion errors, fall back to str
        return str(obj) # Fallback
    return obj # Return basic types (int, float, str, bool, None) and unknowns as is

def decode_axvalue(value):
    """Decodes AXValueRef types into Python types."""
    try:
        value_type = ApplicationServices.AXValueGetType(value)
        
        if value_type == ApplicationServices.kAXValueCGPointType:
            point = Quartz.CGPoint()
            ApplicationServices.AXValueGetValue(value, ApplicationServices.kAXValueCGPointType, objc.byref(point))
            return {'x': point.x, 'y': point.y}
        elif value_type == ApplicationServices.kAXValueCGSizeType:
            size = Quartz.CGSize()
            ApplicationServices.AXValueGetValue(value, ApplicationServices.kAXValueCGSizeType, objc.byref(size))
            return {'width': size.width, 'height': size.height}
        elif value_type == ApplicationServices.kAXValueCGRectType:
            rect = Quartz.CGRect()
            ApplicationServices.AXValueGetValue(value, ApplicationServices.kAXValueCGRectType, objc.byref(rect))
            return {'x': rect.origin.x, 'y': rect.origin.y, 'width': rect.size.width, 'height': rect.size.height}
        elif value_type == ApplicationServices.kAXValueCFRangeType:
            range_val = Quartz.CFRange()
            ApplicationServices.AXValueGetValue(value, ApplicationServices.kAXValueCFRangeType, objc.byref(range_val))
            return {'location': range_val.location, 'length': range_val.length}
        
        return f"<AXValue type {value_type}>" # Fallback for unknown types
    except Exception as e:
        logging.error(f"Error decoding AXValue: {e}")
        return f"<AXValue decode error: {e}>"

def get_element_info(element, max_depth=3, current_depth=0):
    """Recursively get information about an AXUIElement and its children (with depth limit)."""
    if current_depth > max_depth:
        return {"max_depth_reached": True}
    
    info = {}
    attributes = [
        ApplicationServices.kAXRoleAttribute, 
        ApplicationServices.kAXSubroleAttribute, 
        ApplicationServices.kAXTitleAttribute,
        ApplicationServices.kAXIdentifierAttribute, 
        ApplicationServices.kAXValueAttribute,
        ApplicationServices.kAXPositionAttribute,
        ApplicationServices.kAXSizeAttribute
    ]
    
    # Add attributes that help identify the element
    for attr in attributes:
        try:
            result, value = ApplicationServices.AXUIElementCopyAttributeValue(element, attr, None)
            attr_name = str(attr).replace('kAX', '').replace('Attribute', '')
            
            if result == 0 and value is not None:  # kAXErrorSuccess is 0
                if attr == ApplicationServices.kAXPositionAttribute or attr == ApplicationServices.kAXSizeAttribute:
                    info[attr_name] = decode_axvalue(value)
                else:
                    info[attr_name] = str(value)
        except Exception as e:
            logging.debug(f"Error getting attribute {attr}: {e}")
    
    # Get a limited number of children for debugging purposes
    try:
        result_children, children = ApplicationServices.AXUIElementCopyAttributeValue(
            element, ApplicationServices.kAXChildrenAttribute, None
        )
        if result_children == 0 and children:  # kAXErrorSuccess is 0
            num_children = len(children)
            if num_children > 0:
                info['NumChildren'] = num_children
                
                # Only process first few children for brevity
                sample_size = min(num_children, 3)
                info['Children'] = []
                
                for i in range(sample_size):
                    try:
                        child_info = get_element_info(children[i], max_depth, current_depth + 1)
                        if child_info:
                            info['Children'].append(child_info)
                    except Exception as child_e:
                        logging.debug(f"Error processing child {i}: {child_e}")
                
                if sample_size < num_children:
                    info['MoreChildren'] = num_children - sample_size
    except Exception as e:
        logging.debug(f"Error getting children: {e}")

    return info

def capture_accessibility_tree():
    """Captures the accessibility tree of the focused application window."""
    if not check_accessibility_permissions():
        return None
        
    try:
        logging.info("Attempting to capture accessibility tree...")
        workspace = AppKit.NSWorkspace.sharedWorkspace()
        active_app = workspace.frontmostApplication()
        
        if not active_app:
            logging.warning("No active application found")
            return None
            
        app_name = active_app.localizedName()
        bundle_id = active_app.bundleIdentifier()
        pid = active_app.processIdentifier()
        
        logging.info(f"Active app: {app_name} (Bundle ID: {bundle_id}, PID: {pid})")
        
        # Create an accessibility element for the application
        app_element = ApplicationServices.AXUIElementCreateApplication(pid)
        if not app_element:
            logging.warning(f"Failed to create AXUIElement for app {app_name}")
            return None
            
        # Get the focused window
        logging.info("Attempting to get focused window...")
        result, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(
            app_element, ApplicationServices.kAXFocusedWindowAttribute, None
        )
        
        if result != 0 or not focused_window:
            logging.warning(f"Could not get focused window (result={result}), trying to get any window")
            # Try getting any window
            result_windows, windows = ApplicationServices.AXUIElementCopyAttributeValue(
                app_element, ApplicationServices.kAXWindowsAttribute, None
            )
            
            if result_windows == 0 and windows and len(windows) > 0:
                focused_window = windows[0]
                logging.info("Using first window from list as fallback")
            else:
                logging.warning(f"Could not get any window for app {app_name}")
                return None
                
        # Get basic information about the window
        result, window_title = ApplicationServices.AXUIElementCopyAttributeValue(
            focused_window, ApplicationServices.kAXTitleAttribute, None
        )
        
        if result == 0 and window_title:
            logging.info(f"Window title: {window_title}")
        else:
            logging.info("Window title not available")
            
        # Build the accessibility tree
        logging.info("Building accessibility tree...")
        start_time = time.time()
        tree = get_element_info(focused_window)
        logging.info(f"Tree built in {time.time() - start_time:.2f} seconds")
        
        if not tree:
            logging.warning("Generated empty accessibility tree")
            return None
            
        # Sanitize the tree for JSON serialization
        sanitized_tree = sanitize_for_json(tree)
        
        # Save to file
        output_file = "accessibility_tree_debug.json"
        with open(output_file, "w") as f:
            json.dump(sanitized_tree, f, indent=2)
        logging.info(f"Accessibility tree saved to {output_file}")
        
        return sanitized_tree
    
    except Exception as e:
        logging.error(f"Error capturing accessibility tree: {e}", exc_info=True)
        return None

def main():
    """Main function"""
    logging.info("macOS Accessibility API Debug Tool")
    
    if sys.platform != 'darwin':
        logging.error("This tool only works on macOS")
        return
        
    if not HAS_PYOBJC:
        logging.error("PyObjC frameworks are required but not available")
        return
        
    # Test accessibility
    tree = capture_accessibility_tree()
    
    if tree:
        logging.info("Accessibility tree capture successful!")
    else:
        logging.error("Accessibility tree capture failed")
        
if __name__ == "__main__":
    main() 