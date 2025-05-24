# #!/usr/bin/env python3
# # jukebox_gui.py
# # Contiene la classe principale dell'interfaccia grafica (Jukebox),
# # la tastiera virtuale (VirtualKeyboard), e il codice di avvio.
# # ATTENZIONE: Questo file è stato in gran parte commentato per rimuovere le dipendenze GUI
# # dirette da PyQt5 e renderlo compatibile con un ambiente server.

import sys
import os
import json
# import threading # Keep if workers are used and are non-GUI
# import requests # Keep if any non-GUI HTTP requests are made (e.g. by workers, or if get_pixmap was adapted)
import time # Keep for general utilities
import hashlib # Keep for general utilities
from pathlib import Path

# # --- Comment out PyQt5 imports ---
# # from PyQt5.QtWidgets import (
# #     QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
# #     QLineEdit, QListWidget, QListWidgetItem, QSlider, QMessageBox,
# #     QInputDialog, QShortcut, QGridLayout, QFileDialog, QSpinBox,
# #     QSizePolicy, QProgressDialog, QDesktopWidget, QCheckBox,QMenu, QAction
# # )
# # from PyQt5.QtGui import QPixmap, QFont, QColor, QMovie, QKeySequence
# # from PyQt5.QtCore import (
# #     Qt, QTimer, pyqtSignal, QEvent, QPoint, QThread, QMutex, QUrl,
# #     QSize, QRect, QPropertyAnimation
# # )

# # Minimal PyQt5.QtCore imports if workers absolutely need them AND they are GUI-agnostic
# # It's safer to assume that if QThread/pyqtSignal are used by workers, those workers
# # might need adaptation for a non-GUI environment or their signaling mechanism replaced.
# # For a pure backend, it's best if workers don't depend on PyQt at all.
try:
    from PyQt5.QtCore import QObject, pyqtSignal # QObject as base, pyqtSignal for worker communication
    # class pyqtSignal: # Dummy for environments without PyQt5
    #     def __init__(self, *args, **kwargs): pass
    #     def connect(self, slot): pass
    #     def emit(self, *args): pass
except ImportError:
    print("PyQt5.QtCore not found, using dummy QObject and pyqtSignal for server mode.")
    class QObject:
        def __init__(self, parent=None): pass
        def sender(self): return None
        def deleteLater(self): pass # Add dummy deleteLater
        def installEventFilter(self, obj): pass
        def setProperty(self, name, value): pass
        def property(self, name): return None

    class pyqtSignal:
        def __init__(self, *args, **kwargs): pass
        def connect(self, slot): pass
        def emit(self, *args): pass

import vlc # Import vlc module itself

# Importa elementi necessari dagli altri moduli
# Ensure these modules are also GUI-agnostic or have been neutralized
from backend.jukebox_data import ( # Corrected import path
    vlc_instance, Track, save_json, load_json,
    DATA_DIR, COVER_DIR, DOWNLOAD_DIR, DEFAULT_COVER,
    AUDIO_EXTS, MAX_HISTORY_SIZE, YOUTUBE_REGEX, FFMPEG_PATH
)
from backend.jukebox_workers import ( # Corrected import path
    YoutubeSearchWorker, CoverDownloadWorker, FileProbeWorker
)

# # -------------------- Virtual Keyboard Widget (Commented Out) --------------------
# class VirtualKeyboard(QWidget): # Inherits QWidget, problematic
#     """A simple on-screen virtual keyboard, adapted for touch. DEACTIVATED."""
#     # key_pressed = pyqtSignal(str)
#     # closed = pyqtSignal()
#     # key_pressed = pyqtSignal(str) # Dummy
#     # closed = pyqtSignal() # Dummy

#     def __init__(self):
#         # super().__init__(flags=Qt.Window | Qt.FramelessWindowHint | Qt.Tool)
#         print("VirtualKeyboard (GUI) è disattivata.")
#         pass
    # ... (rest of VirtualKeyboard methods would be here, commented out) ...

