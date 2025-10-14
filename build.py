import shutil
import sys
from pathlib import Path
from platform import system
from subprocess import CalledProcessError, run, PIPE
import time # Import time for sleep
import os # Import os for path operations

project_dir = Path(".")
assets_dir = project_dir / "assets"
main_py = project_dir / "main.py"
spec_file = project_dir / "Captr.spec"
# Use .png for icon, PyInstaller handles conversion if needed for Windows
icon_file = assets_dir / "captr.png"
app_name = "Captr"
# Virtual environment path
venv_path = project_dir / "venv"
venv_bin = venv_path / "bin"

def ensure_venv_activated():
    """Ensure we're running in the virtual environment"""
    if not os.environ.get("VIRTUAL_ENV") or not os.environ.get("VIRTUAL_ENV").endswith("venv"):
        print("Activating virtual environment...")
        # We can't actually activate the venv from Python, but we can use the venv's Python
        venv_python = venv_bin / "python3"
        if venv_python.exists():
            # Re-execute this script using the venv's Python
            cmd = [str(venv_python), __file__]
            print(f"Re-executing with {venv_python}: {' '.join(cmd)}")
            os.execv(str(venv_python), cmd)
        else:
            print(f"Error: Virtual environment Python not found at {venv_python}")
            sys.exit(1)
    else:
        print(f"Using virtual environment: {os.environ.get('VIRTUAL_ENV')}")

def test_pyobjc_imports():
    """Test PyObjC imports to verify they work correctly."""
    print("\nTesting PyObjC imports...")
    test_script = """
import sys
try:
    import objc
    from Quartz import CoreGraphics
    import AppKit
    import Foundation
    import ApplicationServices
    
    # Try to access the problematic constants
    print(f"kAXValueCGPointType = {CoreGraphics.kAXValueCGPointType}")
    print(f"All PyObjC imports succeeded!")
    sys.exit(0)
except Exception as e:
    print(f"PyObjC import test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
"""
    with open("test_pyobjc.py", "w") as f:
        f.write(test_script)
    
    try:
        result = run([sys.executable, "test_pyobjc.py"], 
                    check=True, capture_output=True, text=True)
        print("PyObjC import test succeeded:")
        print(result.stdout)
        return True
    except CalledProcessError as e:
        print("PyObjC import test FAILED:")
        print(e.stdout)
        print(e.stderr)
        return False
    finally:
        if Path("test_pyobjc.py").exists():
            Path("test_pyobjc.py").unlink()

def create_dmg(dist_path: Path, app_name: str):
    """Creates a DMG file for the macOS application bundle."""
    print("\nCreating DMG...")
    app_bundle = dist_path / f"{app_name}.app"
    dmg_path = dist_path / f"{app_name}.dmg"
    temp_mount_dir = Path(f"/Volumes/{app_name}")

    if not app_bundle.exists():
        print(f"Error: Application bundle not found at {app_bundle}")
        return False

    # Remove existing DMG if it exists
    if dmg_path.exists():
        print(f"Removing existing DMG: {dmg_path}")
        dmg_path.unlink()

    # Estimate size (add some buffer)
    try:
        app_size_bytes = sum(f.stat().st_size for f in app_bundle.glob('**/*') if f.is_file())
        dmg_size_mb = int(app_size_bytes / (1024 * 1024) * 1.2) + 50 # 20% buffer + 50MB
        print(f"Estimated app size: {app_size_bytes / (1024*1024):.2f} MB, DMG size: {dmg_size_mb} MB")
    except Exception as e:
        print(f"Warning: Could not accurately estimate app size: {e}. Using default size.")
        dmg_size_mb = 500 # Default size if estimation fails

    # Create a temporary writable DMG
    create_cmd = [
        "hdiutil", "create",
        "-ov",
        "-volname", app_name,
        "-fs", "HFS+",
        "-srcfolder", str(app_bundle),
        "-size", f"{dmg_size_mb}m", # Specify size
        str(dmg_path)
    ]
    print(f"Running: {' '.join(create_cmd)}")
    try:
        run(create_cmd, check=True, capture_output=True)
        print("DMG created successfully.")
        return True
    except CalledProcessError as e:
        print(f"Error creating DMG: {e}")
        print(f"hdiutil stdout: {e.stdout.decode()}")
        print(f"hdiutil stderr: {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("Error: 'hdiutil' command not found. This script must be run on macOS.")
        return False

for dir_to_remove in ["dist", "build"]:
    dir_path = project_dir / dir_to_remove
    if dir_path.exists():
        shutil.rmtree(dir_path)

# Make sure we're running in the virtual environment
ensure_venv_activated()

# Test PyObjC imports first on macOS
if system() == "Darwin":
    if not test_pyobjc_imports():
        print("PyObjC import test failed. Fix import issues before building.")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            sys.exit(1)

# First, check if pyinstaller is available
try:
    # Try importing PyInstaller to verify it's installed
    import PyInstaller
    print(f"PyInstaller version {PyInstaller.__version__} found.")
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]
except ImportError:
    print("PyInstaller not found in current environment. Trying python -m PyInstaller instead.")
    pyinstaller_cmd = [sys.executable, "-m", "PyInstaller"]

# Add the spec file
pyinstaller_cmd.append(str(spec_file))

print(f"Running PyInstaller command: {' '.join(pyinstaller_cmd)}")

try:
    # Run with detailed output for debugging
    process = run(pyinstaller_cmd, check=True, stdout=PIPE, stderr=PIPE, text=True)
    print("PyInstaller stdout:")
    print(process.stdout)
    
    if process.stderr:
        print("PyInstaller stderr (warnings/info):")
        print(process.stderr)
    
    print("Build successful! Application bundle created in 'dist' directory.")

    # Create DMG only on macOS
    if system() == "Darwin":
        dist_path = project_dir / "dist"
        if not create_dmg(dist_path, app_name):
            print("DMG creation failed.")
            sys.exit(1)
        else:
            print(f"DMG file created at: {dist_path / f'{app_name}.dmg'}")

except CalledProcessError as e:
    print(f"An error occurred while running PyInstaller:")
    print(f"Command exit code: {e.returncode}")
    print(f"stdout: {e.stdout}")
    print(f"stderr: {e.stderr}")
    sys.exit(1)
except FileNotFoundError:
    print("Error: Could not run PyInstaller. Make sure it's installed in your environment.")
    print("Try running: pip install pyinstaller")
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error during build: {e}")
    sys.exit(1)