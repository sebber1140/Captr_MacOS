"""
Browser launcher dialog for DuckTrack

This module provides a dialog for launching browsers with debugging enabled.
"""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QComboBox, 
                             QPushButton, QHBoxLayout, QRadioButton,
                             QButtonGroup, QMessageBox, QCheckBox,
                             QGridLayout, QGroupBox)
from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont

from .browser_launcher import (find_installed_browsers, launch_browser,
                             get_default_browser, DEFAULT_DEBUG_PORT)

class BrowserLauncherDialog(QDialog):
    """Dialog for launching browsers with debugging enabled"""
    
    browser_launched = pyqtSignal(str, int, bool)  # browser_key, port, success
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowTitle("Launch Browser")
        self.resize(450, 280)
        
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
        
        # Browser selection
        browser_box = QGroupBox("Select Browser")
        browser_layout = QVBoxLayout()
        
        self.browser_combo = QComboBox()
        browser_layout.addWidget(self.browser_combo)
        
        browser_box.setLayout(browser_layout)
        main_layout.addWidget(browser_box)
        
        # Port options
        port_box = QGroupBox("Debugging Port")
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
        
        port_box.setLayout(port_layout)
        main_layout.addWidget(port_box)
        
        # URL options
        url_box = QGroupBox("Start Page")
        url_layout = QGridLayout()
        
        self.blank_page_radio = QRadioButton("Blank page")
        self.blank_page_radio.setChecked(True)
        url_layout.addWidget(self.blank_page_radio, 0, 0, 1, 2)
        
        url_box.setLayout(url_layout)
        main_layout.addWidget(url_box)
        
        # Set as default
        self.default_check = QCheckBox("Remember as default browser")
        main_layout.addWidget(self.default_check)
        
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
        
    def populate_browsers(self):
        """Populate the browsers dropdown with installed browsers"""
        installed_browsers = find_installed_browsers()
        
        if not installed_browsers:
            self.browser_combo.addItem("No compatible browsers found", "")
            self.launch_button.setEnabled(False)
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
        """Launch the selected browser with debugging enabled"""
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