# # -------------------- Main Jukebox Widget (Commented Out / Adapted) --------------------
# # class Jukebox(QWidget): # Original inheritance
class Jukebox_DEACTIVATED(QObject): # Inherit from QObject if only for signals/slots non-GUI
    """
    Interfaccia Jukebox. Logica GUI disattivata per compatibilità server.
    Alcune logiche di gestione dati e player potrebbero essere mantenute se
    utilizzabili da un backend API.
    """
    # --- Signals (Potentially kept if workers use them non-GUI) ---
    play_track_signal = pyqtSignal(int)
    add_tracks_to_playlist_signal = pyqtSignal(list)
    add_to_history_signal = pyqtSignal(Track)
    update_probe_duration_signal = pyqtSignal(str, int)
    playback_error_signal = pyqtSignal(str)

    def __init__(self):
        super(Jukebox_DEACTIVATED, self).__init__() # Call to QObject constructor
        print("Jukebox_DEACTIVATED: __init__ called. GUI functionalities are neutralized.")

        # --- VLC Player Setup (Potentially kept for backend control) ---
        if vlc_instance is None:
            print("ERRORE CRITICO: Istanza VLC non inizializzata in Jukebox_DEACTIVATED!")
            return
        self.player = vlc_instance.media_player_new()
        if self.player is None:
             print("FATAL ERROR: Player instance creation failed in Jukebox_DEACTIVATED.")
             return
        
        # --- VLC Event Handling (Commented out - relies on QTimer/Qt event loop) ---
        # self.event_manager = self.player.event_manager()
        # ... (event_attach calls commented out) ...

        # --- Load Data (Kept, as it's non-GUI) ---
        try:
            self.playlist = load_json("playlist.json", Track)
            self.history = load_json("history.json", Track)
            self.favorites = load_json("favorites.json", Track)
            print(f"Jukebox_DEACTIVATED: Loaded {len(self.playlist)} playlist, {len(self.history)} history, {len(self.favorites)} favs.")
        except Exception as e:
            print(f"Jukebox_DEACTIVATED: Errore caricamento JSON: {e}")
            self.playlist, self.history, self.favorites = [], [], []

        # --- State Variables (Kept) ---
        self.current_idx = -1
        self.is_playing = False # Reflects backend logical state if it controls player
        self.current_track_info = None

        # --- Worker References (Kept, assuming workers are adapted) ---
        self.yt_search_worker = None
        self.cover_worker = None
        self.probe_workers = []
        self.is_searching = False # Manages backend search state
        self.context_download_worker = None
        
        # --- GUI Specific attributes (commented out or dummied) ---
        # self.vkbd = VirtualKeyboard() # GUI
        # self.dragging = False # GUI
        # self.drag_pos = None # QPoint() # GUI

        # --- Connect Signals to Slots (Non-GUI parts can be kept) ---
        # These connections are fine if the slots are non-GUI or adapted.
        self.play_track_signal.connect(self._play_current_index_nogui)
        self.add_tracks_to_playlist_signal.connect(self._add_tracks_to_playlist_nogui)
        self.add_to_history_signal.connect(self._add_to_history_nogui)
        self.update_probe_duration_signal.connect(self._handle_probe_done_nogui)
        self.playback_error_signal.connect(self._handle_playback_error_nogui)
        
        print("Jukebox_DEACTIVATED instance created (non-GUI logic).")

    # --- Non-GUI methods (data management, VLC control logic if backend uses it) ---

    def _play_current_index_nogui(self, index):
        print(f"Jukebox_DEACTIVATED (non-GUI): Richiesta riproduzione indice {index}.")
        if not self.player:
            print("Jukebox_DEACTIVATED: Player non inizializzato.")
            return
        if not (0 <= index < len(self.playlist)):
            print(f"Jukebox_DEACTIVATED: Indice non valido {index}. Stop player.")
            self.player.stop()
            self.current_idx = -1
            self.current_track_info = None
            self.is_playing = False
            return
        
        track_to_play = self.playlist[index]
        if self.player.is_playing() or self.player.get_state() == vlc.State.Paused:
            self.player.stop()

        media_source = track_to_play.url
        if not media_source:
             self.playback_error_signal.emit(f"URL/Percorso non valido per '{track_to_play.title}'.")
             return

        try:
            media = None
            if track_to_play.is_local:
                 if not Path(media_source).exists(): raise FileNotFoundError(f"File locale non trovato: {media_source}")
                 media = vlc_instance.media_new_path(str(media_source))
            else:
                 if not str(media_source).lower().startswith(('http', 'rtsp', 'rtmp')):
                     raise ValueError(f"Formato URL non supportato: {media_source}")
                 media = vlc_instance.media_new(media_source, '--no-video-title-show', ':network-caching=3000')
            
            if media is None: raise ValueError("Impossibile creare media VLC.")
            
            self.player.set_media(media)
            media.release()
            if self.player.play() == -1: raise RuntimeError("player.play() ha restituito -1.")

            self.current_idx = index
            self.current_track_info = track_to_play
            self.is_playing = True
            print(f"Jukebox_DEACTIVATED (non-GUI): Riproducendo '{track_to_play.title}'.")
            self.add_to_history_signal.emit(track_to_play)

        except Exception as e:
             self.playback_error_signal.emit(f"Errore avvio '{track_to_play.title}': {e}")


    def _add_tracks_to_playlist_nogui(self, tracks):
        # (Implementation as provided previously, seems okay for non-GUI)
        if not tracks: return
        added_count = 0
        for track in tracks:
            if isinstance(track, Track) and (track.url or track.webpage_url):
                self.playlist.append(track)
                added_count += 1
        if added_count > 0:
            print(f"Jukebox_DEACTIVATED (non-GUI): Aggiunti {added_count} brani.")
            save_json("playlist.json", self.playlist)

    def _add_to_history_nogui(self, track):
        # (Implementation as provided previously, seems okay for non-GUI)
        if not isinstance(track, Track): return
        identifier_to_add = track.webpage_url or track.url
        if not identifier_to_add: return
        self.history = [t for t in self.history if (t.webpage_url or t.url) != identifier_to_add]
        self.history.insert(0, track)
        if len(self.history) > MAX_HISTORY_SIZE:
            self.history = self.history[:MAX_HISTORY_SIZE]
        save_json("history.json", self.history)
        print(f"Jukebox_DEACTIVATED (non-GUI): Aggiunto '{track.title}' alla cronologia.")


    def _handle_probe_done_nogui(self, path, duration_ms):
        # (Implementation as provided previously, seems okay for non-GUI)
        duration_sec = duration_ms // 1000 if duration_ms is not None and duration_ms > 0 else 0
        for i, track in enumerate(self.playlist):
            if track.is_local and str(Path(track.url).resolve()) == str(Path(path).resolve()):
                if track.duration_sec != duration_sec:
                    track.duration_sec = duration_sec
                    print(f"Jukebox_DEACTIVATED (non-GUI): Durata aggiornata per {track.title}: {duration_sec}s")
                    # If this was the current track, the info might need updating if exposed via API
                break
    
    def _handle_playback_error_nogui(self, msg):
        print(f"Jukebox_DEACTIVATED (non-GUI) Playback Error: {msg}")
        if self.player: self.player.stop()
        self.is_playing = False
        # Potentially try to play next or signal error to an API client

    # --- Placeholder for GUI methods that are now removed/deactivated ---
    def _error(self, msg): print(f"Jukebox_DEACTIVATED (non-GUI) ERRORE: {msg}")
    def _info(self, msg): print(f"Jukebox_DEACTIVATED (non-GUI) INFO: {msg}")
    
    # (All other GUI methods like _style, _ui, _shortcuts, event handlers for GUI elements,
    # mouse events, _show_context_menu, _refresh_lists, _set_cover, _show_loading etc.
    # are effectively removed by not being defined here or by being commented out if this
    # class structure was a direct copy-paste then modification)

    def closeEvent(self, event=None): # Non-GUI cleanup
        print("Jukebox_DEACTIVATED (non-GUI): Chiusura...")
        if self.player:
            if self.player.is_playing(): self.player.stop()
            self.player.release()
            self.player = None
        # Cancel any running non-GUI workers if applicable
        # for worker in [self.yt_search_worker, self.cover_worker, ...]:
        #    if worker and hasattr(worker, 'cancel') and worker.isRunning(): worker.cancel()
        save_json("playlist.json", self.playlist)
        save_json("history.json", self.history)
        save_json("favorites.json", self.favorites)
        print("Jukebox_DEACTIVATED (non-GUI): Chiuso e dati salvati.")

# # -------------------- Main Execution Block (Commented Out) --------------------
# # if __name__ == "__main__":
# #     # ... (original main execution block commented out) ...
# #     print("jukebox_gui.py eseguito come script, ma la GUI è disattivata.")

print("jukebox_gui.py loaded (GUI parts mostly deactivated for server compatibility).")