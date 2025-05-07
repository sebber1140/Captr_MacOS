"""
Browser launcher dialog for DuckTrack

This module provides a dialog for launching browsers with debugging enabled.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                             QPushButton, QHBoxLayout, QRadioButton,
                             QButtonGroup, QMessageBox, QCheckBox,
                             QGridLayout, QGroupBox, QTextEdit)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QPalette, QColor
import os
from platform import system
from PyQt6.QtWidgets import QApplication

from .browser_launcher import (find_installed_browsers, launch_browser,
                             get_default_browser, DEFAULT_DEBUG_PORT,
                             find_running_debuggable_browsers, connect_to_running_browser)

class BrowserLauncherDialog(QDialog):
    """Dialog for launching browsers with debugging enabled"""
    
    browser_launched = pyqtSignal(str, int, bool)  # browser_key, port, success
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Launch Browser")
        self.resize(500, 400)  # Increase dialog size for better button display
        
        # Store running browsers with their ports
        self.running_browsers = {}
        
        self.create_ui()
        self.populate_browsers()
        
        # Make sure initial button states are correct
        self.update_launch_button_state()
    
    def create_ui(self):
        """Create the dialog UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)  # Increase spacing between elements
        main_layout.setContentsMargins(12, 12, 12, 12)  # Add some margin
        
        # Description
        description = QLabel(
            "Launch a browser with debugging enabled to capture DOM snapshots. "
            "This will create a new browser window with a clean profile."
        )
        description.setWordWrap(True)
        main_layout.addWidget(description)
        
        # Browser selection modes
        browser_mode_group = QGroupBox("Browser Mode")
        browser_mode_layout = QVBoxLayout()
        browser_mode_layout.setSpacing(8)  # Increase spacing
        
        self.launch_new_radio = QRadioButton("Launch new browser instance")
        self.launch_new_radio.setChecked(True)
        self.launch_new_radio.toggled.connect(self.toggle_browser_mode)
        browser_mode_layout.addWidget(self.launch_new_radio)
        
        self.connect_existing_radio = QRadioButton("Connect to running browser")
        self.connect_existing_radio.toggled.connect(self.toggle_browser_mode)
        browser_mode_layout.addWidget(self.connect_existing_radio)
        
        browser_mode_group.setLayout(browser_mode_layout)
        main_layout.addWidget(browser_mode_group)
        
        # Browser selection
        self.launch_new_group = QGroupBox("Select Browser to Launch")
        browser_layout = QVBoxLayout()
        browser_layout.setSpacing(10)  # Increase spacing
        
        self.browser_combo = QComboBox()
        self.browser_combo.setMinimumHeight(30)  # Make combo box taller
        browser_layout.addWidget(self.browser_combo)
        
        # Add custom browser button - use a proper grid layout for buttons
        button_grid = QGridLayout()
        button_grid.setSpacing(10)  # Add spacing between buttons
        
        self.add_browser_button = QPushButton("Add Custom Browser...")
        self.add_browser_button.setMinimumHeight(32)  # Ensure height
        self.add_browser_button.clicked.connect(self.add_custom_browser)
        button_grid.addWidget(self.add_browser_button, 0, 0)
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setMinimumHeight(32)  # Ensure height
        self.refresh_button.clicked.connect(self.refresh_browsers)
        button_grid.addWidget(self.refresh_button, 0, 1)
        
        browser_layout.addLayout(button_grid)
        
        self.launch_new_group.setLayout(browser_layout)
        main_layout.addWidget(self.launch_new_group)
        
        # Running browser selection
        self.connect_existing_group = QGroupBox("Select Running Browser")
        running_browser_layout = QVBoxLayout()
        running_browser_layout.setSpacing(10)  # Increase spacing
        
        self.running_browser_combo = QComboBox()
        self.running_browser_combo.setMinimumHeight(30)  # Make combo box taller
        running_browser_layout.addWidget(self.running_browser_combo)
        
        self.detect_button = QPushButton("Detect Running Browsers")
        self.detect_button.setMinimumHeight(32)  # Ensure height
        self.detect_button.clicked.connect(self.detect_running_browsers)
        running_browser_layout.addWidget(self.detect_button)
        
        self.connect_existing_group.setLayout(running_browser_layout)
        self.connect_existing_group.setVisible(False)
        main_layout.addWidget(self.connect_existing_group)
        
        # Port options (only for new browser)
        self.port_box = QGroupBox("Debugging Port")
        port_layout = QGridLayout()
        port_layout.setSpacing(10)  # Increase spacing
        
        self.auto_port_radio = QRadioButton("Auto-select available port")
        self.auto_port_radio.setChecked(True)
        port_layout.addWidget(self.auto_port_radio, 0, 0, 1, 2)
        
        self.custom_port_radio = QRadioButton("Use custom port:")
        port_layout.addWidget(self.custom_port_radio, 1, 0)
        
        self.port_combo = QComboBox()
        self.port_combo.setMinimumHeight(30)  # Make combo box taller
        for port in range(9222, 9232):
            self.port_combo.addItem(str(port))
        self.port_combo.setCurrentText(str(DEFAULT_DEBUG_PORT))
        self.port_combo.setEnabled(False)
        port_layout.addWidget(self.port_combo, 1, 1)
        
        # Group the radio buttons
        self.port_group = QButtonGroup(self)
        self.port_group.addButton(self.auto_port_radio)
        self.port_group.addButton(self.custom_port_radio)
        self.port_group.buttonClicked.connect(self.on_port_option_changed)
        
        self.port_box.setLayout(port_layout)
        main_layout.addWidget(self.port_box)
        
        # URL options (only for new browser)
        self.url_box = QGroupBox("Start Page")
        url_layout = QGridLayout()
        url_layout.setSpacing(10)  # Increase spacing
        
        self.blank_page_radio = QRadioButton("Blank page")
        self.blank_page_radio.setChecked(True)
        url_layout.addWidget(self.blank_page_radio, 0, 0, 1, 2)
        
        self.url_box.setLayout(url_layout)
        main_layout.addWidget(self.url_box)
        
        # Set as default
        self.default_check = QCheckBox("Remember as default browser")
        main_layout.addWidget(self.default_check)
        
        # Debug info checkbox
        self.debug_check = QCheckBox("Show debug information")
        self.debug_check.setChecked(False)
        self.debug_check.stateChanged.connect(self.toggle_debug_info)
        main_layout.addWidget(self.debug_check)
        
        # Debug text area (hidden by default)
        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setFixedHeight(100)
        self.debug_text.setVisible(False)
        self.debug_text.setText("Click 'Refresh' to see browser detection information.")
        main_layout.addWidget(self.debug_text)
        
        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)  # Increase spacing
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumHeight(36)  # Taller action buttons
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.launch_button = QPushButton("Launch Browser")
        self.launch_button.setMinimumHeight(36)  # Taller action buttons
        self.launch_button.setDefault(True)
        # Set specific style for the launch button to ensure it's visible
        self.launch_button.setStyleSheet("""
            QPushButton { 
                background-color: #4CAF50; 
                color: white; 
                font-weight: bold; 
                font-size: 14px;
                padding: 8px 12px;
            }
            QPushButton:disabled {
                background-color: #a0a0a0;
                color: #e0e0e0;
            }
        """)
        self.launch_button.clicked.connect(self.launch_selected_browser)
        button_layout.addWidget(self.launch_button)
        
        main_layout.addLayout(button_layout)
        
        # Set specific style for all buttons to ensure they're visible
        self.setStyleSheet("""
            QPushButton { 
                padding: 8px 12px; 
                min-width: 100px; 
                min-height: 32px;
                background-color: #f0f0f0; 
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover { 
                background-color: #e0e0e0; 
            }
            QPushButton:pressed { 
                background-color: #d0d0d0; 
            }
            QGroupBox { 
                font-weight: bold; 
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                padding: 8px;
            }
            QComboBox {
                padding: 6px;
                min-height: 24px;
                border: 1px solid #ccc;
                border-radius: 4px;
                font-size: 12px;
            }
            QRadioButton, QCheckBox {
                font-size: 12px;
                min-height: 24px;
            }
        """)
    
    def update_launch_button_state(self):
        """Update the launch button state based on current selections"""
        if self.launch_new_radio.isChecked():
            # Enable button if a browser is selected
            browser_key = self.browser_combo.currentData()
            self.launch_button.setEnabled(bool(browser_key))
            self.launch_button.setText("Launch Browser")
            self.launch_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        else:
            # Enable button if a running browser is selected
            browser_key = self.running_browser_combo.currentData()
            self.launch_button.setEnabled(bool(browser_key))
            self.launch_button.setText("Connect to Browser")
            self.launch_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
    
    @pyqtSlot(bool)
    def toggle_browser_mode(self, checked):
        """Handle toggling between launch and connect modes"""
        if self.launch_new_radio.isChecked():
            # Launch mode
            self.launch_new_group.setVisible(True)
            self.connect_existing_group.setVisible(False)
            self.port_box.setVisible(True)
            self.url_box.setVisible(True)
        else:
            # Connect mode
            self.launch_new_group.setVisible(False)
            self.connect_existing_group.setVisible(True)
            self.port_box.setVisible(False)
            self.url_box.setVisible(False)
            
            # Detect running browsers when switching to this mode
            if self.running_browser_combo.count() == 0:
                self.detect_running_browsers()
                
        # Update button state after changing mode
        self.update_launch_button_state()
    
    @pyqtSlot()
    def detect_running_browsers(self):
        """Detect running browsers with debugging enabled"""
        self.running_browser_combo.clear()
        
        # Show detecting message
        if self.debug_check.isChecked():
            self.debug_text.setVisible(True)
            self.debug_text.setText("Detecting running browsers with debugging enabled...")
            QApplication.processEvents()  # Force UI update
            
        self.running_browsers = find_running_debuggable_browsers()
        
        if self.running_browsers:
            for browser_key, port in self.running_browsers.items():
                display_name = {
                    'chrome': 'Google Chrome', 
                    'edge': 'Microsoft Edge',
                    'brave': 'Brave Browser',
                    'chromium': 'Chromium'
                }.get(browser_key, browser_key.capitalize())
                
                self.running_browser_combo.addItem(f"{display_name} (port {port})", browser_key)
            
            # Show success in debug area
            if self.debug_check.isChecked():
                self.debug_text.setText(
                    f"Found {len(self.running_browsers)} running browser(s) with debugging enabled.\n\n"
                    "You can connect to one of these browsers to capture DOM snapshots.\n"
                    "No new browser window will be opened."
                )
        else:
            self.running_browser_combo.addItem("No running browsers with debugging enabled", "")
            
            # Show help text to guide user how to enable debugging
            self.debug_text.setText(
                "No running browsers with debugging enabled found.\n\n"
                "To use an existing browser with debugging enabled:\n\n"
                "1. Close all instances of Chrome/Chromium\n"
                "2. Start Chrome with debugging:\n"
                "   - macOS: open -a \"Google Chrome\" --args --remote-debugging-port=9222\n"
                "   - Windows: chrome.exe --remote-debugging-port=9222\n\n"
                "Or choose 'Launch new browser' to start a fresh browser with debugging enabled."
            )
            
        # Update button state after detecting browsers
        self.update_launch_button_state()
        
        # Connect the combo box change signal if not already connected
        try:
            self.running_browser_combo.currentIndexChanged.disconnect(self.update_launch_button_state)
        except:
            pass  # If not connected, just continue
        self.running_browser_combo.currentIndexChanged.connect(self.update_launch_button_state)
    
    def populate_browsers(self):
        """Populate the browsers dropdown with installed browsers"""
        installed_browsers = find_installed_browsers()
        
        if not installed_browsers:
            self.browser_combo.addItem("No compatible browsers found", "")
            self.launch_button.setEnabled(False)
            
            # Show helpful message in debug area
            self.debug_check.setChecked(True)
            self.debug_text.setVisible(True)
            self.debug_text.setText(
                "No compatible browsers were detected automatically.\n\n"
                "You can:\n"
                "1. Click 'Add Custom Browser' to manually select a browser\n"
                "2. Switch to 'Connect to running browser' if you have a browser running with debugging enabled\n"
                "3. Refresh to try detecting browsers again\n\n"
                "The following browsers are supported: Chrome, Edge, Brave, Opera, Vivaldi"
            )
            return
        
        # Get default browser
        default_browser = get_default_browser()
        default_idx = 0
        
        # Add browsers to dropdown
        for i, (key, name) in enumerate(installed_browsers.items()):
            self.browser_combo.addItem(name, key)
            if key == default_browser:
                default_idx = i
        
        # Set default selection
        self.browser_combo.setCurrentIndex(default_idx)
        
        # Connect the combo box change signal if not already connected
        self.browser_combo.currentIndexChanged.connect(self.update_launch_button_state)
        
        # Show helpful message in debug area
        if self.debug_check.isChecked():
            self.debug_text.setText(
                f"Found {len(installed_browsers)} browsers.\n\n"
                "Launching a browser with debugging enabled allows DuckTrack to capture DOM snapshots.\n"
                "This creates a clean browser profile - your existing browser settings won't be affected."
            )
    
    @pyqtSlot()
    def on_port_option_changed(self):
        """Handle port option radio button changes"""
        self.port_combo.setEnabled(self.custom_port_radio.isChecked())
    
    @pyqtSlot()
    def launch_selected_browser(self):
        """Launch the selected browser with debugging enabled or connect to a running one"""
        if self.launch_new_radio.isChecked():
            self._launch_new_browser()
        else:
            self._connect_to_running_browser()
    
    def _launch_new_browser(self):
        """Launch a new browser instance"""
        browser_key = self.browser_combo.currentData()
        
        if not browser_key:
            QMessageBox.warning(
                self, 
                "No Browser Selected", 
                "No compatible browser is selected. Please install a Chromium-based browser."
            )
            return
        
        # Get port
        port = None
        if self.custom_port_radio.isChecked():
            try:
                port = int(self.port_combo.currentText())
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Port",
                    "Please enter a valid port number."
                )
                return
        
        # Get URL
        url = "about:blank"  # Default to blank page
        
        # Launch browser
        success, actual_port, error = launch_browser(browser_key, port, url)
        
        if success:
            # Save as default if checked
            if self.default_check.isChecked():
                # TODO: Save default browser preference
                pass
            
            # Emit signal
            self.browser_launched.emit(browser_key, actual_port, True)
            self.accept()
        else:
            # Create a custom error dialog with options
            error_dialog = QMessageBox(self)
            error_dialog.setWindowTitle("Browser Launch Failed")
            error_dialog.setIcon(QMessageBox.Icon.Critical)
            error_dialog.setText(f"Failed to launch browser")
            error_dialog.setInformativeText(error)
            error_dialog.setDetailedText(
                "Possible solutions:\n"
                "1. Try connecting to a running browser instead\n"
                "2. Close all instances of Chrome/Chromium and try again\n"
                "3. Try using a different port number\n"
                "4. Try using a different browser"
            )
            
            # Add custom buttons
            try_connect_button = error_dialog.addButton("Connect to Running Browser", QMessageBox.ButtonRole.ActionRole)
            retry_button = error_dialog.addButton("Try Again", QMessageBox.ButtonRole.ActionRole)
            cancel_button = error_dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
            error_dialog.setDefaultButton(try_connect_button)
            
            # Show the dialog and handle the response
            error_dialog.exec()
            
            clicked_button = error_dialog.clickedButton()
            if clicked_button == try_connect_button:
                # Switch to connect mode
                self.connect_existing_radio.setChecked(True)
                self.toggle_browser_mode(True)
                self.detect_running_browsers()
            elif clicked_button == retry_button:
                # Try again with a different port
                new_port = port + 1 if port else 9333  # Try a different port
                success, actual_port, error = launch_browser(browser_key, new_port, url)
                if success:
                    self.browser_launched.emit(browser_key, actual_port, True)
                    self.accept()
                else:
                    # Simple error if second attempt fails
                    QMessageBox.critical(
                        self,
                        "Browser Launch Failed Again",
                        f"Second attempt failed: {error}\n\nPlease try connecting to a running browser instead."
                    )
            
            # Emit signal with failure
            self.browser_launched.emit(browser_key, 0, False)
    
    def _connect_to_running_browser(self):
        """Connect to a running browser"""
        browser_key = self.running_browser_combo.currentData()
        
        if not browser_key:
            QMessageBox.warning(
                self, 
                "No Running Browser Selected", 
                "No running browser with debugging enabled was found. Please start a browser with debugging enabled or use the 'Launch new browser' option."
            )
            return
        
        # Get the port from our stored dictionary
        port = self.running_browsers.get(browser_key, DEFAULT_DEBUG_PORT)
        
        # Show connecting message in debug area if enabled
        if self.debug_check.isChecked():
            self.debug_text.setVisible(True)
            self.debug_text.setText(f"Attempting to connect to browser on port {port}...")
            QApplication.processEvents()  # Force UI update
        
        # Verify connection
        success, error = connect_to_running_browser(port)
        
        if success:
            # Show success in debug area if enabled
            if self.debug_check.isChecked():
                self.debug_text.setText(f"Successfully connected to browser on port {port}!")
                QApplication.processEvents()  # Force UI update
            
            # Emit signal
            self.browser_launched.emit(browser_key, port, True)
            self.accept()
        else:
            # Show detailed error in debug area if enabled
            if self.debug_check.isChecked():
                self.debug_text.setText(f"Connection failed: {error}\n\nPlease check that Chrome is running with debugging enabled.")
            
            QMessageBox.critical(
                self,
                "Browser Connection Failed",
                f"Failed to connect to browser: {error}\n\nPlease make sure the browser is running with debugging enabled."
            )
            # Emit signal with failure
            self.browser_launched.emit(browser_key, 0, False)
    
    @pyqtSlot()
    def toggle_debug_info(self, state):
        """Toggle the visibility of debug info"""
        self.debug_text.setVisible(state > 0)
        if state > 0:
            self.resize(500, 520)  # Make dialog taller when debug is visible
        else:
            self.resize(500, 400)  # Restore original size
            
    @pyqtSlot()
    def refresh_browsers(self):
        """Refresh the browser list"""
        # Clear and repopulate
        self.browser_combo.clear()
        self.populate_browsers()
        
        # Show debug info
        if self.debug_check.isChecked():
            # Capture browser detection logs
            from io import StringIO
            import logging
            
            log_capture = StringIO()
            handler = logging.StreamHandler(log_capture)
            formatter = logging.Formatter('%(levelname)s: %(message)s')
            handler.setFormatter(formatter)
            
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            old_level = root_logger.level
            root_logger.setLevel(logging.DEBUG)
            
            # Re-run browser detection for logs
            from .browser_launcher import find_installed_browsers
            find_installed_browsers()
            
            # Restore logger
            root_logger.removeHandler(handler)
            root_logger.setLevel(old_level)
            
            # Display logs
            self.debug_text.setText(log_capture.getvalue())
            
    @pyqtSlot()
    def add_custom_browser(self):
        """Allow user to select a custom browser path"""
        from PyQt6.QtWidgets import QFileDialog
        
        # Show file dialog to select browser executable
        title = "Select Browser Application"
        file_filter = "Applications (*.app);;All Files (*)" if system() == 'darwin' else "Executables (*.exe);;All Files (*)"
        
        browser_path, _ = QFileDialog.getOpenFileName(
            self, title, "/Applications" if system() == 'darwin' else "C:\\Program Files", file_filter
        )
        
        if not browser_path:
            return
            
        # On macOS, if user selects the .app bundle, we need to extract the name
        if system() == 'darwin' and browser_path.endswith('.app'):
            app_name = os.path.basename(browser_path).replace('.app', '')
            if 'chrome' in app_name.lower():
                self.browser_combo.addItem('Google Chrome', 'chrome')
            elif 'edge' in app_name.lower():
                self.browser_combo.addItem('Microsoft Edge', 'edge')
            elif 'brave' in app_name.lower():
                self.browser_combo.addItem('Brave Browser', 'brave')
            elif 'opera' in app_name.lower():
                self.browser_combo.addItem('Opera', 'opera')
            elif 'vivaldi' in app_name.lower():
                self.browser_combo.addItem('Vivaldi', 'vivaldi')
            elif 'chromium' in app_name.lower():
                self.browser_combo.addItem('Chromium', 'chromium')
            else:
                # Generic browser, just use the name
                key = app_name.lower().replace(' ', '_')
                self.browser_combo.addItem(app_name, key)
            
            # Select the newly added browser
            self.browser_combo.setCurrentIndex(self.browser_combo.count() - 1)
        elif system() == 'windows' or system() == 'win32':
            # Extract executable name
            exe_name = os.path.basename(browser_path)
            if 'chrome' in exe_name.lower():
                self.browser_combo.addItem('Google Chrome', 'chrome')
            elif 'msedge' in exe_name.lower():
                self.browser_combo.addItem('Microsoft Edge', 'edge')
            elif 'brave' in exe_name.lower():
                self.browser_combo.addItem('Brave Browser', 'brave')
            elif 'opera' in exe_name.lower():
                self.browser_combo.addItem('Opera', 'opera')
            elif 'vivaldi' in exe_name.lower():
                self.browser_combo.addItem('Vivaldi', 'vivaldi')
            else:
                # Generic browser, just use the name without extension
                app_name = os.path.splitext(exe_name)[0]
                key = app_name.lower().replace(' ', '_')
                self.browser_combo.addItem(app_name, key)
            
            # Select the newly added browser
            self.browser_combo.setCurrentIndex(self.browser_combo.count() - 1) 