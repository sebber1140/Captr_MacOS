#!/usr/bin/env python3
"""
Debug tool to check recording folders and dom_snaps content.
"""

import os
import sys
import glob
import json
import time
from datetime import datetime
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_recordings_dir():
    """Get the recordings directory"""
    if sys.platform == 'darwin':  # macOS
        home_dir = os.path.expanduser('~')
        documents_dir = os.path.join(home_dir, 'Documents')
        recordings_dir = os.path.join(documents_dir, 'Captr_Recordings')
    else:
        # Should match what's in util.py for other platforms
        home_dir = os.path.expanduser('~')
        recordings_dir = os.path.join(home_dir, 'Captr_Recordings')
    
    if not os.path.exists(recordings_dir):
        logging.error(f"Recordings directory not found at {recordings_dir}")
        return None
    
    return recordings_dir

def find_latest_recording(recordings_dir):
    """Find the most recent recording folder"""
    if not recordings_dir or not os.path.exists(recordings_dir):
        return None
    
    recording_folders = glob.glob(os.path.join(recordings_dir, "*-*-*_*-*-*"))
    if not recording_folders:
        logging.error("No recording folders found")
        return None
    
    # Sort by creation time, newest first
    recording_folders.sort(key=os.path.getctime, reverse=True)
    
    return recording_folders[0]

def check_dom_snaps_folder(recording_path):
    """Check for the dom_snaps folder and its contents"""
    dom_snaps_path = os.path.join(recording_path, "dom_snaps")
    
    if not os.path.exists(dom_snaps_path):
        logging.error(f"dom_snaps folder not found at {dom_snaps_path}")
        
        # Check for alternative location
        home_dir = os.path.expanduser('~')
        alt_path = os.path.join(home_dir, 'Captr_dom_snaps')
        if os.path.exists(alt_path):
            logging.info(f"Found alternative dom_snaps folder at {alt_path}")
            dom_snaps_path = alt_path
        else:
            logging.info("Alternative dom_snaps folder not found either")
            return None
    
    # Check contents
    files = os.listdir(dom_snaps_path)
    if not files:
        logging.warning(f"dom_snaps folder exists but is empty: {dom_snaps_path}")
        return dom_snaps_path
    
    # Count types of files
    json_files = len([f for f in files if f.endswith('.json')])
    mhtml_files = len([f for f in files if f.endswith('.mhtml')])
    
    logging.info(f"dom_snaps folder contains: {json_files} accessibility tree files (.json) and {mhtml_files} DOM snapshot files (.mhtml)")
    
    return dom_snaps_path

def check_events_file(recording_path):
    """Check the events.jsonl file for DOM/accessibility references"""
    events_file = os.path.join(recording_path, "events.jsonl")
    
    if not os.path.exists(events_file):
        logging.error(f"events.jsonl file not found at {events_file}")
        return
    
    # Check if any dom_snapshot or accessibility_tree fields are set
    dom_refs = 0
    a11y_refs = 0
    events_with_chrome = 0
    
    with open(events_file, 'r') as f:
        for line in f:
            try:
                event = json.loads(line)
                if event.get("dom_snapshot"):
                    dom_refs += 1
                if event.get("accessibility_tree"):
                    a11y_refs += 1
                if event.get("app_name") in ["Google Chrome", "Microsoft Edge", "Brave Browser"]:
                    events_with_chrome += 1
            except json.JSONDecodeError:
                continue
    
    logging.info(f"Found {dom_refs} events with DOM snapshot references and {a11y_refs} with accessibility tree references")
    logging.info(f"Found {events_with_chrome} events associated with Chromium browsers")
    
    if dom_refs == 0 and a11y_refs == 0:
        logging.warning("No DOM or accessibility captures referenced in events file")
        
        # Check for window_focus events to see if focused app detection works
        window_focus_events = 0
        with open(events_file, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line)
                    if event.get("action") == "window_focus":
                        window_focus_events += 1
                except json.JSONDecodeError:
                    continue
        
        logging.info(f"Found {window_focus_events} window_focus events")
        if window_focus_events == 0:
            logging.warning("No window_focus events found - app focus detection may not be working")

def check_permissions():
    """Check relevant permissions on macOS"""
    if sys.platform != 'darwin':
        logging.info("Permission check only available on macOS")
        return
    
    try:
        import AppKit
        import ApplicationServices
        
        # Check Accessibility permissions
        trusted = ApplicationServices.AXIsProcessTrustedWithOptions(None)
        if trusted:
            logging.info("Application has Accessibility permissions")
        else:
            logging.error("Application does NOT have Accessibility permissions!")
            logging.error("Enable in System Preferences > Security & Privacy > Privacy > Accessibility")
    except Exception as e:
        logging.error(f"Error checking permissions: {e}")

def check_chrome_debug_port():
    """Check if Chrome's debug port is responding"""
    try:
        import requests
        try:
            response = requests.get("http://localhost:9222/json/version", timeout=2)
            if response.status_code == 200:
                data = response.json()
                logging.info(f"Chrome debugging port available: {data.get('Browser')}")
                return True
            else:
                logging.error(f"Chrome debug port returned status {response.status_code}")
                return False
        except requests.exceptions.ConnectionError:
            logging.error("Could not connect to Chrome debugging port")
            logging.error("Make sure Chrome is running with --remote-debugging-port=9222")
            return False
    except ImportError:
        logging.error("Could not import requests library")
        return False

def main():
    """Main function"""
    logging.info("Captr Recording Debug Tool")
    
    # Check recordings directory
    recordings_dir = get_recordings_dir()
    if not recordings_dir:
        print("No recordings directory found. Please create a recording first.")
        return
    
    # Find latest recording
    latest_recording = find_latest_recording(recordings_dir)
    if not latest_recording:
        print("No recording folders found. Please create a recording first.")
        return
    
    recording_name = os.path.basename(latest_recording)
    
    logging.info(f"Latest recording: {recording_name}")
    
    # Check DOM snaps folder
    dom_snaps_path = check_dom_snaps_folder(latest_recording)
    
    # Check events file
    check_events_file(latest_recording)
    
    # Check permissions
    check_permissions()
    
    # Check Chrome debug port
    check_chrome_debug_port()
    
    # Print summary
    print("\n=== Captr Debug Summary ===")
    print(f"Latest recording: {recording_name}")
    print(f"Recording path: {latest_recording}")
    
    if dom_snaps_path:
        print(f"dom_snaps path: {dom_snaps_path}")
        print(f"dom_snaps exists: {os.path.exists(dom_snaps_path)}")
        if os.path.exists(dom_snaps_path):
            file_count = len(os.listdir(dom_snaps_path))
            print(f"dom_snaps file count: {file_count}")
    else:
        print("dom_snaps folder not found")

    # Recommendations
    print("\n=== Recommendations ===")
    print("1. Run Chrome with debugging enabled (if not already):")
    print("   open -a \"Google Chrome\" --args --remote-debugging-port=9222")
    print()
    print("2. Check app logs by running Captr from terminal:")
    print("   open dist/Captr.app --stdout-path=/tmp/captr.log --stderr-path=/tmp/captr_err.log")
    print("   Then check logs with: cat /tmp/ducktrack.log")
    print()
    print("3. Make sure Captr has Accessibility permissions in")
    print("   System Preferences > Security & Privacy > Privacy > Accessibility")
    print()
    print("4. Run the debug scripts:")
    print("   python3 debug_chrome_cdp.py")
    print("   python3 debug_accessibility.py")

if __name__ == "__main__":
    main() 