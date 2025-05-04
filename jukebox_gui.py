#!/usr/bin/env python3
# jukebox_gui.py
# Contiene la classe principale dell'interfaccia grafica (Jukebox),
# la tastiera virtuale (VirtualKeyboard), e il codice di avvio.

import sys
import os
import json
import threading
import requests
import time
import hashlib
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QSlider, QMessageBox,
    QInputDialog, QShortcut, QGridLayout, QFileDialog, QSpinBox,
    QSizePolicy, QProgressDialog, QDesktopWidget, QCheckBox,QMenu, QAction
)
from PyQt5.QtGui import QPixmap, QFont, QColor, QMovie, QKeySequence
from PyQt5.QtCore import (
    Qt, QTimer, pyqtSignal, QEvent, QPoint, QThread, QMutex, QUrl,
    QSize, QRect, QPropertyAnimation
)
import vlc # Import vlc module itself

# Importa elementi necessari dagli altri moduli
from jukebox_data import (
    vlc_instance, Track, save_json, load_json,
    DATA_DIR, COVER_DIR, DOWNLOAD_DIR, DEFAULT_COVER,
    AUDIO_EXTS, MAX_HISTORY_SIZE, YOUTUBE_REGEX, FFMPEG_PATH
)
from jukebox_workers import (
    YoutubeSearchWorker, CoverDownloadWorker, FileProbeWorker
)

# -------------------- Virtual Keyboard Widget --------------------
class VirtualKeyboard(QWidget):
    """A simple on-screen virtual keyboard, adapted for touch."""
    key_pressed = pyqtSignal(str) # Emits character or "←" for backspace
    closed = pyqtSignal()         # Emitted when the keyboard is hidden

    def __init__(self):
        # Use Popup flag to make it close when clicking outside, Frameless for custom look
        super().__init__(flags=Qt.Window | Qt.FramelessWindowHint | Qt.Tool) # <-- NUOVA RIGA (USA Qt.Tool)
        self.setStyleSheet("""
        QWidget {
            background-color: #3a3a3a; /* Darker background */
            border: 1px solid #555;
            border-radius: 8px;
            padding: 8px; /* Increased padding */
        }
        QPushButton {
            background-color: #505050; /* Slightly lighter buttons */
            color: white;
            font-size: 18px; /* Larger font */
            border-radius: 5px;
            padding: 12px 8px; /* More padding, especially vertical */
            min-height: 40px; /* Minimum button height */
            border: 1px solid #666; /* Subtle border */
            margin: 2px; /* Spacing between buttons */
        }
        QPushButton:hover {
            background-color: #656565;
            border: 1px solid #777;
        }
        QPushButton:pressed {
            background-color: #404040;
            border: 1px solid #555;
        }
        QPushButton#done_btn { /* Special style for Done button */
            background-color: #0078d7; /* Blue */
            font-weight: bold;
        }
        QPushButton#done_btn:hover { background-color: #008ae6; }
        QPushButton#done_btn:pressed { background-color: #005a9e; }

        QPushButton#backspace_btn { /* Special style for Backspace */
             font-size: 22px; /* Make symbol larger */
        }
        QPushButton#space_btn { /* Give space bar more visual weight */
            /* padding: 12px 50px; */ /* Wider padding if needed */
        }
        """)
        grid = QGridLayout(self)
        grid.setSpacing(3) # Reduced spacing within the grid itself

        # Define keyboard layout rows
        rows = [
            "`1234567890-=",
            "qwertyuiop[]\\",
            "asdfghjkl;'",
            "zxcvbnm,./"
        ]

        button_fixed_width = 50 # Fixed width for standard keys

        # Create standard character buttons
        for r, row_str in enumerate(rows):
            for c, char in enumerate(row_str):
                btn = QPushButton(char)
                btn.setFixedWidth(button_fixed_width)
                # Use lambda with default argument capture for the character
                btn.clicked.connect(lambda _, x=char: self._emit_key(x))
                grid.addWidget(btn, r, c)

        # --- Special Keys ---
        # Backspace Button (top right)
        backspace_btn = QPushButton("←")
        backspace_btn.setObjectName("backspace_btn")
        backspace_btn.setFixedWidth(int(button_fixed_width * 1.5)) # Make it wider
        backspace_btn.clicked.connect(lambda: self._emit_key("←"))
        # Place it after the first row's keys
        grid.addWidget(backspace_btn, 0, len(rows[0]), 1, 2) # Span 2 columns

        # Space Bar (bottom row, centered)
        space_btn = QPushButton(" ")
        space_btn.setObjectName("space_btn")
        space_btn.setFixedHeight(45) # Match other buttons' height + padding
        space_btn.clicked.connect(lambda: self._emit_key(" "))
        # AddWidget(widget, row, col, rowSpan, colSpan)
        grid.addWidget(space_btn, len(rows), 2, 1, 8) # Span 8 columns, starting from col 2

        # Done/Close Button (bottom right)
        close_btn = QPushButton("Done")
        close_btn.setObjectName("done_btn")
        close_btn.setFixedWidth(int(button_fixed_width * 2)) # Make it wider
        close_btn.clicked.connect(self.hide_keyboard)
        # Place it next to the space bar
        grid.addWidget(close_btn, len(rows), 10, 1, 3) # Span 3 cols

        self.target_widget = None # The QLineEdit this keyboard is attached to
        self.setLayout(grid)
        # Adjust size after adding widgets, but consider setting a min width/height
        self.adjustSize()
        self.setMinimumWidth(600) # Ensure a reasonable minimum width

    def _emit_key(self, key):
        """Emits the pressed key signal."""
        self.key_pressed.emit(key)
        # Optional: Add a small haptic feedback or sound here if desired

    def show_keyboard(self, target_widget):
        """Shows the keyboard positioned relative to the target widget."""
        # Avoid re-showing if already visible for the same target
        if self.isVisible() and self.target_widget is target_widget:
             return

        self.target_widget = target_widget
        if not self.target_widget:
             return

        # Calculate position: Below the target widget
        target_rect = self.target_widget.rect()
        # Map bottom-left corner of target widget to global screen coordinates
        global_pos = self.target_widget.mapToGlobal(target_rect.bottomLeft())

        kb_size = self.sizeHint() # Preferred size
        screen_geometry = QApplication.desktop().availableGeometry(self.target_widget)

        # Default position: directly below the target
        kb_x = global_pos.x()
        kb_y = global_pos.y() + 5 # Small offset below

        # --- Adjust position to stay within screen bounds ---
        # If keyboard goes off the right edge, align its right edge with screen right
        if kb_x + kb_size.width() > screen_geometry.right():
             kb_x = screen_geometry.right() - kb_size.width()
        # If keyboard goes off the left edge, align its left edge with screen left
        if kb_x < screen_geometry.left():
             kb_x = screen_geometry.left()

        # If keyboard goes off the bottom edge, try placing it *above* the target
        if kb_y + kb_size.height() > screen_geometry.bottom():
             kb_y = self.target_widget.mapToGlobal(target_rect.topLeft()).y() - kb_size.height() - 5 # 5px above
             # If placing above *still* goes off the top edge (unlikely but possible), pin to top
             if kb_y < screen_geometry.top():
                  kb_y = screen_geometry.top()

        # --- End Adjust position ---

        self.move(QPoint(kb_x, kb_y))
        self.show()
        #self.activateWindow() # Try to bring focus to the keyboard window

    def hide_keyboard(self):
        """Hides the keyboard and emits the closed signal."""
        print("VirtualKeyboard: hide_keyboard() chiamato") # <-- AGGIUNGI QUESTO
        if not self.isVisible():
            print("VirtualKeyboard: Già non visibile.") # <-- AGGIUNGI QUESTO
            return
        # ... resto del metodo ...
        self.hide()
        self.target_widget = None # Clear the target widget reference
        self.closed.emit()
        print("VirtualKeyboard: Nascosta.") # <-- AGGIUNGI QUESTO

    def sizeHint(self):
         """Provide a reasonable default size hint."""
         # Calculate hint based on layout, but enforce minimums
         hint = self.layout().sizeHint()
         min_width = 600
         min_height = 250 # Adjusted for touch-friendlier buttons
         return hint.expandedTo(QSize(min_width, min_height))

    # Override closeEvent if needed, e.g., if using Qt.Window instead of Qt.Popup
    # def closeEvent(self, event):
    #     self.hide_keyboard()
    #     event.accept()

