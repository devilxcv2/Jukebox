#!/usr/bin/env python3
# jukebox_data.py
# Contiene la classe Track, le costanti, le funzioni JSON,
# e l'inizializzazione/controllo delle dipendenze globali.

import sys
import os
import json
import re
import shutil
from pathlib import Path
# from PyQt5.QtWidgets import QApplication, QMessageBox # GUI elements removed for server compatibility

# Try importing necessary libraries. Provide user feedback if missing.
try:
    import yt_dlp
except ImportError:
    print("FATAL ERROR: La libreria 'yt_dlp' non è installata.")
    print("Per installarla, esegui: pip install yt-dlp")
    # app = QApplication.instance() # GUI
    # if app is None: app = QApplication(sys.argv) # GUI
    # QMessageBox.critical(None, "Errore Critico", "La libreria 'yt_dlp' non è installata.\nPer installarla, esegui: pip install yt-dlp") # GUI
    sys.exit(1)

try:
    import vlc
except ImportError:
    print("FATAL ERROR: Le librerie 'python-vlc' non sono installate.")
    print("Per installarle, esegui: pip install python-vlc")
    # app = QApplication.instance() # GUI
    # if app is None: app = QApplication(sys.argv) # GUI
    # QMessageBox.critical(None, "Errore Critico", "Le librerie 'python-vlc' non sono installate.\nPer installarle, esegui: pip install python-vlc") # GUI
    sys.exit(1)

try:
    from PIL import Image, ImageDraw
except ImportError:
     print("Warning: Pillow (PIL) not installed. Cannot create default cover placeholder.")
     Image = ImageDraw = None

# Assicura che l'istanza VLC sia creata all'inizio
vlc_instance = None
try:
    instance_options = ['--no-xlib'] if sys.platform.startswith('linux') else []
    instance_options.append('--quiet')

    # app_instance = QApplication.instance() # GUI
    # if app_instance is None: app_instance = QApplication(sys.argv) # Ensure QApplication exists # GUI

    vlc_instance = vlc.Instance(instance_options)

    if vlc_instance is None:
         raise RuntimeError("Impossibile creare istanza VLC.")
except Exception as e:
    print(f"FATAL ERROR: Impossibile inizializzare VLC. Assicurati che libvlc sia installato e accessibile. Dettagli: {e}")
    # Ensure QApplication exists before showing QMessageBox
    # app_instance = QApplication.instance() # GUI
    # if app_instance is None: app_instance = QApplication(sys.argv) # GUI
    # QMessageBox.critical(None, "Errore VLC critico", f"Impossibile inizializzare VLC. Assicurati che sia installato correttamente. Dettagli: {e}") # GUI
    sys.exit(1)


# -------------------- Configuration & Constants --------------------
# Use the directory of *this* data file as the base
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

COVER_DIR = DATA_DIR / "covers"
COVER_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_DIR = DATA_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_COVER = DATA_DIR / "default_cover.png"
if not DEFAULT_COVER.exists() and Image is not None and ImageDraw is not None:
    try:
        img = Image.new('RGB', (100, 100), color = (50, 50, 50))
        d = ImageDraw.Draw(img)
        d.text((10,10), "No Cover", fill=(200,200,200))
        img.save(DEFAULT_COVER)
        print("Default cover placeholder created.")
    except Exception as e:
        print(f"Warning: Error creating default cover: {e}")

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".webm", ".opus"}
MAX_HISTORY_SIZE = 50

YOUTUBE_REGEX = re.compile(
    r'(?:https?:\/\/)?(?:www\.)?(?:youtube\.com|youtu\.be)\/(?:watch\?v=)?(?:embed\/)?(?:v\/)?'
    r'([\w-]{11})'
)

# Check for FFmpeg (required for MP3 conversion)
FFMPEG_PATH = shutil.which('ffmpeg')
if FFMPEG_PATH:
    print(f"FFmpeg found at: {FFMPEG_PATH}")
