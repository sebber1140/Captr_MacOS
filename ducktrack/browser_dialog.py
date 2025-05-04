"""
Browser launcher dialog for DuckTrack

This module provides a dialog for launching browsers with debugging enabled.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                             QPushButton, QHBoxLayout, QRadioButton,
                             QButtonGroup, QMessageBox, QCheckBox,
                             QGridLayout, QGroupBox, QTextEdit)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont
import os
from platform import system

from .browser_launcher import (find_installed_browsers, launch_browser,
                             get_default_browser, DEFAULT_DEBUG_PORT,
                             find_running_debuggable_browsers, connect_to_running_browser)

class BrowserLauncherDialog(QDialog):
    """Dialog for launching browsers with debugging enabled"""
    
    browser_launched = pyqtSignal(str, int, bool)  # browser_key, port, success
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Launch Browser")
        self.resize(450, 280)
        
        # Store running browsers with their ports
        self.running_browsers = {}
        
        self.create_ui()
        self.populate_browsers()
    
    def create_ui(self):
        """Create the dialog UI"""
        main_layout = QVBoxLayout(self)
        
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
        
        self.browser_combo = QComboBox()
        browser_layout.addWidget(self.browser_combo)
        
        # Add custom browser button
        custom_browser_layout = QHBoxLayout()
        self.add_browser_button = QPushButton("Add Custom Browser...")
        self.add_browser_button.clicked.connect(self.add_custom_browser)
        custom_browser_layout.addWidget(self.add_browser_button)
        
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_browsers)
        custom_browser_layout.addWidget(self.refresh_button)
        
        browser_layout.addLayout(custom_browser_layout)
        
        self.launch_new_group.setLayout(browser_layout)
        main_layout.addWidget(self.launch_new_group)
        
        # Running browser selection
        self.connect_existing_group = QGroupBox("Select Running Browser")
        running_browser_layout = QVBoxLayout()
        
        self.running_browser_combo = QComboBox()
        running_browser_layout.addWidget(self.running_browser_combo)
        
        running_refresh_layout = QHBoxLayout()
        self.detect_button = QPushButton("Detect Running Browsers")
        self.detect_button.clicked.connect(self.detect_running_browsers)
        running_refresh_layout.addWidget(self.detect_button)
        
        running_browser_layout.addLayout(running_refresh_layout)
        
        self.connect_existing_group.setLayout(running_browser_layout)
        self.connect_existing_group.setVisible(False)
        main_layout.addWidget(self.connect_existing_group)
        
        # Port options (only for new browser)
        self.port_box = QGroupBox("Debugging Port")
        port_layout = QGridLayout()
        
        self.auto_port_radio = QRadioButton("Auto-select available port")
        self.auto_port_radio.setChecked(True)
        port_layout.addWidget(self.auto_port_radio, 0, 0, 1, 2)
        
        self.custom_port_radio = QRadioButton("Use custom port:")
        port_layout.addWidget(self.custom_port_radio, 1, 0)
        
        self.port_combo = QComboBox()
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
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.launch_button = QPushButton("Launch Browser")
        self.launch_button.setDefault(True)
        self.launch_button.clicked.connect(self.launch_selected_browser)
        button_layout.addWidget(self.launch_button)
        
        main_layout.addLayout(button_layout)
    
    @pyqtSlot(bool)
    def toggle_browser_mode(self, checked):
        """Handle toggling between launch and connect modes"""
        if self.launch_new_radio.isChecked():
            # Launch mode
            self.launch_new_group.setVisible(True)
            self.connect_existing_group.setVisible(False)
            self.port_box.setVisible(True)
            self.url_box.setVisible(True)
            self.launch_button.setText("Launch Browser")
        else:
            # Connect mode
            self.launch_new_group.setVisible(False)
            self.connect_existing_group.setVisible(True)
            self.port_box.setVisible(False)
            self.url_box.setVisible(False)
            self.launch_button.setText("Connect to Browser")
            
            # Detect running browsers when switching to this mode
            if self.running_browser_combo.count() == 0:
                self.detect_running_browsers()
    
    @pyqtSlot()
    def detect_running_browsers(self):
        """Detect running browsers with debugging enabled"""
        self.running_browser_combo.clear()
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
        else:
            self.running_browser_combo.addItem("No running browsers with debugging enabled", "")
            
            # Show help text if debug is enabled
            if self.debug_check.isChecked():
                self.debug_text.setText(
                    "No running browsers with debugging enabled found.\n\n"
                    "To use an existing browser, start it with the '--remote-debugging-port=9222' flag.\n"
                    "For example: 'open -a \"Google Chrome\" --args --remote-debugging-port=9222'\n\n"
                    "Alternatively, use the 'Launch new browser' option."
                )
    
    def populate_browsers(self):
        """Populate the browsers dropdown with installed browsers"""
        installed_browsers = find_installed_browsers()
        
        if not installed_browsers:
            self.browser_combo.addItem("No compatible browsers found", "")
            self.launch_button.setEnabled(self.connect_existing_radio.isChecked())
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
            QMessageBox.critical(
                self,
                "Browser Launch Failed",
                f"Failed to launch browser: {error}"
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
        
        # Verify connection
        success, error = connect_to_running_browser(port)
        
        if success:
            # Emit signal
            self.browser_launched.emit(browser_key, port, True)
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Browser Connection Failed",
                f"Failed to connect to browser: {error}"
            )
            # Emit signal with failure
            self.browser_launched.emit(browser_key, 0, False)
    
    @pyqtSlot()
    def toggle_debug_info(self, state):
        """Toggle the visibility of debug info"""
        self.debug_text.setVisible(state > 0)
        if state > 0:
            self.resize(450, 400)  # Make dialog taller when debug is visible
        else:
            self.resize(450, 280)  # Restore original size
            
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