# -------------------- Main Jukebox Widget --------------------
class Jukebox(QWidget):
    # --- Signals for cross-thread communication ---
    # Request playback of a track index on the main thread
    play_track_signal = pyqtSignal(int)
    # Add a list of Track objects to the playlist (from worker/import)
    add_tracks_to_playlist_signal = pyqtSignal(list)
    # Add a played Track object to history (from playback logic)
    add_to_history_signal = pyqtSignal(Track)
    # Update duration for a local file after probing (from FileProbeWorker)
    update_probe_duration_signal = pyqtSignal(str, int) # path, duration_ms
    # Signal a playback error occurred (from VLC events or playback logic)
    playback_error_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Jukebox")
        # Frameless window, but allow standard window manager interactions
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.resize(1024, 600) # Default size
        self.center_window()

        # --- VLC Player Setup ---
        if vlc_instance is None:
            # This should not happen due to checks in jukebox_data, but double-check
            QMessageBox.critical(self, "Errore Critico", "Istanza VLC non inizializzata!")
            QTimer.singleShot(100, self.close) # Close after showing message
            return
        self.player = vlc_instance.media_player_new()
        if self.player is None:
             print("FATAL ERROR: Player instance creation failed.")
             self._error("Impossibile creare un player VLC. Riavvia l'applicazione.")
             QTimer.singleShot(100, self.close)
             return

        # --- VLC Event Handling ---
        self.event_manager = self.player.event_manager()
        # Use lambda with QTimer.singleShot to ensure handler runs in main Qt thread
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached,
                                        lambda event: QTimer.singleShot(0, lambda: self._on_media_event(vlc.EventType.MediaPlayerEndReached, event)))
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError,
                                        lambda event: QTimer.singleShot(0, lambda: self._on_media_event(vlc.EventType.MediaPlayerEncounteredError, event)))
        # Optional: Add more event listeners if needed (e.g., Buffering, PositionChanged)
        # self.event_manager.event_attach(vlc.EventType.MediaPlayerBuffering,
        #                                 lambda event: QTimer.singleShot(0, lambda: self._on_media_event(vlc.EventType.MediaPlayerBuffering, event, event.u.new_cache)))
        # self.event_manager.event_attach(vlc.EventType.MediaPlayerPositionChanged,
        #                                 lambda event: QTimer.singleShot(0, lambda: self._on_media_event(vlc.EventType.MediaPlayerPositionChanged, event, event.u.new_position)))


        # --- Load Data ---
        try:
            # Load data using functions from jukebox_data, passing the Track class for conversion
            self.playlist = load_json("playlist.json", Track)
            self.history = load_json("history.json", Track)
            self.favorites = load_json("favorites.json", Track)
            print(f"Loaded {len(self.playlist)} playlist items, {len(self.history)} history items, {len(self.favorites)} favorites.")
        except Exception as e:
            print(f"Errore durante il caricamento dei file JSON: {e}")
            self._error(f"Errore durante il caricamento dei dati (playlist, storia, preferiti): {e}.\nI dati potrebbero essere resettati o incompleti.")
            # Initialize empty lists on error to prevent crashes
            self.playlist = []
            self.history = []
            self.favorites = []

        # --- State Variables ---
        self.current_idx = -1 # Index of the currently playing/paused track in playlist
        self.seeking = False # True while user is dragging the progress slider
        self.is_playing = False # Reflects player state (Playing vs Paused/Stopped/etc.)
        self.current_track_info = None # Holds the Track object currently loaded/playing

        # --- Worker References ---
        # Hold references to workers to manage their lifecycle (e.g., cancellation)
        self.yt_search_worker = None
        self.cover_worker = None
        self.probe_workers = [] # Can have multiple file probes running
        self.is_searching = False
        self.context_download_worker = None
        # --- Virtual Keyboard ---
        self.vkbd = VirtualKeyboard()
        self.vkbd.key_pressed.connect(self._vk_input) # Connect keyboard output to input handler
        # Optional: self.vkbd.closed.connect(self.on_vkbd_closed) # Handle keyboard closing if needed

        # --- Dragging Frameless Window ---
        self.dragging = False
        self.drag_pos = QPoint() # Stores the offset when dragging starts

        # --- Initialize UI ---
        self._style()     # Apply CSS styles
        self._ui()        # Create and layout widgets
        self._shortcuts() # Setup keyboard shortcuts
        self._timer()     # Start UI update timer (for progress bar etc.)

        # --- Connect Signals to Slots ---
        # These handle requests coming from signals emitted (potentially cross-thread)
        self.play_track_signal.connect(self._play_current_index)
        self.add_tracks_to_playlist_signal.connect(self._add_tracks_to_playlist)
        self.add_to_history_signal.connect(self._add_to_history)
        self.update_probe_duration_signal.connect(self._handle_probe_done)
        self.playback_error_signal.connect(self._handle_playback_error)

        # --- Final Setup ---
        # Install event filter on search input to trigger virtual keyboard
        self.search_in.installEventFilter(self)

        # Populate lists with loaded data
        self._refresh_lists()

        # Auto-play first track if playlist is not empty on startup
        if self.playlist:
            self.current_idx = 0 # Set index before emitting signal
            self.play_track_signal.emit(self.current_idx)
        else:
             self._clear_media_info() # Ensure UI is cleared if no tracks


    # --- Window Management and Dragging ---
    def center_window(self):
        """Centers the window on the screen."""
        try:
            screen = QApplication.desktop().screenGeometry()
            self.move(screen.center() - self.rect().center())
        except Exception as e:
             print(f"Warning: Could not center window: {e}")

    def mousePressEvent(self, event):
        """Handles mouse press for dragging the frameless window."""
        if event.button() == Qt.LeftButton:
            # Define the draggable area (e.g., top 50 pixels, excluding buttons)
            header_height = 50 # Adjust as needed
            # Make draggable area slightly dynamic based on search bar position
            if hasattr(self, 'search_in') and self.search_in:
                 try:
                    # Use the top position of the search bar container layout
                    sr_layout = self.search_in.parentWidget().layout() # QHBoxLayout 'sr'
                    if sr_layout:
                         # Get geometry of the layout relative to the main window
                         layout_rect = sr_layout.geometry()
                         # Use the top of the layout as the bottom of the drag area
                         header_height = layout_rect.top() - 5 # 5px margin
                         header_height = max(20, header_height) # Ensure minimum drag height
                 except Exception:
                      header_height = 50 # Fallback

            header_drag_area = QRect(0, 0, self.width(), header_height)

            # Check if click is within the drag area AND not on an interactive widget (like close button)
            widget_at_click = self.childAt(event.pos())
            is_on_button = isinstance(widget_at_click, QPushButton)
            is_on_spinbox = isinstance(widget_at_click, QSpinBox)
            # Add other widgets to exclude if necessary

            if header_drag_area.contains(event.pos()) and not (is_on_button or is_on_spinbox):
                self.dragging = True
                # Calculate offset from window top-left to click position
                self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
                event.accept() # Indicate event was handled
                return # Don't pass to base class if dragging started

        # If not dragging, let the base class handle the event (e.g., for focus)
        self.dragging = False
        super().mousePressEvent(event)


    def mouseMoveEvent(self, event):
        """Handles mouse move for dragging."""
        # Only move if dragging started and left button is held
        if event.buttons() == Qt.LeftButton and self.dragging:
            # Move window to new global position based on mouse and stored offset
            self.move(event.globalPos() - self.drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handles mouse release to stop dragging."""
        if event.button() == Qt.LeftButton and self.dragging:
            self.dragging = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    # --- UI Styling and Creation ---
    def _style(self):
        """Applies CSS styling to the widgets."""
        self.setStyleSheet("""
        QWidget {
            background-color: #1e1e1e; /* Dark background */
            color: #e0e0e0; /* Light grey text */
            font-family: Arial, sans-serif; /* Consistent font */
            font-size: 14px; /* Base font size */
        }
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #4a4a4a, stop:1 #333);
            border: 1px solid #555;
            border-radius: 6px; /* Slightly less rounded */
            padding: 8px 16px; /* Comfortable padding */
            font-size: 15px; /* Button text size */
            color: white;
            min-height: 30px; /* Ensure minimum height */
        }
        QPushButton:hover {
            background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #5a5a5a, stop:1 #444);
            border: 1px solid #777;
        }
        QPushButton:pressed {
            background-color: #2a2a2a;
            border: 1px solid #444;
        }
        QPushButton:disabled {
            background-color: #444;
            color: #888;
            border: 1px solid #555;
        }

        QSlider::groove:horizontal {
            border: 1px solid #444;
            height: 8px; /* Thinner groove */
            background: #3a3a3a;
            margin: 2px 0;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #00cc66; /* Bright green handle */
            border: 1px solid #00994d;
            width: 18px; /* Handle width */
            margin: -6px 0; /* Vertical centering */
            border-radius: 9px; /* Circular handle */
        }
        QSlider::handle:horizontal:hover {
            background: #33ff99;
            border: 1px solid #00cc66;
        }
        QSlider::handle:horizontal:disabled {
             background: #666;
             border: 1px solid #555;
        }

        QListWidget {
            background-color: #2e2e2e;
            border: 1px solid #444;
            border-radius: 8px;
            padding: 5px;
            color: #e0e0e0;
            font-size: 14px;
            alternate-background-color: #333333; /* Subtle row alternation */
        }
        QListWidget::item {
            padding: 6px 4px; /* Item padding */
            border-bottom: 1px solid #3a3a3a; /* Separator */
            color: #e0e0e0;
        }
        QListWidget::item:last { border-bottom: none; } /* No border on last item */
        QListWidget::item:selected {
            background-color: #0078d7; /* Selection color */
            color: white;
            border-radius: 3px;
        }
        QListWidget::item:hover {
            background-color: #3e3e3e; /* Hover color */
            border-radius: 3px;
        }

        QLabel { color: #e0e0e0; } /* Default label color */
        QLabel#cover_lbl {
            border: 2px solid #444;
            border-radius: 10px;
            background-color: #282828; /* Darker background for cover area */
            min-width: 300px; /* Minimum cover size */
            min-height: 169px;
        }
        QLabel#title_label { /* Specific style for main title */
            color: #00e673; /* Bright green title */
            font-size: 22px;
            font-weight: bold;
            padding-bottom: 5px; /* Space below title */
        }
        QLabel#info_lbl { /* Style for track title/duration */
            font-size: 15px;
            min-height: 2.5em; /* Ensure space for two lines */
            padding: 5px;
            color: #cccccc; /* Slightly dimmer info text */
        }
        QLabel#time_lbl { font-size: 13px; color: #bbbbbb; }
        QLabel#query_lbl { /* Style for status/progress messages */
            color: #00cc66; /* Green status text */
            font-size: 14px;
            min-height: 1.2em;
            padding: 2px;
        }

        QLineEdit {
            padding: 8px 10px;
            border: 1px solid #555;
            border-radius: 5px;
            background-color: #333;
            color: white;
            font-size: 16px; /* Larger search input text */
        }
        QLineEdit:focus { border: 1px solid #0078d7; } /* Highlight on focus */

        QSpinBox {
            padding: 5px 8px;
            border: 1px solid #555;
            border-radius: 5px;
            background: #333;
            color: white;
            font-size: 14px;
            min-width: 50px; /* Min width for spinbox */
        }
        QSpinBox::up-button, QSpinBox::down-button { width: 18px; } /* Size of arrows */
        QSpinBox::up-button:hover, QSpinBox::down-button:hover { background-color: #555; }

        /* Specific Button Styles */
        QPushButton#play_pause_btn { font-weight: bold; font-size: 16px; }
        QPushButton#add_fav_btn { background-color: #4CAF50; border-color: #388E3C; }
        QPushButton#add_fav_btn:hover { background-color: #5cd65c; }
        QPushButton#add_fav_btn:pressed { background-color: #388E3C; }
        QPushButton#close_button { /* Style for 'X' close button */
            background-color: #e81123; /* Red */
            border: 1px solid #a3000f;
            border-radius: 15px; /* Circular */
            font-size: 14px;
            font-weight: bold;
            padding: 0; /* Remove padding */
            color: white;
            min-width: 30px; min-height: 30px; /* Fixed size */
            max-width: 30px; max-height: 30px;
        }
        QPushButton#close_button:hover { background-color: #f14c59; border-color: #c00; }
        QPushButton#close_button:pressed { background-color: #a3000f; border-color: #800; }

        QCheckBox { color: #e0e0e0; spacing: 8px; /* Space between indicator and text */ }
        QCheckBox::indicator { width: 18px; height: 18px; }
        QCheckBox::indicator:unchecked {
            background-color: #444; border: 1px solid #666; border-radius: 3px;
        }
        QCheckBox::indicator:checked {
            background-color: #00cc66; border: 1px solid #00994d; border-radius: 3px;
        }
        /* Simple visual checkmark using font character (or border trick) */
        QCheckBox::indicator:checked::after {
             /* content: '✔'; */ /* Using a character */
             /* color: black; */
             /* position: relative; left: 3px; top: -1px; */
             /* OR Border trick (adjust positioning) */
             content: ""; display: block; position: relative;
             left: 6px; top: 3px; width: 4px; height: 8px;
             border: solid white; border-width: 0 2px 2px 0;
             transform: rotate(45deg);
        }
        QCheckBox:disabled { color: #888; }
        QCheckBox::indicator:disabled { background-color: #3a3a3a; border: 1px solid #555; }
        QCheckBox::indicator:checked:disabled { background-color: #558870; border: 1px solid #446655; }
        QCheckBox::indicator:checked:disabled::after { border-color: #aaa; }

        QMessageBox { background-color: #2e2e2e; }
        QMessageBox QLabel { color: white; font-size: 14px; }
        QMessageBox QPushButton { font-size: 14px; padding: 6px 12px; min-width: 80px;}

        QInputDialog { background-color: #2e2e2e; }
        QInputDialog QLabel { color: white; font-size: 14px; }
        QInputDialog QComboBox { background-color: #333; color: white; border: 1px solid #555; padding: 5px;}
        QInputDialog QLineEdit { /* Inherits base style, fine */ }
        QInputDialog QPushButton { font-size: 14px; padding: 6px 12px; min-width: 80px;}

        /* Style for the loading indicator */
        QLabel#loading_lbl { /* Add if needed */ }

        """)


    def _btn(self, text, fn, w=None, color_start=None, color_end=None, object_name=None):
        """Helper function to create styled QPushButtons."""
        b = QPushButton(text)
        b.clicked.connect(fn)
        if object_name:
            b.setObjectName(object_name)
        # Apply specific gradient if colors are provided
        if color_start and color_end:
            # Lighter hover colors
            hover_start = QColor(color_start).lighter(120).name()
            hover_end = QColor(color_end).lighter(120).name()
            # Darker pressed color
            pressed_color = QColor(color_end).darker(150).name()
            # Base object name selector or just QPushButton
            selector = f"QPushButton#{object_name}" if object_name else "QPushButton"

            # Construct style string (overrides base style for this button)
            # Use triple quotes for multi-line f-string
            button_style = f"""
            {selector} {{
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {color_start}, stop:1 {color_end});
            }}
            {selector}:hover {{
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {hover_start}, stop:1 {hover_end});
            }}
            {selector}:pressed {{
                background-color: {pressed_color};
            }}
            """
            # Apply the specific style (append to existing or set)
            current_style = b.styleSheet()
            b.setStyleSheet(current_style + button_style) # Append specific style

        if w: # Set fixed width if provided
            b.setFixedWidth(w)
        return b

    def _ui(self):
        """Creates and lays out the user interface widgets."""
        root = QVBoxLayout(self)
        root.setSpacing(12) # Spacing between main layout sections
        root.setContentsMargins(15, 10, 15, 10) # Margins around the window content

        # --- Header Area (Title, Loading, Close) ---
        hdr = QHBoxLayout()
        hdr.setSpacing(10)
        # Loading Indicator (GIF)
        self.loading_lbl = QLabel(objectName="loading_lbl") # Assign object name if specific styling needed
        gif_path = DATA_DIR / "loading_fumetto.gif" # Assumes GIF is in 'data' subdir
        self.loading_movie = None
        if gif_path.exists():
            self.loading_movie = QMovie(str(gif_path))
            self.loading_lbl.setMovie(self.loading_movie)
            self.loading_lbl.setFixedSize(32, 32) # Adjust size as needed
            self.loading_lbl.setScaledContents(True)
            self.loading_movie.start() # Start animation
            self.loading_lbl.hide() # Initially hidden
        else:
             print(f"Warning: Loading GIF not found at {gif_path}. Loading indicator disabled.")
             self.loading_lbl.setText("...") # Fallback text
             self.loading_lbl.setFixedSize(32, 32)
             self.loading_lbl.setAlignment(Qt.AlignCenter)
             self.loading_lbl.hide()

        hdr.addWidget(self.loading_lbl, 0, Qt.AlignLeft | Qt.AlignVCenter) # Align left

        # Title Label
        self.title_label = QLabel("YouTube Jukebox", objectName="title_label") # Use object name for styling
        self.title_label.setAlignment(Qt.AlignCenter)
        hdr.addStretch(1) # Push title towards center
        hdr.addWidget(self.title_label)
        hdr.addStretch(1) # Push close button towards right

        # Close Button
        close_btn = QPushButton("X", objectName="close_button") # Use object name for styling
        close_btn.setFixedSize(30, 30) # Ensure size matches style
        #close_btn.setStyleSheet("...") # Style defined in _style() by object name
        close_btn.setToolTip("Chiudi Applicazione")
        close_btn.clicked.connect(self.close)
        hdr.addWidget(close_btn, 0, Qt.AlignRight | Qt.AlignTop) # Align top-right
        root.addLayout(hdr)

        # --- Search and Options Area ---
        sr = QHBoxLayout() # Search Row layout
        sr.setSpacing(8)
        self.search_in = QLineEdit(placeholderText="Cerca canzone, artista o incolla URL...")
        self.search_in.setMinimumHeight(38) # Ensure decent height
        # Trigger search on Enter/Return key press in the search field
        self.search_in.returnPressed.connect(self.search_song)
        sr.addWidget(self.search_in, 1) # Line edit takes available space

        sr.addWidget(self._btn("Cerca", self.search_song, 100)) # Search button
        sr.addWidget(self._btn("Apri File", self._import_files, 100)) # Import button

        # Download Checkbox (MP3) - Enabled based on FFMPEG_PATH from jukebox_data
        self.download_checkbox = QCheckBox("Download MP3") # Text updated
        if FFMPEG_PATH:
            self.download_checkbox.setChecked(False) # Default unchecked
            self.download_checkbox.setToolTip("Se selezionato, scarica l'audio in formato MP3 nella cartella 'data/downloads' quando si cerca tramite URL diretto.\nRichiede FFmpeg installato e nel PATH.")
            self.download_checkbox.setEnabled(True)
        else:
            self.download_checkbox.setChecked(False)
            self.download_checkbox.setToolTip("Download MP3 disabilitato: FFmpeg non trovato nel sistema.\nInstalla FFmpeg per abilitare questa funzione.")
            self.download_checkbox.setEnabled(False) # Disable if FFmpeg is missing

        sr.addWidget(self.download_checkbox)

        # YouTube Results Count SpinBox
        sr.addWidget(QLabel("Ris. YT:"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 50) # Min/Max results
        self.spin.setValue(10)    # Default results
        self.spin.setToolTip("Numero massimo di risultati da mostrare per le ricerche testuali su YouTube.")
        self.spin.setFixedWidth(60)
        sr.addWidget(self.spin)

        # Favorites Button
        sr.addWidget(self._btn("Preferiti", self.show_favorites, 100, color_start="#4CAF50", color_end="#388E3C"))

        root.addLayout(sr)

        # --- Status/Query Label ---
        self.query_lbl = QLabel("", alignment=Qt.AlignCenter, objectName="query_lbl")
        # self.query_lbl.setStyleSheet(...) # Style defined in _style() by object name
        root.addWidget(self.query_lbl)

        # --- Media Player Area (Cover, Info, Progress, Volume, Controls) ---
        media_area = QHBoxLayout()
        media_area.setSpacing(20)
        media_area.setAlignment(Qt.AlignTop)

        # Left Side: Cover, Info, Progress, Volume
        info_progress_area = QVBoxLayout()
        info_progress_area.setSpacing(10)
        info_progress_area.setAlignment(Qt.AlignTop | Qt.AlignHCenter) # Center items horizontally

        self.cover_lbl = QLabel(alignment=Qt.AlignCenter, objectName="cover_lbl")
        self.cover_lbl.setFixedSize(320, 180) # Fixed size for cover art
        self.set_default_cover() # Load initial default cover
        info_progress_area.addWidget(self.cover_lbl)

        self.info_lbl = QLabel("Titolo: -\nDurata: -", alignment=Qt.AlignCenter, objectName="info_lbl")
        # self.info_lbl.setStyleSheet(...) # Style in _style()
        info_progress_area.addWidget(self.info_lbl)

        # Progress Bar Layout
        pr = QHBoxLayout() # Progress Row layout
        pr.setSpacing(5)
        self.progress = QSlider(Qt.Horizontal)
        self.progress.setToolTip("Posizione nel brano")
        self.progress.sliderPressed.connect(lambda: setattr(self,'seeking',True)) # Flag seeking on press
        self.progress.sliderReleased.connect(self._seek_finish) # Handle seek on release
        # Optional: Connect valueChanged while seeking for live time update
        # self.progress.valueChanged.connect(self._update_time_label_while_seeking)
        pr.addWidget(self.progress, 1) # Slider takes available space

        self.time_lbl = QLabel("00:00 / 00:00", alignment=Qt.AlignRight, objectName="time_lbl")
        self.time_lbl.setFixedWidth(110) # Fixed width for time display
        pr.addWidget(self.time_lbl)
        info_progress_area.addLayout(pr)

        # Volume Control Layout
        vol_layout = QHBoxLayout()
        vol_layout.setSpacing(5)
        vol_layout.addWidget(QLabel("Volume:"))
        self.vol = QSlider(Qt.Horizontal, objectName="volumeSlider") # Object name for specific handle style
        self.vol.setRange(0, 100)
        self.vol.setValue(80) # Default volume
        self.vol.valueChanged.connect(self._set_volume)
        self.vol.setToolTip("Regola Volume")
        self.vol.setFixedWidth(180) # Fixed width for volume slider
        vol_layout.addWidget(self.vol)
        vol_layout.addStretch(1) # Push slider to the left within its space
        info_progress_area.addLayout(vol_layout)
        info_progress_area.addStretch(1) # Add stretch at the bottom if needed

        # Right Side: Playback Controls and Favorites Button
        ctl = QVBoxLayout() # Controls layout
        ctl.setSpacing(15)
        ctl.setAlignment(Qt.AlignCenter) # Center buttons vertically and horizontally

        ctl.addStretch(1) # Push controls down slightly

        # Main Control Buttons (Prev, Play/Pause, Next)
        ctl_buttons = QHBoxLayout()
        ctl_buttons.setSpacing(15)
        ctl_buttons.setAlignment(Qt.AlignCenter)
        ctl_buttons.addWidget(self._btn("<< Prec", self.play_previous, 110)) # Previous Track
        self.play_pause_btn = self._btn("Play", self.toggle_play, 120, object_name="play_pause_btn") # Play/Pause
        self._update_play_pause_button() # Set initial text
        ctl_buttons.addWidget(self.play_pause_btn)
        ctl_buttons.addWidget(self._btn("Succ >>", self.play_next, 110)) # Next Track
        ctl.addLayout(ctl_buttons)

        # Add to Favorites Button
        fav_layout = QHBoxLayout()
        fav_layout.setAlignment(Qt.AlignCenter)
        self.add_fav_btn = self._btn("Aggiungi ai Preferiti", self.add_to_favorites, 200, object_name="add_fav_btn")
        # self.add_fav_btn.setStyleSheet(...) # Style applied via _btn using object name
        fav_layout.addWidget(self.add_fav_btn)
        ctl.addLayout(fav_layout)

        ctl.addStretch(1) # Push controls up slightly

        # Add left and right sides to the media_area layout
        media_area.addLayout(info_progress_area, 1) # Info/Progress side takes proportional space
        media_area.addLayout(ctl, 0) # Controls side takes fixed space based on contents

        root.addLayout(media_area) # Add media area to main layout

        # --- Playlist and History Lists Area ---
        lists = QHBoxLayout()
        lists.setSpacing(15)

        # Playlist Queue Area
        queue_vbox = QVBoxLayout()
        queue_vbox.setSpacing(5)
        queue_vbox.addWidget(QLabel("Playlist (Doppio Click per Riprodurre):"))
        self.queue = QListWidget()
        self.queue.setAlternatingRowColors(True) # Use alternating colors from style
        self.queue.itemDoubleClicked.connect(self._queue_double_clicked)
        self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue.customContextMenuRequested.connect(self._show_playlist_context_menu)
        # Add context menu for removing items? (Optional)
        # self.queue.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.queue.customContextMenuRequested.connect(self._show_playlist_context_menu)
        queue_vbox.addWidget(self.queue, 1) # List takes available vertical space
        lists.addLayout(queue_vbox, 1) # Playlist takes proportional horizontal space

        # History List Area
        history_vbox = QVBoxLayout()
        history_vbox.setSpacing(5)
        history_vbox.addWidget(QLabel(f"Cronologia (Doppio Click per Aggiungere in Coda):")) # Max size info removed
        self.history_list = QListWidget()
        self.history_list.setAlternatingRowColors(True)
        self.history_list.itemDoubleClicked.connect(self._history_double_clicked)
        # Add context menu for adding to playlist or favorites? (Optional)
        # self.history_list.setContextMenuPolicy(Qt.CustomContextMenu)
        # self.history_list.customContextMenuRequested.connect(self._show_history_context_menu)
        history_vbox.addWidget(self.history_list, 1)
        lists.addLayout(history_vbox, 1) # History takes proportional horizontal space

        root.addLayout(lists, 1) # Add lists area, make it stretch vertically

    # --- Keyboard Shortcuts ---
    def _shortcuts(self):
        """Sets up global keyboard shortcuts."""
        # Playback Controls
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self.play_next)
        QShortcut(QKeySequence(Qt.Key_Left), self, activated=self.play_previous)

        # Volume Controls
        QShortcut(QKeySequence(Qt.Key_Up), self, activated=lambda: self.vol.setValue(min(100, self.vol.value() + 5)))
        QShortcut(QKeySequence(Qt.Key_Down), self, activated=lambda: self.vol.setValue(max(0, self.vol.value() - 5)))

        # Window Controls
        QShortcut(QKeySequence(Qt.Key_F11), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close) # Use Esc to close

        # Search Field Activation (using Return/Enter handled by QLineEdit signal)

    # --- Timer for UI Updates ---
    def _timer(self):
        """Starts a timer to periodically update the UI (progress bar, time)."""
        self.t = QTimer(self)
        self.t.setInterval(200) # Update interval (milliseconds) - 5 times/sec
        self.t.timeout.connect(self._update_progress)
        self.t.start()

    # --- UI Update Methods ---
    def _update_progress(self):
        """Updates the progress slider and time labels based on player state."""
        # Avoid updates if player doesn't exist or user is dragging slider
        if self.seeking or not self.player:
            return

        media = self.player.get_media()
        if not media: # No media loaded
             if self.progress.maximum() != 0: # Reset only if needed
                 self.progress.setMaximum(0)
                 self.progress.setValue(0)
                 self.time_lbl.setText("00:00 / 00:00")
             # Ensure play/pause button reflects stopped state if necessary
             if self.is_playing:
                  self.is_playing = False
                  self._update_play_pause_button()
             return

        # Get player state and times
        state = self.player.get_state()
        pos_ms = self.player.get_time()      # Current time in ms
        dur_ms = self.player.get_length()     # Total duration in ms

        # --- Update Play/Pause Button ---
        # Check if the actual playing state changed
        current_vlc_is_playing = (state == vlc.State.Playing)
        if current_vlc_is_playing != self.is_playing:
            self.is_playing = current_vlc_is_playing
            self._update_play_pause_button()

        # --- Update Progress Bar and Time Labels ---
        # Only update if playing, paused, or buffering (and duration is valid)
        if state in (vlc.State.Playing, vlc.State.Paused, vlc.State.Buffering):
            if dur_ms is not None and dur_ms > 0:
                 # Valid duration, update slider and labels
                 dur_sec = dur_ms // 1000
                 pos_sec = max(0, pos_ms // 1000 if pos_ms is not None else 0)

                 # Update slider maximum only if it changed
                 if self.progress.maximum() != dur_sec:
                     self.progress.setMaximum(dur_sec)
                 # Update slider position
                 self.progress.setValue(pos_sec)
                 # Update time label
                 self.time_lbl.setText(f"{self._fmt_time(pos_ms)} / {self._fmt_time(dur_ms)}")
                 self.progress.setEnabled(True)
            else:
                 # No duration available (e.g., stream, radio, or not parsed yet)
                 # Show only current time, disable slider seeking
                 self.progress.setMaximum(0) # Indicate unknown duration
                 self.progress.setValue(0)
                 self.progress.setEnabled(False) # Disable seeking
                 pos_str = self._fmt_time(pos_ms) if pos_ms is not None else "00:00"
                 self.time_lbl.setText(f"{pos_str} / --:--")
        else:
            # Player is stopped, ended, error, etc.
            if self.progress.maximum() != 0: # Reset only if needed
                self.progress.setMaximum(0)
                self.progress.setValue(0)
                self.time_lbl.setText("00:00 / 00:00")
                self.progress.setEnabled(False) # Disable seeking


    @staticmethod
    def _fmt_time(ms):
        """Formats milliseconds into HH:MM:SS or MM:SS string."""
        if ms is None or ms < 0:
             return "--:--" # Indicate invalid time

        s = round(ms / 1000) # Round to nearest second
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)

        if h > 0:
            return f"{h:d}:{m:02d}:{s:02d}" # HH:MM:SS
        else:
            return f"{m:02d}:{s:02d}"       # MM:SS

    def _seek_finish(self):
        """Applies the seek when the user releases the progress slider."""
        if not self.player or not self.player.get_media() or not self.player.is_seekable():
            print("Seek failed: Player not ready or media not seekable.")
            self.seeking = False
            self._update_progress() # Refresh progress bar to actual position
            return

        target_sec = self.progress.value()
        target_ms = target_sec * 1000

        # Optional: Clamp seek value slightly from the end to avoid issues
        # dur_ms = self.player.get_length()
        # if dur_ms and dur_ms > 1000:
        #     target_ms = min(target_ms, dur_ms - 500) # Seek max 0.5s before end

        print(f"Seeking to: {self._fmt_time(target_ms)} ({target_ms} ms)")
        if self.player.set_time(target_ms) == 0:
            print("Seek successful.")
            # VLC might take a moment to update its internal time after seek.
            # Force an immediate progress update based on the target value.
            # self._update_progress() # This might show the old time briefly
        else:
            print("Seek command failed.")
            # Update progress to reflect actual position if seek failed
            # self._update_progress()

        # Short delay before clearing seeking flag allows UI to potentially catch up
        QTimer.singleShot(50, lambda: setattr(self, 'seeking', False))
        # Set seeking false immediately if preferred:
        # self.seeking = False

    # --- VLC Event Handling Slot ---
    def _on_media_event(self, event_type, event, *args):
        """Handles events received from the VLC player."""
        if event_type == vlc.EventType.MediaPlayerEndReached:
            print("VLC Event: EndReached")
            # Use QTimer to ensure play_next runs in the main thread event loop
            QTimer.singleShot(50, self.play_next) # Small delay before playing next

        elif event_type == vlc.EventType.MediaPlayerEncounteredError:
            print("VLC Event: EncounteredError")
            # Emit signal to handle the error safely in the main thread
            self.playback_error_signal.emit("Errore durante la riproduzione del brano. Potrebbe essere corrotto o non accessibile.")

        # Example: Handle buffering state changes (optional)
        # elif event_type == vlc.EventType.MediaPlayerBuffering:
        #     buffer_percent = args[0] # First extra argument is the buffer percentage
        #     print(f"VLC Event: Buffering {buffer_percent:.1f}%")
        #     if buffer_percent < 100:
        #         self.query_lbl.setText(f"Buffering... {buffer_percent:.0f}%")
        #     else:
        #         # Buffer complete, clear message if it was buffering
        #         if "Buffering" in self.query_lbl.text():
        #              self.query_lbl.setText("")

        # Example: Handle position changes (can be very frequent!) (optional)
        # elif event_type == vlc.EventType.MediaPlayerPositionChanged:
        #      new_position_float = args[0] # Position as float 0.0 to 1.0
        #      # This event fires rapidly, avoid heavy processing here.
        #      # The _update_progress timer is usually sufficient.
        #      pass


    def _handle_playback_error(self, msg):
        """Handles playback errors signaled from VLC or playback logic."""
        print(f"Handling playback error: {msg}")
        self._error(msg) # Show error message box to user
        # Stop player and clear info
        if self.player:
             self.player.stop()
        self._clear_media_info()
        # Try to play the next track automatically after an error
        QTimer.singleShot(100, self.play_next)

    # --- Volume Control ---
    def _set_volume(self, value):
        """Sets the player volume."""
        if self.player:
            if self.player.audio_set_volume(value) == -1:
                 print(f"Error setting volume to {value}")
            # else: # Debug
            #      print(f"Volume set to {value}")

    # --- Virtual Keyboard Interaction ---
    def eventFilter(self, obj, ev):
        """Filters events to show/hide the virtual keyboard for the search input."""
        if obj is self.search_in:
            # Show keyboard when search input gains focus (e.g., by touch tap)
            if ev.type() == QEvent.FocusIn:
                # Use singleShot to ensure focus is fully processed before showing keyboard
                QTimer.singleShot(0, lambda: self.vkbd.show_keyboard(self.search_in))
            # Hide keyboard when search input loses focus (maybe not needed if Qt.Popup used)
            # elif ev.type() == QEvent.FocusOut:
            #     # Check if focus is moving TO the keyboard itself
            #     if not self.vkbd.isActiveWindow():
            #          self.vkbd.hide_keyboard()
            pass # Allow event to proceed

        # Handle clicks outside the keyboard to close it (if using Qt.Window flag)
        # This is usually handled automatically by Qt.Popup flag
        # if self.vkbd.isVisible() and ev.type() == QEvent.MouseButtonPress:
        #     if not self.vkbd.geometry().contains(ev.globalPos()):
        #         self.vkbd.hide_keyboard()

        return super().eventFilter(obj, ev) # Pass event to base class

    def _vk_input(self, char):
        """Handles input received from the virtual keyboard."""
        target = self.vkbd.target_widget
        if target and isinstance(target, QLineEdit):
            if char == "←": # Backspace
                target.backspace()
            elif char == " ": # Space
                 target.insert(" ")
            elif len(char) == 1: # Standard character
                target.insert(char)
            # Could add handling for other special keys if needed

    # --- Search and Import ---
        # Dentro la classe Jukebox in jukebox_gui.py
    def search_song(self):
        """Initiates a YouTube search or URL extraction/download."""
        query = self.search_in.text().strip()
        if not query:
            self._info("Inserisci un termine di ricerca o un URL YouTube/SoundCloud/ecc.")
            return

        # --- Check if already searching ---
        # Usa la variabile di stato self.is_searching
        if self.is_searching:
             print("Warning: Ricerca già in corso. Annullamento precedente (se possibile).")
             if self.yt_search_worker and hasattr(self.yt_search_worker, 'cancel') and self.yt_search_worker.isRunning():
                  try:
                      self.yt_search_worker.cancel()
                      # Non impostare self.is_searching = False qui,
                      # verrà fatto quando il worker annullato emette 'finished'.
                      print("Segnale di annullamento inviato al worker precedente.")
                  except RuntimeError: # Ignora se è già stato cancellato nel frattempo
                      print("Warning: Impossibile annullare worker precedente (potrebbe essere già stato eliminato).")
                      self.yt_search_worker = None # Resetta riferimento se l'oggetto non è valido
             else:
                 # Potrebbe esserci un worker non valido o non in esecuzione, resetta lo stato se necessario
                 if not (self.yt_search_worker and self.yt_search_worker.isRunning()):
                      self.is_searching = False # Forza reset dello stato se il worker non è valido/running

             # Se, nonostante il reset, is_searching fosse ancora True, esci.
             # O, più semplicemente, esci sempre se una ricerca era attiva per evitare sovrapposizioni.
             self.query_lbl.setText("Attendere fine ricerca precedente o riprovare...")
             QTimer.singleShot(2000, lambda: self.query_lbl.setText("") if "Attendere" in self.query_lbl.text() else None)
             return # Impedisce l'avvio di una nuova ricerca immediatamente


        # Hide virtual keyboard if it's open
        if self.vkbd.isVisible():
             # print("Jukebox.search_song: Chiamata a vkbd.hide_keyboard()") # Debug print
             self.vkbd.hide_keyboard()

        num_results = self.spin.value()
        download_requested = self.download_checkbox.isChecked()

        # --- Check Local Download Cache First (if it's a downloadable URL) ---
        is_potential_download_url = YOUTUBE_REGEX.search(query) # Extend regex/checks for other sites if needed
        # Verifica cache solo se è un URL potenzialmente scaricabile (non ricerca testuale)
        # e se il download non è richiesto (perché se è richiesto, vogliamo forzare il download/conversione)
        # O meglio: controlla la cache *sempre* se è un URL, indipendentemente da download_requested.
        # Se troviamo il file e download_requested=True, possiamo chiedere all'utente se vuole riscaricare?
        # Per ora, usiamo la cache se presente, ignorando download_requested se il file esiste già.
        if is_potential_download_url:
             video_id = is_potential_download_url.group(1)
             expected_ext = '.mp3' if FFMPEG_PATH else None
             extractor_prefix = 'youtube'

             cached_file_path = None
             if expected_ext:
                  potential_path = DOWNLOAD_DIR / f"{extractor_prefix}_{video_id}{expected_ext}"
                  if potential_path.exists():
                       cached_file_path = potential_path
             else:
                  for ext in AUDIO_EXTS:
                       potential_path = DOWNLOAD_DIR / f"{extractor_prefix}_{video_id}{ext}"
                       if potential_path.exists():
                            cached_file_path = potential_path
                            break

             if cached_file_path:
                 print(f"Trovato file audio locale nella cache per {query}: {cached_file_path.name}")
                 try:
                     # --- Logica per gestire la traccia dalla cache ---
                     cached_track = Track(
                         url=str(cached_file_path.resolve()),
                         title=cached_file_path.stem.replace(f"{extractor_prefix}_{video_id}", video_id),
                         thumbnail_url=None, duration_sec=0, is_local=True, webpage_url=query
                     )
                     info_json_path = cached_file_path.with_suffix(".info.json")
                     if info_json_path.exists():
                          try:
                              with open(info_json_path, 'r', encoding='utf-8') as f: info_data = json.load(f)
                              cached_track.title = info_data.get('title', cached_track.title)
                              thumbs = info_data.get('thumbnails', [])
                              cached_track.thumbnail_url = thumbs[-1].get('url') if thumbs else info_data.get('thumbnail')
                              cached_track.duration_sec = info_data.get('duration', cached_track.duration_sec)
                              print(f"Caricate info addizionali da {info_json_path.name}")
                          except Exception as e: print(f"Warning: Impossibile leggere info da {info_json_path.name}: {e}")

                     if cached_track.duration_sec <= 0:
                          print(f"Avvio probe per durata di {cached_track.title}...")
                          probe_worker = FileProbeWorker(cached_track.url)
                          probe_worker.probe_done.connect(self.update_probe_duration_signal)
                          probe_worker.finished.connect(probe_worker.deleteLater)
                          self.probe_workers.append(probe_worker)
                          probe_worker.start()

                     start_index_of_new_tracks = len(self.playlist)
                     self.add_tracks_to_playlist_signal.emit([cached_track])

                     is_player_playing = self.player and self.player.is_playing()
                     if not is_player_playing:
                          print(f"Player non in riproduzione, avvio brano locale aggiunto ({cached_track.title})")
                          self.play_track_signal.emit(start_index_of_new_tracks)
                          self.query_lbl.setText(f"Riproducendo da cache: {cached_track.title[:50]}...")
                     else:
                          print(f"Player in riproduzione, brano locale aggiunto in coda.")
                          self.query_lbl.setText(f"Aggiunto da cache in coda: {cached_track.title[:50]}...")

                     self.search_in.clear()
                     return # Stop here, loaded from cache
                 except Exception as e:
                      print(f"Errore processando traccia cache {cached_file_path.name}: {e}. Procedo con ricerca/download online.")
        # --- End Check Local Download Cache ---


        # --- Start Online Search/Download Worker ---
        print(f"Avvio worker per: '{query}', Download: {download_requested}")

        # Imposta lo stato e mostra il caricamento PRIMA di creare il worker
        self.is_searching = True
        self._show_loading()

        # Assicurati che il riferimento al worker precedente sia None
        # Non dovrebbe essere necessario se _on_search_worker_finished funziona correttamente
        # self.yt_search_worker = None

        # Crea e avvia il NUOVO worker
        # Assegna il nuovo worker a self.yt_search_worker
        self.yt_search_worker = YoutubeSearchWorker(query, num_results, download_audio=download_requested)

        # Connetti i segnali principali
        self.yt_search_worker.results_ready.connect(self._handle_search_results)
        self.yt_search_worker.error_occurred.connect(self._handle_search_error)
        self.yt_search_worker.progress_update.connect(self.query_lbl.setText) # Update status label

        # Connetti 'finished' allo slot dedicato per gestire stato e pulizia
        self.yt_search_worker.finished.connect(self._on_search_worker_finished)

        # !!! Riga rimossa: self.yt_search_worker.finished.connect(self.yt_search_worker.deleteLater) !!!

        # Avvia il worker
        self.yt_search_worker.start()

        # Dentro la classe Jukebox in jukebox_gui.py
    def _show_playlist_context_menu(self, pos):
        """Mostra il menu contestuale per la playlist."""
        item = self.queue.itemAt(pos)
        if not item:
            return # Click su spazio vuoto

        index = self.queue.row(item)
        if not (0 <= index < len(self.playlist)):
            return # Indice non valido (raro)

        track = self.playlist[index]

        # Controlli di idoneità per il download
        can_download = (
            not track.is_local and
            track.webpage_url and # Diamo priorità a webpage_url per YouTube etc.
            ('youtube.com' in track.webpage_url or 'youtu.be' in track.webpage_url) and # Limita a YouTube per ora (o estendi)
            FFMPEG_PATH is not None # FFmpeg deve essere disponibile
        )

        # Crea il menu
        menu = QMenu(self)

        # Aggiungi azione "Scarica MP3" solo se idonea
        if can_download:
            download_action = QAction(f"Scarica '{track.title[:30]}...' MP3", self)
            # Usa lambda per passare l'indice alla funzione di download
            download_action.triggered.connect(lambda checked=False, idx=index: self._download_track_from_playlist(idx))
            menu.addAction(download_action)

        # --- Opzionale: Aggiungi altre azioni ---
        remove_action = QAction("Rimuovi dalla playlist", self)
        remove_action.triggered.connect(lambda checked=False, idx=index: self._remove_track_from_playlist(idx))
        menu.addAction(remove_action)
        # --- Fine azioni opzionali ---


        # Mostra il menu nella posizione globale del click
        if menu.actions(): # Mostra solo se ci sono azioni
            menu.exec_(self.queue.mapToGlobal(pos))
    def _download_track_from_playlist(self, index):
        """Avvia il download MP3 per una traccia specifica dalla playlist."""
        if not (0 <= index < len(self.playlist)):
            self._error("Errore: Indice traccia non valido per il download.")
            return

        track_to_download = self.playlist[index]

        # Controlli (ripetuti per sicurezza)
        if track_to_download.is_local:
            self._info(f"'{track_to_download.title}' è già un file locale.")
            return
        if not FFMPEG_PATH:
            self._error("Download MP3 non possibile: FFmpeg non trovato.")
            return

        # Usa webpage_url come URL da scaricare (più affidabile per yt-dlp)
        url_to_download = track_to_download.webpage_url
        if not url_to_download or not ('youtube.com' in url_to_download or 'youtu.be' in url_to_download):
            self._error(f"Impossibile scaricare: URL non valido o non supportato per '{track_to_download.title}'.")
            return

        # --- Impedisci download multipli simultanei ---
        # Usiamo lo stesso flag 'is_searching' per semplicità
        if self.is_searching:
            self._info("Attendere la fine della ricerca/download corrente prima di avviarne un altro.")
            return
        # Potremmo aggiungere un flag specifico per il download contestuale se necessario
        # if self.context_download_worker and self.context_download_worker.isRunning():
        #     self._info("Attendere...")
        #     return

        # --- Avvia il worker di download ---
        print(f"Avvio download contestuale per indice {index}: '{track_to_download.title}' da URL: {url_to_download}")
        self.is_searching = True # Imposta lo stato globale
        self._show_loading()
        self.query_lbl.setText(f"Avvio download MP3 per: {track_to_download.title[:40]}...")

        # Crea un nuovo worker specificamente per questo download
        # Passiamo l'indice originale così l'handler sa quale traccia aggiornare
        self.context_download_worker = YoutubeSearchWorker(url_to_download, 1, download_audio=True)
        # Salva l'indice originale nel worker stesso (modifichiamo leggermente il worker)
        self.context_download_worker.original_playlist_index = index

        # Collega i segnali
        # Usiamo lo stesso handler _handle_search_results, ma dovrà sapere come aggiornare
        self.context_download_worker.results_ready.connect(self._handle_context_download_results) # Usa un handler dedicato!
        self.context_download_worker.error_occurred.connect(self._handle_context_download_error)   # Usa un handler dedicato!
        self.context_download_worker.progress_update.connect(self.query_lbl.setText)
        # Usa lo stesso slot _on_search_worker_finished per la pulizia e reset stato
        self.context_download_worker.finished.connect(self._on_search_worker_finished)

        # Avvia
        self.context_download_worker.start()
    def _handle_context_download_results(self, tracks):
        """Gestisce i risultati del download avviato dal menu contestuale."""
        sender_worker = self.sender()
        original_index = getattr(sender_worker, 'original_playlist_index', None)

        print(f"Risultato download contestuale ricevuto per indice originale {original_index}.")

        if original_index is None:
            print("Errore: Indice originale mancante nel risultato del download contestuale.")
            # Potremmo provare ad aggiungerlo in coda come fallback?
            # self._handle_search_results(tracks) # Chiamata fallback all'handler generico
            return

        if not tracks or not isinstance(tracks, list) or len(tracks) != 1:
            print(f"Errore: Risultato download contestuale non valido per indice {original_index} (ricevuto: {tracks}).")
            self._error(f"Download fallito per la traccia selezionata (nessun file valido prodotto).")
            # Lo stato is_searching verrà resettato da _on_search_worker_finished
            return

        local_track_data = tracks[0] # Dovrebbe essere il singolo Track scaricato

        if not local_track_data.is_local or not local_track_data.url:
            print(f"Errore: Il worker non ha restituito una traccia locale valida per indice {original_index}.")
            self._error(f"Download fallito per la traccia selezionata (file locale non trovato nel risultato).")
            return

        # --- Aggiorna la traccia esistente nella playlist ---
        if 0 <= original_index < len(self.playlist):
            print(f"Aggiornamento traccia all'indice {original_index} con dati locali.")
            original_track = self.playlist[original_index]
            # Aggiorna solo i campi rilevanti (URL, is_local, magari durata se disponibile)
            original_track.url = local_track_data.url
            original_track.is_local = True
            if local_track_data.duration_sec and local_track_data.duration_sec > 0:
                original_track.duration_sec = local_track_data.duration_sec
            # Potremmo anche aggiornare titolo/thumbnail se quelli scaricati sono migliori?
            # original_track.title = local_track_data.title
            # original_track.thumbnail_url = local_track_data.thumbnail_url

            # Aggiorna UI e salva
            self._refresh_lists()
            save_json("playlist.json", self.playlist)
            self.query_lbl.setText(f"Scaricato: {original_track.title[:50]}...")
            QTimer.singleShot(3000, lambda: self.query_lbl.setText("") if "Scaricato:" in self.query_lbl.text() else None)

            # Se la traccia scaricata era quella corrente, ricarica le info
            if self.current_idx == original_index:
                 self._update_info_label(original_track)
                 # Potrebbe essere necessario ricaricare il media nel player se stava suonando lo stream?
                 # self.play_track_signal.emit(self.current_idx) # Forse troppo aggressivo

            # Avvia probe se necessario (dovrebbe essere già stato fatto dal worker?)
            if original_track.duration_sec <= 0:
                 print(f"Avvio probe post-download per {original_track.title}...")
                 probe_worker = FileProbeWorker(original_track.url)
                 probe_worker.probe_done.connect(self.update_probe_duration_signal)
                 probe_worker.finished.connect(probe_worker.deleteLater)
                 self.probe_workers.append(probe_worker)
                 probe_worker.start()

        else:
            print(f"Errore: Indice originale {original_index} non più valido nella playlist dopo il download.")
            self._error("Errore interno durante l'aggiornamento della playlist dopo il download.")
            # Aggiungi comunque la traccia scaricata in coda come fallback?
            # self.add_tracks_to_playlist_signal.emit([local_track_data])

    def _handle_context_download_error(self, msg):
        """Gestisce gli errori del download avviato dal menu contestuale."""
        sender_worker = self.sender()
        original_index = getattr(sender_worker, 'original_playlist_index', None)
        track_title = "Traccia Selezionata"
        if original_index is not None and 0 <= original_index < len(self.playlist):
             track_title = self.playlist[original_index].title

        print(f"Errore durante il download contestuale per indice {original_index} ('{track_title}'): {msg}")
        self._error(f"Errore durante il download di '{track_title[:40]}...':\n{msg}")
        self.query_lbl.setText(f"Errore download: {track_title[:40]}...")
        # Lo stato is_searching verrà resettato da _on_search_worker_finished


    def _remove_track_from_playlist(self, index):
        """Rimuove una traccia dalla playlist all'indice specificato."""
        if not (0 <= index < len(self.playlist)):
            print(f"Tentativo di rimuovere indice non valido: {index}")
            return

        removed_track = self.playlist.pop(index)
        print(f"Rimosso dalla playlist: '{removed_track.title}' (indice {index})")

        # Gestione se la traccia rimossa era quella corrente
        if index == self.current_idx:
            print("La traccia corrente è stata rimossa.")
            if self.player: self.player.stop()
            self._clear_media_info()
            # Decide cosa fare: suonare la successiva o fermarsi?
            if index < len(self.playlist): # Se c'è una traccia successiva nello stesso indice
                print("Avvio traccia successiva...")
                self.play_track_signal.emit(index)
            elif self.playlist: # Se ci sono altre tracce, suona la precedente (o la nuova ultima)
                print("Avvio traccia precedente/ultima...")
                new_index = max(0, index - 1) if self.playlist else -1
                if new_index != -1:
                    self.play_track_signal.emit(new_index)
                else: # Playlist diventata vuota
                     self.current_idx = -1
            else: # Playlist vuota
                 self.current_idx = -1

        elif index < self.current_idx:
            # Se abbiamo rimosso una traccia *prima* di quella corrente,
            # l'indice corrente deve essere decrementato.
            self.current_idx -= 1
            print(f"Indice corrente aggiornato a: {self.current_idx}")

        # Aggiorna UI e salva
        self._refresh_lists()
        save_json("playlist.json", self.playlist)
    def _handle_search_results(self, tracks):
        """Handles search/download results received from the YoutubeSearchWorker."""
        sender_worker = self.sender() # Identifica quale worker ha inviato il segnale

        # Non è più necessario/affidabile confrontare sender_worker con self.yt_search_worker qui,
        # perché self.yt_search_worker potrebbe essere già stato sovrascritto da una nuova ricerca.
        # La logica in _on_search_worker_finished gestisce la pulizia.
        # Ci fidiamo che i risultati arrivino dal worker che era attivo.
        # if sender_worker != self.yt_search_worker:
        #     print(f"Ignoring results from potentially outdated worker {id(sender_worker)}.")
        #     return

        print(f"Ricevuti {len(tracks)} risultati dal worker {id(sender_worker)}.")

        # Verifica se la ricerca è stata annullata o non ha prodotto risultati validi
        if not tracks:
            # Controlla lo stato attuale dell'interfaccia per evitare messaggi fuorvianti
            current_status = self.query_lbl.text()
            # Mostra info solo se non c'è un messaggio di errore o un nuovo stato di caricamento
            if not current_status or "..." in current_status or "Estrazione" in current_status or "Attendere" in current_status:
                 self._info("Nessun risultato trovato o operazione annullata.")
                 # Non cancellare il messaggio se è un errore specifico da _handle_search_error
                 if "Errore" not in current_status:
                     self.query_lbl.setText("") # Clear status only if it was informational
            return

        # Aggiungi le tracce valide alla playlist
        start_index_of_new_tracks = len(self.playlist)
        self.add_tracks_to_playlist_signal.emit(tracks) # Usa il segnale per l'aggiunta

        # Verifica se sono state effettivamente aggiunte tracce
        tracks_were_added = len(self.playlist) > start_index_of_new_tracks

        # Decide se avviare la riproduzione automatica
        # Controlla lo stato del player *prima* di emettere il segnale play_track
        is_player_playing = self.player and self.player.is_playing()

        if not is_player_playing and tracks_were_added:
             actual_play_index = start_index_of_new_tracks # L'indice della prima traccia aggiunta
             print(f"Player non in riproduzione, avvio primo risultato aggiunto all'indice: {actual_play_index}")
             # Emetti il segnale per avviare la riproduzione
             self.play_track_signal.emit(actual_play_index)
             # Aggiorna l'etichetta di stato
             first_track_title = self.playlist[actual_play_index].title[:50] # Usa il titolo dalla playlist
             status_msg = f"Riproducendo: {first_track_title}..."
             added_count = len(self.playlist) - start_index_of_new_tracks
             if added_count > 1: status_msg += f" (+{added_count-1} in coda)"
             if self.playlist[actual_play_index].is_local: status_msg += " (Scaricato)"
             self.query_lbl.setText(status_msg)
        elif tracks_were_added:
             # Player già in riproduzione O nessuna traccia aggiunta (caso gestito sopra)
             added_count = len(self.playlist) - start_index_of_new_tracks
             print(f"Player in riproduzione, aggiunti {added_count} brani in coda.")
             status_msg = f"Aggiunti {added_count} brani in coda."
             # Controlla se almeno uno dei brani *appena aggiunti* è locale
             newly_added_tracks = self.playlist[start_index_of_new_tracks:]
             if any(t.is_local for t in newly_added_tracks): status_msg += " (Alcuni scaricati)"
             self.query_lbl.setText(status_msg)
        # else: # Caso in cui tracks non era vuoto ma nessuna traccia è stata aggiunta (improbabile)
             # print("Nessuna traccia valida aggiunta alla playlist.")
             # self.query_lbl.setText("") # Clear status

        # !!! NON resettare self.is_searching qui !!!
        # Verrà fatto nello slot _on_search_worker_finished

        # Pulisci la barra di ricerca dopo aver processato i risultati
        self.search_in.clear()
        # Dentro la classe Jukebox in jukebox_gui.py
    def _handle_search_error(self, msg):
        """Handles errors received from the YoutubeSearchWorker."""
        sender_worker = self.sender() # Identifica quale worker ha inviato il segnale

        # Non è più necessario/affidabile confrontare sender_worker con self.yt_search_worker qui.
        # La gestione dello stato in _on_search_worker_finished si occupa della pulizia.
        # Assumiamo che l'errore sia rilevante per l'operazione che era in corso.
        # if sender_worker != self.yt_search_worker:
        #     print(f"Ignoring error from potentially outdated worker {id(sender_worker)}.")
        #     return

        # Stampa l'errore nel terminale per il debug, includendo l'ID del worker
        print(f"Errore ricevuto dal worker {id(sender_worker)}: {msg}")

        # Mostra il messaggio di errore all'utente tramite una QMessageBox
        self._error(msg)

        # Aggiorna l'etichetta di stato per indicare che si è verificato un errore
        self.query_lbl.setText("Errore nella ricerca/download.")

        # !!! NON resettare self.is_searching qui !!!
        # Verrà fatto nello slot _on_search_worker_finished quando il worker
        # (che ha generato l'errore) emetterà il segnale 'finished'.
    # Inserisci questo metodo dentro la classe Jukebox in jukebox_gui.py
    # Dentro la classe Jukebox in jukebox_gui.py

    def _on_cover_worker_finished(self):
        """Slot chiamato quando CoverDownloadWorker emette il segnale finished."""
        sender_worker = self.sender()
        if sender_worker:
            print(f"Jukebox: _on_cover_worker_finished chiamato per worker {id(sender_worker)}.")
            # Programma la cancellazione per il worker che ha finito
            sender_worker.deleteLater()
            # Se self.cover_worker punta ancora a questo worker finito,
            # resetta il riferimento nella classe Jukebox.
            if self.cover_worker is sender_worker:
                print("Jukebox: Resettato riferimento self.cover_worker.")
                self.cover_worker = None
        else:
             print("Jukebox: _on_cover_worker_finished - sender (worker) non trovato.")
    def _on_search_worker_finished(self):
        """Slot chiamato quando YoutubeSearchWorker emette il segnale finished."""
        print("Jukebox: _on_search_worker_finished chiamato.")
        self.is_searching = False # Resetta lo stato di ricerca
        self._hide_loading() # Nascondi l'indicatore di caricamento

        # Ora è sicuro programmare la cancellazione del worker che ha finito
        sender_worker = self.sender()
        if sender_worker:
            # Controlla se il worker che ha finito è ancora quello a cui
            # fa riferimento self.yt_search_worker (potrebbe essere stato
            # sovrascritto da una ricerca rapidissima successiva).
            # Tuttavia, dovremmo comunque cancellare il worker che ha *emesso* il segnale.
            print(f"Jukebox: Scheduling deletion for worker {id(sender_worker)} che ha finito.")
            sender_worker.deleteLater()

            # Se il riferimento principale punta ancora a questo worker, resettalo.
            if self.yt_search_worker is sender_worker:
                 self.yt_search_worker = None
                 print("Jukebox: Riferimento self.yt_search_worker resettato.")
        else:
            print("Jukebox: _on_search_worker_finished - sender (worker) non trovato.")

        # Aggiorna l'etichetta di stato se mostra ancora un messaggio di caricamento/attesa
        current_status = self.query_lbl.text()
        if "..." in current_status or "Attendere" in current_status or "Estrazione" in current_status or "Caricamento" in current_status :
             # Solo cancella se non è un messaggio di errore specifico
             if "Errore" not in current_status:
                 self.query_lbl.setText("")
    def _import_files(self):
        """Opens a file dialog to import local audio files."""
        if self.vkbd.isVisible():
             self.vkbd.hide_keyboard()

        # Define supported extensions string for the dialog filter
        audio_filter = f"Audio Files (*{' *'.join(sorted(AUDIO_EXTS))});;All Files (*)"
        # Start dialog in user's Music directory or Home directory
        start_dir = str(Path.home() / "Music")
        if not Path(start_dir).exists():
             start_dir = str(Path.home())

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Seleziona file audio locali", start_dir, audio_filter
        )

        if not paths: # User cancelled
            return

        # --- Cancel previous probe workers (optional but good practice) ---
        active_probes = False
        for worker in self.probe_workers:
             if worker and worker.isRunning():
                  print(f"Annullamento probe precedente per: {worker.path}")
                  worker.cancel() # Signal cancellation
                  active_probes = True
        if active_probes:
             print("Attendendo brevemente la terminazione dei probe precedenti...")
             # time.sleep(0.1) # Brief pause (optional)
        self.probe_workers.clear() # Clear the list of workers

        # --- Process selected files ---
        imported_tracks = []
        needs_probe = []
        for p_str in paths:
             try:
                 p_path = Path(p_str)
                 # Basic validation: is file and has supported extension
                 if p_path.is_file() and p_path.suffix.lower() in AUDIO_EXTS:
                      title = p_path.stem # Use filename without extension as title
                      resolved_path_str = str(p_path.resolve()) # Use absolute path
                      # Create track object, duration initially unknown (0)
                      track = Track(url=resolved_path_str, title=title, is_local=True, duration_sec=0, webpage_url=resolved_path_str)
                      imported_tracks.append(track)
                      needs_probe.append(track) # Add to list for duration probing
                 else:
                      print(f"File ignorato (non valido o estensione non supportata): {p_str}")
             except Exception as e:
                  print(f"Errore processando il file {p_str}: {e}")

        if not imported_tracks:
             self._info("Nessun file audio valido selezionato o processato.")
             return

        # Add imported tracks to the main playlist
        start_index_of_imported = len(self.playlist)
        self.add_tracks_to_playlist_signal.emit(imported_tracks) # Use signal

        # --- Start background duration probing ---
        if needs_probe:
             print(f"Avvio probe per la durata di {len(needs_probe)} file importati...")
             self.query_lbl.setText(f"Analisi durata {len(needs_probe)} file...")
             for track_to_probe in needs_probe:
                 probe_worker = FileProbeWorker(track_to_probe.url) # Pass the path
                 probe_worker.probe_done.connect(self.update_probe_duration_signal)
                 probe_worker.finished.connect(probe_worker.deleteLater)
                 self.probe_workers.append(probe_worker) # Keep track
                 probe_worker.start()
        else:
             self.query_lbl.setText(f"Importati {len(imported_tracks)} file.")


        # Auto-play the first imported track if the player was idle
        is_player_playing = self.player and self.player.is_playing()
        if not is_player_playing and len(self.playlist) > start_index_of_imported:
            print(f"Player non in riproduzione, avvio primo brano importato all'indice: {start_index_of_imported}")
            self.play_track_signal.emit(start_index_of_imported)


    def _handle_probe_done(self, path, duration_ms):
        """Updates the duration of a track after FileProbeWorker finishes."""
        duration_sec = duration_ms // 1000 if duration_ms is not None and duration_ms > 0 else 0
        print(f"Probe completato per {Path(path).name}: {duration_sec}s")

        updated = False
        track_index = -1
        # Find the track in the playlist by its path (URL)
        for i, track in enumerate(self.playlist):
            # Compare resolved paths for robustness
            try:
                 if track.is_local and Path(track.url).resolve() == Path(path).resolve():
                      if track.duration_sec != duration_sec:
                          track.duration_sec = duration_sec
                          updated = True
                          track_index = i
                          print(f"Durata aggiornata per: {track.title}")
                      break # Found the track
            except Exception as e:
                 print(f"Errore comparando path durante probe update: {e}")


        if updated:
            # Refresh UI list if duration changed
            self._refresh_lists()
            # Save updated playlist immediately (optional, could save on close)
            # save_json("playlist.json", self.playlist)

            # If the currently playing track's duration was updated, refresh the info label/slider max
            if track_index == self.current_idx:
                 self._update_info_label(self.playlist[track_index])

        # Remove worker reference (optional, as it deletes itself)
        self.probe_workers = [w for w in self.probe_workers if w.path != path and w.isRunning()]

        # Check if all probes are done
        if not any(w.isRunning() for w in self.probe_workers):
             if "Analisi durata" in self.query_lbl.text():
                  self.query_lbl.setText("Analisi durata completata.")
                  # Clear message after a delay
                  QTimer.singleShot(2000, lambda: self.query_lbl.setText("") if "Analisi durata completata" in self.query_lbl.text() else None)


    # --- Playback Logic ---
    def _play_current_index(self, index):
        """Starts or resumes playback of the track at the given playlist index."""
        # --- Validate Index ---
        if not (0 <= index < len(self.playlist)):
            print(f"Errore: Tentativo di riprodurre indice non valido: {index}. Playlist size: {len(self.playlist)}")
            self.player.stop() # Stop playback if index is invalid
            self.current_idx = -1
            self._clear_media_info()
            self._refresh_lists() # Update UI to show no selection
            return

        # --- Get Track and Check for Resume ---
        track_to_play = self.playlist[index]
        print(f"Richiesta riproduzione indice {index}: '{track_to_play.title}' ({'Locale' if track_to_play.is_local else 'Stream'})")

        # If clicking the *same* track which is currently *paused*, just resume.
        if index == self.current_idx and self.player and self.player.get_state() == vlc.State.Paused:
             print("Ripresa riproduzione.")
             self.player.play()
             # No need to set media again, just update UI state
             self.is_playing = True
             self._update_play_pause_button()
             self._refresh_lists() # Ensure highlight is correct
             return

        # --- Stop Previous Playback (if any) ---
        # Necessary before setting new media, especially for streams
        if self.player.is_playing() or self.player.get_state() == vlc.State.Paused:
            print("Stop player precedente...")
            self.player.stop()
            # Short pause might help VLC release resources before new media
            # time.sleep(0.05) # Usually not necessary with stop()

        # --- Prepare New Media ---
        self.current_idx = index
        self.current_track_info = track_to_play # Store current track info

        media_source = track_to_play.url
        if not media_source: # Sanity check: Track must have a URL/path
             error_msg = f"URL/Percorso non valido per '{track_to_play.title}'. Impossibile riprodurre."
             print(f"FATAL: {error_msg}")
             self.playback_error_signal.emit(error_msg) # Signal error
             return # Cannot proceed

        try:
            media = None
            options = [] # VLC media options

            if track_to_play.is_local:
                 # Local file playback
                 source_path = Path(media_source)
                 if not source_path.exists():
                      raise FileNotFoundError(f"File locale non trovato: {media_source}")
                 # Use media_new_path for local files (often more reliable)
                 media = vlc_instance.media_new_path(str(source_path))
                 print(f"Creazione media locale da: {source_path}")
            else:
                 # Stream playback (YouTube, SoundCloud, etc.)
                 if not str(media_source).lower().startswith(('http', 'rtsp', 'rtmp')):
                     # Basic check for valid streaming protocols
                     raise ValueError(f"Formato URL non supportato per lo streaming: {media_source}")

                 # Add options for network streams (adjust caching values as needed)
                 options = [
                     '--no-video-title-show', # Don't show URL as window title if video present
                     ':network-caching=3000', # Network buffer size (ms)
                     ':sout-keep', # Keep stream open (might help some streams)
                     # ':file-caching=1000' # File cache (less relevant for streams)
                 ]
                 media = vlc_instance.media_new(media_source, *options)
                 print(f"Creazione media stream da: {media_source} con opzioni: {options}")

            if media is None:
                 raise ValueError(f"Impossibile creare oggetto media VLC da: {media_source}")

            # --- Set Media and Start Playback ---
            self.player.set_media(media)
            # Release the media object *after* setting it in the player
            # The player now holds its own reference.
            media.release()

            # Set initial volume (might be redundant if volume unchanged, but safe)
            self._set_volume(self.vol.value())

            print("Avvio riproduzione...")
            if self.player.play() == -1:
                 # Playback failed to start
                 raise RuntimeError("Errore VLC: player.play() ha restituito -1. Impossibile avviare la riproduzione.")

            # --- Update UI ---
            print("Riproduzione avviata con successo.")
            self._update_info_label(track_to_play) # Show title/duration
            self._set_cover(track_to_play.thumbnail_url) # Load cover art
            self._refresh_lists() # Update list highlighting

            # --- Add to History ---
            # Emit signal to add to history (handled by _add_to_history slot)
            self.add_to_history_signal.emit(track_to_play)

        # --- Error Handling ---
        except FileNotFoundError as e:
             error_msg = f"Errore: File non trovato '{track_to_play.title}'. Potrebbe essere stato spostato o cancellato.\n({e})"
             print(error_msg)
             self.playback_error_signal.emit(error_msg) # Signal error
        except ValueError as e: # Catches invalid URL format etc.
             error_msg = f"Errore: Sorgente media non valida per '{track_to_play.title}'.\n({e})"
             print(error_msg)
             self.playback_error_signal.emit(error_msg) # Signal error
        except Exception as e: # Catch-all for other VLC or unexpected errors
             import traceback
             error_msg = f"Errore imprevisto durante l'avvio della riproduzione per '{track_to_play.title}'.\n({e})"
             print(f"{error_msg}\n{traceback.format_exc()}")
             self.playback_error_signal.emit(error_msg) # Signal error


    def _update_info_label(self, track):
        """Updates the title and duration labels for the current track."""
        if track:
             # Get duration, handle None or 0
             duration_sec = track.duration_sec if track.duration_sec is not None and track.duration_sec > 0 else 0
             # Format duration string ("--:--" if unknown)
             dur_str = self._fmt_time(duration_sec * 1000) if duration_sec > 0 else "--:--"
             # Prepare title (limit length if necessary)
             title_display = track.title if len(track.title) < 70 else track.title[:67] + "..."
             # Set the label text
             self.info_lbl.setText(f"<b>Titolo:</b> {title_display}\n<b>Durata:</b> {dur_str}")
             # Update progress bar maximum based on duration
             if self.progress.maximum() != duration_sec:
                  self.progress.setMaximum(duration_sec)
             self.progress.setEnabled(duration_sec > 0) # Enable slider only if duration known
             # Reset progress value and time label for the new track
             self.progress.setValue(0)
             self.time_lbl.setText(f"00:00 / {dur_str}")
        else:
             # No track provided, clear the info
             self._clear_media_info()

    def _clear_media_info(self):
         """Clears the media information display (title, duration, cover)."""
         self.info_lbl.setText("<b>Titolo:</b> -\n<b>Durata:</b> -")
         self.set_default_cover() # Reset to default cover
         # Reset progress bar and time label
         if self.progress.value() != 0: self.progress.setValue(0)
         if self.progress.maximum() != 0: self.progress.setMaximum(0)
         self.progress.setEnabled(False)
         self.time_lbl.setText("00:00 / 00:00")
         # Clear current track reference
         self.current_track_info = None
         # Optionally clear status label
         # self.query_lbl.setText("")


    def toggle_play(self):
        """Toggles playback between Play and Pause states."""
        if not self.player: return # Safety check

        state = self.player.get_state()

        if state == vlc.State.Playing:
            self.player.pause()
            print("Player Paused.")
        elif state == vlc.State.Paused:
            self.player.play()
            print("Player Resumed.")
        elif state in (vlc.State.Stopped, vlc.State.Ended, vlc.State.Error, vlc.State.NothingSpecial):
             # If stopped/ended, try to play the current track again, or the first track
             if 0 <= self.current_idx < len(self.playlist):
                 print(f"Player stopped/ended. Replaying track index {self.current_idx}.")
                 self.play_track_signal.emit(self.current_idx) # Use signal
             elif self.playlist: # If playlist not empty, play first track
                 print("Player stopped/ended. Playing first track.")
                 self.play_track_signal.emit(0) # Use signal
             else:
                 print("Player stopped/ended. Playlist empty.")
                 self._clear_media_info() # Clear display if nothing to play
                 # Ensure button shows "Play"
                 self.is_playing = False
                 self._update_play_pause_button()

    def _update_play_pause_button(self):
        """Updates the Play/Pause button text based on the is_playing state."""
        if self.is_playing:
            self.play_pause_btn.setText("Pausa")
            self.play_pause_btn.setToolTip("Metti in pausa (Spazio)")
        else:
            self.play_pause_btn.setText("Play")
            self.play_pause_btn.setToolTip("Riproduci (Spazio)")


    def play_next(self):
        """Plays the next track in the playlist."""
        if not self.playlist: # No tracks, do nothing
            print("Play Next: Playlist vuota.")
            return

        current = self.current_idx
        total_tracks = len(self.playlist)

        if current == -1: # If nothing is playing, play the first track
             next_idx = 0
        else:
             next_idx = current + 1

        if next_idx >= total_tracks:
            # Reached end of playlist
            print("Fine della playlist.")
            # Option 1: Stop playback
            self.player.stop()
            self.current_idx = -1
            self._clear_media_info()
            self._refresh_lists() # Update UI to show no selection
            # Option 2: Loop back to the first track (uncomment to enable loop)
            # print("Looping alla prima traccia.")
            # next_idx = 0
            # self.play_track_signal.emit(next_idx)
        else:
            # Play the calculated next index
            self.play_track_signal.emit(next_idx)


    def play_previous(self):
        """Plays the previous track in the playlist."""
        if not self.playlist: # No tracks, do nothing
            print("Play Previous: Playlist vuota.")
            return

        current = self.current_idx
        total_tracks = len(self.playlist)

        if current <= 0: # Already at the first track or nothing playing
            print("Inizio della playlist.")
            # Option 1: Do nothing or restart the first track
            if total_tracks > 0:
                 print("Riavvio prima traccia.")
                 self.play_track_signal.emit(0) # Restart first track
            # Option 2: Loop to the last track (uncomment to enable loop)
            # print("Looping all'ultima traccia.")
            # prev_idx = total_tracks - 1
            # self.play_track_signal.emit(prev_idx)
        else:
            # Play the calculated previous index
            prev_idx = current - 1
            self.play_track_signal.emit(prev_idx)


    # --- Playlist, History, Favorites Management ---
    def _add_tracks_to_playlist(self, tracks):
        """Adds a list of Track objects to the internal playlist."""
        if not tracks: return

        added_count = 0
        # Optional: Prevent duplicates based on URL/webpage_url?
        # existing_ids = {t.webpage_url or t.url for t in self.playlist}
        for track in tracks:
             if isinstance(track, Track) and (track.url or track.webpage_url):
                 # if (track.webpage_url or track.url) not in existing_ids:
                 self.playlist.append(track)
                 added_count += 1
                 # else:
                 #    print(f"Skipping duplicate track: {track.title}")
             else:
                 print(f"Avviso: Tentativo di aggiungere oggetto non valido alla playlist: {track}")

        if added_count > 0:
            print(f"Aggiunti {added_count} brani alla playlist.")
            save_json("playlist.json", self.playlist) # Save updated playlist
            self._refresh_lists() # Update UI
        else:
             print("Nessun brano valido da aggiungere alla playlist.")


    def _queue_double_clicked(self, item):
        """Handles double-click on a playlist item to play it."""
        clicked_idx = self.queue.row(item)
        if 0 <= clicked_idx < len(self.playlist):
            self.play_track_signal.emit(clicked_idx) # Signal to play this index
        else:
             print(f"Warning: Double click su indice playlist non valido: {clicked_idx}")


    def _add_to_history(self, track):
        """Adds a played track to the history list (avoiding duplicates)."""
        if not isinstance(track, Track):
             print(f"Avviso: _add_to_history chiamato con oggetto non Track: {track}")
             return

        # Use webpage_url as primary identifier (e.g., YouTube page URL)
        # Fallback to the stream/file URL if webpage_url is missing
        identifier_to_add = track.webpage_url or track.url
        if not identifier_to_add:
             print(f"Avviso: Impossibile aggiungere '{track.title}' alla cronologia (nessun identificatore).")
             return # Cannot add if no identifier

        # --- Remove existing entry with the same identifier ---
        # Iterate backwards to safely remove while iterating
        # Or create a new list excluding the item
        new_history = []
        found = False
        for h_track in self.history:
             h_identifier = h_track.webpage_url or h_track.url
             if h_identifier == identifier_to_add:
                  # Don't add this one to the new list (effectively removing it)
                  found = True
                  print(f"Rimuovendo vecchia entry '{h_track.title}' dalla cronologia.")
             else:
                  new_history.append(h_track)
        self.history = new_history

        # --- Add the new entry to the beginning ---
        # Create a clean copy of the track for history
        history_track = Track(
            track.url, track.title, track.thumbnail_url,
            track.duration_sec, track.is_local, track.webpage_url
        )
        self.history.insert(0, history_track)

        # --- Limit History Size ---
        if len(self.history) > MAX_HISTORY_SIZE:
            self.history = self.history[:MAX_HISTORY_SIZE] # Keep only the most recent items

        # --- Save and Refresh ---
        save_json("history.json", self.history)
        self._refresh_lists() # Update history list display
        print(f"Aggiunto '{history_track.title}' alla cronologia.")


    def _history_double_clicked(self, item):
        """Handles double-click on a history item to add it to the playlist queue."""
        # Retrieve the identifier stored in the item's data
        track_identifier = item.data(Qt.UserRole)
        if not track_identifier:
             print("Warning: Identificatore non trovato nell'elemento della cronologia.")
             self._error("Dati brano cronologia corrotti o mancanti.")
             return

        # Find the corresponding Track object in the self.history list
        track_to_add = None
        for h_track in self.history:
             h_identifier = h_track.webpage_url or h_track.url
             if h_identifier == track_identifier:
                  track_to_add = h_track
                  break

        if not track_to_add:
             print(f"Warning: Traccia non trovata nei dati della cronologia per l'identificatore: {track_identifier}")
             self._error("Brano della cronologia non trovato nei dati salvati.")
             # Optionally refresh list in case of discrepancy: self._refresh_lists()
             return

        # Create a new Track instance to add to the playlist
        # (Avoids modifying the instance stored in history directly if needed)
        new_track = Track(
            track_to_add.url,
            track_to_add.title,
            track_to_add.thumbnail_url,
            track_to_add.duration_sec,
            track_to_add.is_local,
            track_to_add.webpage_url
        )

        # Add the selected track to the end of the playlist
        self.add_tracks_to_playlist_signal.emit([new_track]) # Use signal

        # Decide whether to play it
        is_player_playing = self.player and self.player.is_playing()
        new_index = len(self.playlist) - 1 # Index of the newly added track

        if not is_player_playing:
             print(f"Player non in riproduzione, avvio brano aggiunto dalla cronologia ({new_track.title})")
             self.play_track_signal.emit(new_index) # Play the added track
             self.query_lbl.setText(f"Riproducendo da Cronologia: {new_track.title[:50]}...")
        else:
             print(f"Player in riproduzione, brano aggiunto dalla cronologia in coda.")
             self.query_lbl.setText(f"Aggiunto da Cronologia in coda: {new_track.title[:50]}...")


    def _refresh_lists(self):
        """Updates both the playlist (queue) and history list widgets."""
        # --- Refresh Playlist (Queue) ---
        current_playlist_index = self.current_idx # Store current index before clearing
        self.queue.clear() # Remove all items
        for i, track in enumerate(self.playlist):
            # Format duration string
            duration_str = ""
            if track.duration_sec is not None and track.duration_sec > 0:
                 duration_str = f" ({self._fmt_time(track.duration_sec * 1000)})"
            # Format title with local indicator if needed
            prefix = "[L] " if track.is_local else ""
            item_text = f"{prefix}{track.title}{duration_str}"

            item = QListWidgetItem(item_text)
            # Set tooltip with more info (e.g., full title or URL)
            tooltip_text = f"Titolo: {track.title}\n"
            tooltip_text += f"URL/Path: {track.url}\n"
            if track.webpage_url and track.webpage_url != track.url:
                 tooltip_text += f"Pagina Web: {track.webpage_url}\n"
            tooltip_text += f"Locale: {'Sì' if track.is_local else 'No'}"
            item.setToolTip(tooltip_text)

            # Highlight the currently playing/selected item
            if i == current_playlist_index:
                # Use selection colors defined in stylesheet
                item.setSelected(True)
                # Optionally set custom background/foreground here if needed
                # item.setBackground(QColor("#0078d7")) # Example direct color
                # item.setForeground(QColor(Qt.white))

            self.queue.addItem(item)

        # Scroll to ensure the current item is visible after refresh
        if 0 <= current_playlist_index < self.queue.count():
            self.queue.scrollToItem(self.queue.item(current_playlist_index), QListWidget.EnsureVisible)

        # --- Refresh History List ---
        self.history_list.clear()
        for track in self.history:
            # Format duration string
            duration_str = ""
            if track.duration_sec is not None and track.duration_sec > 0:
                 duration_str = f" ({self._fmt_time(track.duration_sec * 1000)})"
             # Format title with local indicator
            prefix = "[L] " if track.is_local else ""
            item_text = f"{prefix}{track.title}{duration_str}"

            item = QListWidgetItem(item_text)
            # Store the track identifier (webpage_url or url) in the item's data role
            # This is used in _history_double_clicked to find the track
            identifier = track.webpage_url or track.url
            item.setData(Qt.UserRole, identifier)
            # Set tooltip
            tooltip_text = f"Titolo: {track.title}\n"
            tooltip_text += f"ID: {identifier}\n"
            tooltip_text += f"Locale: {'Sì' if track.is_local else 'No'}"
            item.setToolTip(tooltip_text)

            self.history_list.addItem(item)


    def add_to_favorites(self):
        """Adds the currently playing track to the favorites list."""
        if self.current_track_info is None:
             self._info("Nessun brano attualmente selezionato da aggiungere ai preferiti.")
             return

        track_to_add = self.current_track_info

        # Use webpage_url or url as the unique identifier
        identifier = track_to_add.webpage_url or track_to_add.url
        if not identifier:
             self._error(f"Impossibile aggiungere '{track_to_add.title}' ai preferiti: URL/identificatore non disponibile.")
             return

        # Check if already in favorites using the identifier
        if any((fav.webpage_url or fav.url) == identifier for fav in self.favorites):
            self._info(f"'{track_to_add.title}' è già nei preferiti.")
            return

        # Create a copy to add to favorites
        fav_track = Track(
            track_to_add.url,
            track_to_add.title,
            track_to_add.thumbnail_url,
            track_to_add.duration_sec,
            track_to_add.is_local,
            track_to_add.webpage_url
        )

        self.favorites.append(fav_track)
        save_json("favorites.json", self.favorites) # Save updated favorites
        self._info(f"'{fav_track.title}' aggiunto ai preferiti!")


    def show_favorites(self):
        """Shows a dialog to select a favorite track to add to the queue."""
        if not self.favorites:
            self._info("La lista dei preferiti è vuota.")
            return

        # --- Prepare items for the dialog ---
        # Use display text that includes "[L]" for local files
        # Store mapping from display text back to the Track object
        favorite_display_items = []
        display_to_track_map = {} # Maps the unique display string back to the Track object

        for i, fav_track in enumerate(self.favorites):
             prefix = "[L] " if fav_track.is_local else ""
             base_display_text = f"{prefix}{fav_track.title}"
             display_text = base_display_text

             # Handle potential duplicate display names (e.g., same title, one local one stream)
             counter = 2
             while display_text in display_to_track_map:
                  display_text = f"{base_display_text} ({counter})"
                  counter += 1

             favorite_display_items.append(display_text)
             display_to_track_map[display_text] = fav_track # Store mapping

        if not favorite_display_items: # Should not happen if self.favorites is not empty
             self._error("Errore interno: impossibile generare la lista dei preferiti.")
             return

        # --- Show Input Dialog ---
        # QInputDialog.getItem provides a dropdown list
        choice_text, ok = QInputDialog.getItem(self,
                                               "Preferiti", # Dialog Title
                                               "Seleziona un brano preferito da aggiungere alla coda:", # Prompt Label
                                               favorite_display_items, # List of strings to display
                                               0, # Default selected index
                                               False) # Editable flag (False for non-editable dropdown)

        # --- Handle Selection ---
        if ok and choice_text: # User selected an item and clicked OK
            selected_fav = display_to_track_map.get(choice_text)

            if selected_fav:
                print(f"Preferito selezionato: {selected_fav.title}")

                # Create a new Track instance to add to the playlist
                new_track = Track(
                    selected_fav.url,
                    selected_fav.title,
                    selected_fav.thumbnail_url,
                    selected_fav.duration_sec,
                    selected_fav.is_local,
                    selected_fav.webpage_url
                )

                # Add to playlist
                self.add_tracks_to_playlist_signal.emit([new_track])

                # Decide whether to play
                is_player_playing = self.player and self.player.is_playing()
                new_index = len(self.playlist) - 1

                if not is_player_playing:
                     print(f"Player non in riproduzione, avvio brano aggiunto dai preferiti ({new_track.title})")
                     self.play_track_signal.emit(new_index)
                     self.query_lbl.setText(f"Riproducendo da Preferiti: {new_track.title[:50]}...")
                else:
                     print(f"Player in riproduzione, brano aggiunto dai preferiti in coda.")
                     self.query_lbl.setText(f"Aggiunto da Preferiti in coda: {new_track.title[:50]}...")

            else:
                 # This should not happen if the map is correct
                 self._error("Errore interno: Brano preferito non trovato dopo la selezione.")


    # --- Cover Art Handling ---
        # Dentro la classe Jukebox in jukebox_gui.py
    def _set_cover(self, thumbnail_url):
        """Loads cover from cache or starts asynchronous download."""

        # --- Cancel Previous Cover Worker (if any) ---
        # Usa una variabile temporanea e un try-except per sicurezza
        worker_to_cancel = self.cover_worker
        if worker_to_cancel is not None: # Controlla se il riferimento esiste
            try:
                # Controlla se è ancora in esecuzione prima di annullare
                if worker_to_cancel.isRunning():
                    print(f"Annullamento download copertina precedente (worker {id(worker_to_cancel)})...")
                    worker_to_cancel.cancel()
                # Non resettare self.cover_worker qui, verrà gestito dallo slot _on_cover_worker_finished
                # quando il worker annullato effettivamente termina.
            except RuntimeError:
                # L'oggetto C++ potrebbe essere già stato cancellato, ignora l'errore
                print(f"Warning: Impossibile accedere/annullare worker copertina precedente {id(worker_to_cancel)} (potrebbe essere stato eliminato).")
                # Se il riferimento self.cover_worker puntava ancora all'oggetto eliminato,
                # è prudente resettarlo ora, anche se _on_cover_worker_finished dovrebbe farlo.
                if self.cover_worker is worker_to_cancel:
                    self.cover_worker = None

        # --- Reset to Default Cover ---
        # Fallo subito per mostrare un placeholder mentre si carica la nuova copertina
        self.set_default_cover()

        # --- Validate URL ---
        if not thumbnail_url or not str(thumbnail_url).startswith("http"):
            # print(f"URL copertina non valido o assente: {thumbnail_url}") # Debug
            return # Nessun URL valido, rimane la copertina di default

        try:
            # --- Generate Cache Filename & Check Cache ---
            # Usa MD5 dell'URL per un nome file univoco e sicuro
            filename_hash = hashlib.md5(thumbnail_url.encode('utf-8')).hexdigest()
            cache_filename = f"{filename_hash}.jpg" # Assumi JPEG (o usa un'estensione più generica)
            local_cache_path = COVER_DIR / cache_filename

            if local_cache_path.exists():
                # print(f"Tentativo caricamento copertina dalla cache: {local_cache_path.name}") # Debug
                pix = QPixmap(str(local_cache_path))
                if not pix.isNull():
                    # Cache hit e immagine valida caricata con successo
                    # print("Cache hit, copertina caricata.") # Debug
                    self._handle_cover_ready(pix)
                    return # Fatto, esci dal metodo
                else:
                    # Il file cache esiste ma è corrotto o illeggibile
                    print(f"Errore caricamento file cache copertina: {local_cache_path.name}. Rimuovo e tento il download.")
                    try:
                        local_cache_path.unlink() # Cancella il file corrotto
                    except OSError as e:
                        print(f"Impossibile cancellare file cache corrotto {local_cache_path.name}: {e}")

            # --- Cache Miss or Invalid Cache: Start Download ---
            # print(f"Cache miss per copertina {thumbnail_url}. Avvio download...") # Debug

            # Crea e assegna il NUOVO worker a self.cover_worker
            # Sovrascrive il riferimento precedente (che dovrebbe essere None o puntare
            # a un worker già annullato/finito).
            self.cover_worker = CoverDownloadWorker(thumbnail_url, local_cache_path)
            print(f"Creato nuovo CoverDownloadWorker {id(self.cover_worker)} per {thumbnail_url[:50]}...")

            # Connetti i segnali del nuovo worker
            self.cover_worker.cover_ready.connect(self._handle_downloaded_cover_ready)
            self.cover_worker.cover_error.connect(self._handle_cover_error)
            # Connetti finished allo SLOT DEDICATO per la pulizia
            self.cover_worker.finished.connect(self._on_cover_worker_finished)

            # !!! Riga importante: NON collegare finished a deleteLater qui !!!

            # Avvia il download in background
            self.cover_worker.start()

        except Exception as e:
             # Cattura errori durante hashing, manipolazione path, o creazione worker
             import traceback
             print(f"Errore nella logica di caching/download copertina per URL {thumbnail_url}: {e}\n{traceback.format_exc()}")
             self.set_default_cover() # Assicura che venga mostrata la copertina di default in caso di errore
        # Dentro la classe Jukebox in jukebox_gui.py

    def _handle_downloaded_cover_ready(self, file_path_str):
        """Handles the signal when a cover has been successfully downloaded and saved."""
        # Identifica il worker che ha inviato il segnale (utile per il logging)
        sender_worker = self.sender()
        worker_id = id(sender_worker) if sender_worker else "Unknown"

        # --- Rimuoviamo il controllo sul worker corrente ---
        # Non è più necessario/affidabile confrontare con self.cover_worker qui.
        # Se un segnale arriva, lo processiamo assumendo che sia rilevante
        # per l'operazione che quel worker stava eseguendo.

        print(f"Cover scaricata e salvata in: {file_path_str} (da worker {worker_id})")

        # Carica il file immagine scaricato in una QPixmap
        pix = QPixmap(file_path_str)

        if not pix.isNull():
             # Immagine caricata con successo, chiamiamo l'handler comune per visualizzarla
             self._handle_cover_ready(pix)
        else:
             # Il file è stato salvato ma non può essere caricato come QPixmap
             # (potrebbe essere corrotto, o un formato immagine non supportato da Qt in questo contesto).
             print(f"Errore caricamento QPixmap dalla cover scaricata: {file_path_str}")
             self.set_default_cover() # Ripristina la copertina di default

             # Opzionale ma consigliato: cancella il file potenzialmente corrotto
             try:
                 Path(file_path_str).unlink()
                 print(f"File cover corrotto/illeggibile cancellato: {file_path_str}")
             except OSError as e:
                 print(f"Impossibile cancellare file cover scaricato ({file_path_str}): {e}")


    def _handle_cover_error(self):
        """Handles the signal when cover download/processing fails."""
        # Identifica il worker che ha inviato il segnale (utile per il logging)
        sender_worker = self.sender()
        worker_id = id(sender_worker) if sender_worker else "Unknown"

        # --- Rimuoviamo il controllo sul worker corrente ---
        # L'errore è rilevante per l'operazione che il worker specifico stava tentando.

        print(f"Errore durante il download della copertina (da worker {worker_id}).")

        # Non c'è bisogno di chiamare self.set_default_cover() qui,
        # perché la copertina di default dovrebbe essere già stata impostata
        # all'inizio di _set_cover() prima di avviare il download.ver() here, as it should already be showing
        # self.set_default_cover()


    def _handle_cover_ready(self, pixmap):
        """Displays the loaded QPixmap in the cover label."""
        if self.cover_lbl and not pixmap.isNull():
            # Scale pixmap to fit the label while keeping aspect ratio
            scaled_pixmap = pixmap.scaled(
                self.cover_lbl.size(), # Target size is the label's size
                Qt.KeepAspectRatio,    # Maintain aspect ratio
                Qt.SmoothTransformation # Use high-quality scaling
            )
            self.cover_lbl.setPixmap(scaled_pixmap)
            self.cover_lbl.setText("") # Clear any "No Cover" text
        else:
             # If pixmap is null or label doesn't exist, ensure default
             self.set_default_cover()


    def set_default_cover(self):
        """Sets the cover label to the default placeholder image."""
        if self.cover_lbl:
             # Load default cover pixmap (ensure DEFAULT_COVER path is correct)
             default_pixmap = QPixmap(str(DEFAULT_COVER))
             if not default_pixmap.isNull():
                 # Scale and set the default pixmap
                 scaled_default = default_pixmap.scaled(
                     self.cover_lbl.size(),
                     Qt.KeepAspectRatio,
                     Qt.SmoothTransformation
                 )
                 self.cover_lbl.setPixmap(scaled_default)
                 self.cover_lbl.setText("") # Clear text
             else:
                 # If default image file is missing or invalid
                 print(f"Warning: Default cover file non trovato o non valido: {DEFAULT_COVER}")
                 self.cover_lbl.clear() # Clear any existing pixmap
                 self.cover_lbl.setText("No Cover") # Show text fallback
                 # Apply basic text styling if needed
                 # self.cover_lbl.setStyleSheet("color: #888; border: ...; background: ...;")


    # --- Feedback and Window Management ---
    def _show_loading(self):
        """Shows the loading indicator."""
        if self.loading_movie and self.loading_movie.isValid():
            self.loading_lbl.show()
            if self.loading_movie.state() != QMovie.Running:
                 self.loading_movie.start()
        else:
            # Fallback if GIF is missing
            self.query_lbl.setText("Caricamento...") # Use query label as text indicator

    def _hide_loading(self):
        """Hides the loading indicator."""
        # Check if the signal is from the current worker that finished
        sender_worker = self.sender()
        if sender_worker == self.yt_search_worker:
             if self.loading_movie:
                 self.loading_lbl.hide()
                 # movie.stop() # Optional: stop animation to save resources
             else:
                 # If using text fallback, clear it only if it shows "Caricamento..."
                 if "Caricamento..." in self.query_lbl.text():
                      self.query_lbl.setText("") # Clear text indicator
        # else: # Debug
             # print(f"Ignoro hide_loading da worker non attuale.")


    def _error(self, msg):
        """Shows a critical error message box."""
        QMessageBox.critical(self, "Errore Jukebox", msg)

    def _info(self, msg):
        """Shows an informational message box."""
        QMessageBox.information(self, "Info Jukebox", msg)

    def toggle_fullscreen(self):
        """Toggles the window between fullscreen and normal state."""
        if self.isFullScreen():
            self.showNormal() # Restore previous size/position
            print("Uscita da modalità schermo intero.")
        else:
            self.showFullScreen()
            print("Entrata in modalità schermo intero.")

    # --- Cleanup on Close ---
    def closeEvent(self, event):
        """Handles the window closing event for proper cleanup."""
        print("Chiusura Jukebox in corso...")

        # --- 1. Stop Timers ---
        if hasattr(self, 't') and self.t:
             self.t.stop()
             print("Timer UI fermato.")

        # --- 2. Cancel Running Workers ---
        workers_to_stop = []
        if self.yt_search_worker and self.yt_search_worker.isRunning():
             print("Annullamento worker ricerca YouTube...")
             self.yt_search_worker.cancel()
             workers_to_stop.append(self.yt_search_worker)

        if self.cover_worker and self.cover_worker.isRunning():
             print("Annullamento worker download copertina...")
             self.cover_worker.cancel()
             workers_to_stop.append(self.cover_worker)

        active_probes = [w for w in self.probe_workers if w and w.isRunning()]
        if active_probes:
             print(f"Annullamento {len(active_probes)} worker probe file...")
             for worker in active_probes:
                 worker.cancel()
                 workers_to_stop.append(worker)

        # --- Wait briefly for workers to acknowledge cancellation ---
        if workers_to_stop:
            print("Attendendo brevemente la terminazione dei worker...")
            # Use QThread.wait() for a short period
            deadline = time.time() + 1.0 # Max 1 second wait total
            for worker in workers_to_stop:
                 remaining_time = deadline - time.time()
                 if remaining_time > 0:
                      if not worker.wait(int(remaining_time * 1000)): # wait expects ms
                           print(f"Warning: Worker {type(worker).__name__} non ha terminato entro il timeout.")
                 else:
                      print(f"Warning: Timeout attesa worker {type(worker).__name__}.")
            print("Tentativo di stop worker completato.")


        # --- 3. Stop and Release VLC Player ---
        if self.player:
            print("Stop e rilascio player VLC...")
            try:
                if self.player.is_playing():
                    self.player.stop() # Stop playback first

                # Detach events (optional but good practice)
                if self.event_manager:
                     # Check if methods exist before calling (robustness)
                     if hasattr(self.event_manager, 'event_detach'):
                          try:
                              self.event_manager.event_detach(vlc.EventType.MediaPlayerEndReached)
                              self.event_manager.event_detach(vlc.EventType.MediaPlayerEncounteredError)
                              # Detach other events if attached
                          except Exception as e_detach:
                               print(f"Errore durante detach eventi VLC: {e_detach}")

                # Release the player instance
                self.player.release()
                print("Player VLC rilasciato.")
            except Exception as e_vlc:
                 print(f"Errore durante stop/rilascio player VLC: {e_vlc}")
            self.player = None # Clear reference


        # --- 4. Hide Virtual Keyboard ---
        if self.vkbd.isVisible():
             self.vkbd.hide()

        # --- 5. Save Data ---
        try:
            print("Salvataggio dati (playlist, cronologia, preferiti)...")
            save_json("playlist.json", self.playlist)
            save_json("history.json", self.history)
            save_json("favorites.json", self.favorites)
            print("Dati salvati.")
        except Exception as e_save:
            print(f"Errore durante il salvataggio dei dati JSON: {e_save}")


        # --- 6. Accept Close Event ---
        print("Jukebox chiuso.")
        event.accept() # Allow window to close

    # --- Keyboard Event Handling (for Virtual Keyboard input simulation) ---
    def keyPressEvent(self, event):
         """Handles key presses, potentially forwarding them to the virtual keyboard."""
         # If VKBD is visible AND target is the search input, simulate VKBD input
         if self.vkbd.isVisible() and self.vkbd.target_widget == self.search_in:
              key = event.key()
              text = event.text()

              if key in (Qt.Key_Return, Qt.Key_Enter):
                  # Trigger search on Enter/Return even if VKBD is visible
                  self.search_song()
                  event.accept()
                  return
              elif key == Qt.Key_Backspace:
                  self._vk_input("←") # Simulate VKBD backspace
                  event.accept()
                  return
              elif text and text.isprintable() and len(text) == 1:
                  # Simulate VKBD character input for printable keys
                  self._vk_input(text)
                  event.accept()
                  return
              # Allow other keys (like arrows, Escape) to pass through if needed

         # If VKBD not relevant, pass event to base class for shortcuts etc.
         super().keyPressEvent(event)


# -------------------- Main Execution Block --------------------
if __name__ == "__main__":
    # Set environment variable for Wayland/X11 compatibility if needed (Linux)
    # os.environ.setdefault("QT_QPA_PLATFORM", "xcb") # Example for forcing XCB

    # --- Ensure QApplication Instance ---
    # Use existing instance if available (e.g., in interactive environments)
    # Create a new one otherwise.
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # --- Apply Style ---
    # Optional: Force a specific style like Fusion for consistency
    app.setStyle("Fusion")

    # --- Ensure Data Directories Exist ---
    # These are defined in jukebox_data, but ensure they are created before Jukebox init
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        COVER_DIR.mkdir(parents=True, exist_ok=True)
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
         QMessageBox.critical(None, "Errore Creazione Cartelle Dati",
                              f"Impossibile creare le cartelle necessarie in {DATA_DIR.parent}.\n"
                              f"Verifica i permessi.\n\nDettagli: {e}")
         sys.exit(1)


    # --- Create and Show Main Window ---
    jukebox = None # Initialize to None
    try:
        jukebox = Jukebox()
        # Show maximized or normal based on preference
        # jukebox.show() # Normal window
        jukebox.showMaximized() # Maximized window
    except Exception as e_init:
         import traceback
         print(f"Errore CRITICO durante l'inizializzazione di Jukebox: {e_init}\n{traceback.format_exc()}")
         QMessageBox.critical(None, "Errore Avvio Jukebox",
                              f"Si è verificato un errore irreversibile durante l'avvio.\n\nDettagli: {e_init}")
         # Ensure VLC instance is released even if Jukebox init failed partially
         if 'vlc_instance' in globals() and vlc_instance is not None:
             try: vlc_instance.release()
             except Exception: pass
         sys.exit(1)


    # --- Start Event Loop ---
    exit_code = app.exec_()


    # --- Global VLC Instance Release (after event loop finishes) ---
    # This happens *after* Jukebox.closeEvent has already released the player
    # This releases the main VLC library instance.
    if 'vlc_instance' in globals() and vlc_instance is not None:
         print("Rilascio istanza VLC globale...")
         try:
             vlc_instance.release()
             vlc_instance = None # Clear reference
             print("Istanza VLC globale rilasciata.")
         except Exception as e_vlc_global:
             print(f"Errore durante il rilascio dell'istanza VLC globale: {e_vlc_global}")


    # --- Exit ---
    sys.exit(exit_code)

print("jukebox_gui.py loaded.")