else:
    print("Warning: FFmpeg not found in PATH. MP3 download conversion will not be available.")

# -------------------- Data Structures --------------------
class Track:
    """Represents a single track (local or stream)."""
    def __init__(self, url, title, thumbnail_url=None, duration_sec=0, is_local=False, webpage_url=None):
        self.url = url
        self.title = title
        self.thumbnail_url = thumbnail_url
        self.duration_sec = duration_sec
        self.is_local = is_local
        self.webpage_url = webpage_url # Often the YouTube page URL

        # Ensure local files have a sensible webpage_url if missing
        if self.is_local and (self.webpage_url is None or not self.webpage_url):
             self.webpage_url = self.url # For local files, webpage_url can be the file path itself

    def to_dict(self):
        """Converts Track object to a dictionary for JSON serialization."""
        return {
            "url": self.url,
            "title": self.title,
            "thumbnail_url": self.thumbnail_url,
            "duration_sec": self.duration_sec,
            "is_local": self.is_local,
            "webpage_url": self.webpage_url
        }

    @staticmethod
    def from_dict(data):
        """Creates a Track object from a dictionary (handles migration from old formats)."""
        if not isinstance(data, (dict, str, list)):
             print(f"Errore conversione Track: dato non è un dict, str o list: {type(data)}")
             return Track(None, "Invalid Track Data") # Return a dummy track

        migrated_data = {}
        identifier_url = None # Used for title fallback and history identification

        # --- Migration Logic ---
        if isinstance(data, str): # Old format: just URL/path
            identifier_url = data
            migrated_data = {"title": data, "webpage_url": data, "url": data} # Assume URL is webpage and stream URL

        elif isinstance(data, list) and len(data) >= 5: # Older format: [stream_url, title, thumb, duration, page_url]
             stream_url = data[0]
             title = data[1]
             thumbnail_url = data[2]
             duration_sec = data[3] if data[3] is not None else 0
             webpage_url_old = data[4]

             identifier_url = webpage_url_old # The page URL is the best identifier

             migrated_data = {
                 "url": stream_url, # This was the stream URL
                 "title": title,
                 "thumbnail_url": thumbnail_url,
                 "duration_sec": duration_sec,
                 "webpage_url": webpage_url_old, # This is the identifier URL
             }

        elif isinstance(data, dict): # Current or slightly older dict format
             migrated_data = data
             # Prioritize webpage_url as the identifier, fall back to url
             identifier_url = migrated_data.get("webpage_url", migrated_data.get("url"))

        else:
             # Should not happen with the initial check, but safety first
             print(f"Elemento inaspettato durante la migrazione: {data}. Ignorato.")
             return Track(None, "Invalid Track Data") # Return a dummy track
        # --- End Migration Logic ---

        # Create the Track instance using migrated data, providing defaults
        track = Track(
            url=migrated_data.get("url"),
            title=migrated_data.get("title", identifier_url or "Titolo Sconosciuto"), # Use identifier if title missing
            thumbnail_url=migrated_data.get("thumbnail_url"),
            duration_sec=migrated_data.get("duration_sec", 0),
            is_local=migrated_data.get("is_local", False), # Default to False if missing
            webpage_url=migrated_data.get("webpage_url")
        )

        # --- Post-Creation Cleanup & Heuristics ---
        # If title ended up being the same as the identifier URL, try to improve it (e.g., from path)
        if track.title == identifier_url and track.url:
            try:
                # If url looks like a path, use the filename stem
                p = Path(str(track.url))
                if p.is_file(): # Check if it *could* be a file path (even if currently a stream URL)
                    track.title = p.stem
            except Exception: # Ignore errors during path parsing
                pass
        if not track.title: # Final fallback if title is still empty
            track.title = "Titolo Sconosciuto"


        # Heuristic: Determine is_local based on URL/path if not explicitly set
        if not migrated_data.get("is_local"): # Only check if not explicitly set to True
             potential_path_str = track.url # Usually the URL field holds the path for local files
             if potential_path_str:
                 try:
                     potential_path = Path(str(potential_path_str))
                     # Check suffix and if the file *actually* exists
                     if potential_path.suffix.lower() in AUDIO_EXTS and potential_path.exists():
                         track.is_local = True
                         # If it's local, ensure URL is the resolved absolute path
                         track.url = str(potential_path.resolve())
                 except OSError: # Handle potential errors with invalid path characters
                     pass
                 except Exception as e: # Catch other potential Path errors
                     print(f"Warning: Error checking path '{potential_path_str}' for local status: {e}")


        # Ensure webpage_url is set consistently
        if track.is_local and (track.webpage_url is None or not track.webpage_url):
             track.webpage_url = track.url # Use path as webpage_url for local files
        elif not track.is_local and track.webpage_url is None and track.url and track.url.startswith("http"):
             # If it's a stream and webpage_url is missing, use the stream url as fallback
             # (This might not always be the YouTube page, but it's better than nothing)
             track.webpage_url = track.url

        return track

# -------------------- JSON Helpers --------------------
def save_json(name: str, data_list):
    """Saves a list of Track objects (or other serializable data) to a JSON file."""
    # Convert Track objects to dictionaries before saving
    data_to_save = [item.to_dict() if isinstance(item, Track) else item for item in data_list]
    fp = DATA_DIR / name
    try:
        fp.parent.mkdir(parents=True, exist_ok=True) # Ensure directory exists
        fp.write_text(json.dumps(data_to_save, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Errore salvataggio JSON {name}: {e}")


def load_json(name: str, item_class=None):
    """Loads data from a JSON file, optionally converting items to item_class objects using from_dict."""
    fp = DATA_DIR / name
    if not fp.exists():
        return [] # Return empty list if file doesn't exist
    try:
        content = fp.read_text(encoding="utf-8").strip()
        if not content: # Handle empty file
             return []

        raw_data = json.loads(content)

        if not isinstance(raw_data, list):
             print(f"Errore: Il file {name} non contiene una lista valida JSON: {type(raw_data)}")
             # Attempt recovery if it's a dict containing a list (rare case)
             if isinstance(raw_data, dict) and len(raw_data) == 1:
                 key = list(raw_data.keys())[0]
                 if isinstance(raw_data[key], list):
                     print(f"Avviso: Recupero lista dalla chiave '{key}' nel file {name}.")
                     raw_data = raw_data[key]
                 else:
                     return [] # Cannot recover list
             else:
                return [] # Not a list, return empty

        # Process items if an item_class with from_dict is provided
        if item_class and hasattr(item_class, 'from_dict'):
            processed_data = []
            for item_data in raw_data:
                 try:
                    item = item_class.from_dict(item_data)
                    # Add only if the created item is valid (e.g., has a title or URL)
                    if item and (item.title or item.url):
                         processed_data.append(item)
                    else:
                        print(f"Avviso: Elemento non valido saltato durante il caricamento di {name}: {item_data}")
                 except Exception as e:
                     print(f"Errore durante la conversione dell'elemento in {name}: {item_data} -> {e}")

            return processed_data
        else:
             # Return raw list if no conversion class provided
             return raw_data

    except json.JSONDecodeError as e:
        print(f"Errore di decodifica JSON nel file {name}: {e}")
        # Optionally, try to backup the corrupted file here
        # backup_path = fp.with_suffix(f".corrupted_{int(time.time())}.json")
        # try: shutil.copy(fp, backup_path); print(f"Backed up corrupted file to {backup_path}")
        # except Exception as backup_e: print(f"Error backing up corrupted file: {backup_e}")
        return [] # Return empty list on decoding error
    except Exception as e:
        print(f"Errore generico durante il caricamento del file {name}: {e}")
        return [] # Return empty list on other errors

print(f"Data directory: {DATA_DIR}")
print("jukebox_data.py loaded.")