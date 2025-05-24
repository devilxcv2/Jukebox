from flask import Flask, send_from_directory, jsonify, request
import vlc # Make sure vlc is imported
import json # For generic JSON helpers
import os # For path operations
from pathlib import Path # For path operations

# Attempt to import from jukebox_data, otherwise define necessities
try:
    from backend.jukebox_data import Track, load_json as load_track_json, vlc_instance, DATA_DIR
except ImportError:
    print("Warning: Could not import full jukebox_data. Defining minimal DATA_DIR for webradios.")
    # Define DATA_DIR relative to current file (app.py) if jukebox_data is problematic
    # This assumes app.py is in backend/
    APP_DIR = Path(__file__).resolve().parent
    DATA_DIR = APP_DIR / "data"
    # Dummy Track and load_track_json if not available, so rest of the file doesn't break
    class Track: pass
    def load_track_json(filename, track_class): return []
    # vlc_instance might also be an issue if jukebox_data fails. For now, assume it's available or handled later.
    if 'vlc_instance' not in globals():
        # This is a fallback, real vlc_instance should come from jukebox_data
        # For this subtask, we mainly focus on JSON files, not necessarily VLC ops.
        vlc_instance = vlc.Instance(['--quiet', '--no-xlib'] if sys.platform.startswith('linux') else [])


app = Flask(__name__, static_folder='../frontend/static', template_folder='../frontend')

# --- Generic JSON Data Helpers ---
def _ensure_data_dir_exists():
    """Ensures the DATA_DIR directory exists."""
    if not DATA_DIR.exists():
        print(f"Data directory {DATA_DIR} not found, creating it.")
        DATA_DIR.mkdir(parents=True, exist_ok=True)

def _load_json_data(filename: str, default_data=None):
    """Loads generic JSON data from a file in DATA_DIR."""
    _ensure_data_dir_exists()
    filepath = DATA_DIR / filename
    if not filepath.exists():
        if default_data is not None:
            print(f"File {filepath} not found. Creating with default data.")
            _save_json_data(filename, default_data) # Save the defaults
            return default_data
        return [] if default_data is None else default_data # Return empty list or provided default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content: # Handle empty file
                 return [] if default_data is None else default_data
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading JSON from {filepath}: {e}")
        return [] if default_data is None else default_data # Return empty or default on error

def _save_json_data(filename: str, data):
    """Saves data to a JSON file in DATA_DIR."""
    _ensure_data_dir_exists()
    filepath = DATA_DIR / filename
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Data saved to {filepath}")
    except IOError as e:
        print(f"Error saving JSON to {filepath}: {e}")

# --- Player State & Initialization ---
player = vlc_instance.media_player_new() if vlc_instance else None
if player is None:
    print("FATAL ERROR: VLC player instance creation failed in app.py. VLC might not be installed correctly.")
    # In a real app, you might exit or disable player functionality
    # For now, we'll let it potentially crash later if player is used.

# Use the original load_json (aliased to load_track_json) for track-specific lists
current_playlist = load_track_json("playlist.json", Track)
history_data = load_track_json("history.json", Track) # Not directly modified by player but loaded
favorites_data = load_track_json("favorites.json", Track) # Not directly modified by player but loaded

# --- Web Radio Data ---
DEFAULT_WEBRADIOS = [
  {
    "name": "Radio Deejay (MP3)",
    "url_stream": "http://shoutcast.unitedradio.it/RadioDeejay"
  },
  {
    "name": "Rai Radio 1 (MP3)",
    "url_stream": "http://icestreaming.rai.it/1.mp3"
  }
]
webradio_stations = _load_json_data("webradios.json", default_data=DEFAULT_WEBRADIOS)


current_track_index = -1
is_playing = False
current_volume = 80 # Default volume
if player:
    player.audio_set_volume(current_volume)

# --- Player State Variables ---
current_track_index = -1
is_playing = False
current_volume = 80 # Default volume
current_media_type = "none" # Can be "playlist", "webradio", or "none"
current_radio_info = None   # Stores {"name": "...", "url_stream": "..."} if radio is playing

if player:
    player.audio_set_volume(current_volume)

# --- VLC Event Handling ---
# from threading import Lock # If needed for complex cross-thread state changes
# vlc_event_lock = Lock()

def _handle_end_reached_event(event):
    global current_media_type
    # with vlc_event_lock: # If using a lock
    print("VLC Event: MediaPlayerEndReached")
    if current_media_type == "webradio":
        print("MediaPlayerEndReached for a web radio. Ignoring (or could implement auto-restart).")
        # Optionally, could try to restart the stream:
        # if player and current_radio_info:
        #    print(f"Attempting to restart web radio: {current_radio_info['name']}")
        #    media = vlc_instance.media_new(current_radio_info['url_stream'], ':network-caching=3000')
        #    player.set_media(media)
        #    media.release()
        #    player.play()
        #    # is_playing should remain true or be re-asserted by play() success
        return
    elif current_media_type == "playlist":
        _play_next_track(from_event=True)
    else:
        print(f"MediaPlayerEndReached in unknown media type state: {current_media_type}")


if player:
    event_manager = player.event_manager()
    event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, _handle_end_reached_event)

# --- Helper Functions ---
def _get_player_status():
    global current_track_index, current_playlist, is_playing, current_volume, player
    global current_media_type, current_radio_info
    
    track_dict = None
    duration_ms = 0
    current_time_ms = 0
    actual_is_playing = False
    status_output = {}

    if player:
        current_time_ms = player.get_time() or 0
        actual_is_playing = player.is_playing()
        # Reconcile logical is_playing state if VLC reports differently
        if is_playing and not actual_is_playing:
            # If we thought it was playing, but VLC says it's not, update our state.
            # This can happen if a track ends and EndReached hasn't fired/completed yet,
            # or if playback stopped for an external reason.
            print("Reconciling state: VLC not playing, but is_playing was true. Setting is_playing to false.")
            is_playing = False


    if current_media_type == "webradio" and current_radio_info:
        track_dict = { # Create a representation for the web radio
            "title": current_radio_info.get("name", "Web Radio"),
            "artist": "Web Radio Stream", # Placeholder
            "album": "", # Placeholder
            "thumbnail_url": current_radio_info.get("thumbnail_url"), # Optional if we store it
            "is_webradio": True,
            "is_local": False, # Web radios are not local files
            "duration_sec": 0, # Duration is unknown/irrelevant for streams
            "webpage_url": current_radio_info.get("url_stream") # The stream URL itself
        }
        duration_ms = 0 # Live streams don't have a fixed duration
        status_output.update({
            "media_type": "webradio",
            "station_info": current_radio_info,
            "current_track_index": -1 # Or a special value indicating radio
        })
    elif current_media_type == "playlist" and 0 <= current_track_index < len(current_playlist):
        track_dict = current_playlist[current_track_index].to_dict()
        if player and player.get_media(): # Only get duration if media is set
             media_duration = player.get_length()
             duration_ms = media_duration if media_duration > 0 else (track_dict.get('duration_sec', 0) * 1000)
        status_output.update({
            "media_type": "playlist",
            "current_track_index": current_track_index,
        })
    else: # "none" or invalid state
        status_output.update({
            "media_type": current_media_type, # Could be "none"
            "current_track_index": -1,
        })

    status_output.update({
        "is_playing": is_playing,
        "actually_playing_vlc": actual_is_playing, # For debugging frontend if needed
        "current_track": track_dict,
        "current_time_ms": current_time_ms,
        "duration_ms": duration_ms,
        "volume": current_volume,
        "playlist_length": len(current_playlist),
    })
    return status_output

def _play_track_at_index(index: int, from_event=False):
    global current_track_index, current_playlist, is_playing, player, current_media_type, current_radio_info
    
    if not player:
        print("Error: VLC Player not initialized.")
        is_playing = False
        return False

    # This function is for playlist tracks, so update media type
    current_media_type = "playlist"
    current_radio_info = None # Clear any radio info

    if not (0 <= index < len(current_playlist)):
        print(f"Error: Track index {index} is out of bounds for playlist length {len(current_playlist)}.")
        if player: player.stop()
        current_track_index = -1
        is_playing = False
        return False

    track_to_play = current_playlist[index]
    
    if player.is_playing() or player.get_state() == vlc.State.Paused:
        if current_track_index == index and player.get_state() == vlc.State.Paused and current_media_type == "playlist":
            # If it's the same playlist track and it's paused, just resume.
             if player.play() != -1:
                is_playing = True
                print(f"Resuming playlist track {index}: {track_to_play.title}")
                return True
             else:
                print(f"Error resuming playlist track {index}: {track_to_play.title}")
                is_playing = False
                return False
        player.stop() # Stop whatever was playing before
    
    media_path = track_to_play.url
    if not media_path:
        print(f"Error: Track '{track_to_play.title}' has no valid URL/path.")
        is_playing = False
        return False

    try:
        media = vlc_instance.media_new(media_path)
        if not media:
            print(f"Error: VLC could not create media for path: {media_path}")
            is_playing = False
            return False
        player.set_media(media)
        media.release()
        
        play_result = player.play()
        if play_result == -1:
            print(f"Error: player.play() failed for {media_path}")
            is_playing = False
            return False
            
        current_track_index = index
        is_playing = True
        print(f"Playing playlist track {index}: {track_to_play.title}")
        # History addition could be signaled here or handled by an event if needed
        return True
    except Exception as e:
        print(f"Exception during _play_track_at_index for {media_path}: {e}")
        is_playing = False
        return False

def _play_next_track(from_event=False):
    global current_track_index, current_playlist, is_playing, current_media_type
    if current_media_type != "playlist": # Only play next if current media is from playlist
        print("_play_next_track called but not in playlist mode. Stopping.")
        if player: player.stop()
        is_playing = False
        # current_media_type = "none" # Or keep as "webradio" if it was
        return False

    if not current_playlist:
        is_playing = False
        return False 
    
    new_index = current_track_index + 1
    if new_index >= len(current_playlist):
        new_index = 0 
        if not from_event: 
            pass # For now, always wrap around. Loop control can be added later.
            
    return _play_track_at_index(new_index) # This will set current_media_type to "playlist"

def _play_previous_track():
    global current_track_index, current_playlist, is_playing, current_media_type
    if current_media_type != "playlist":
        print("_play_previous_track called but not in playlist mode. Stopping.")
        if player: player.stop()
        is_playing = False
        # current_media_type = "none"
        return False

    if not current_playlist:
        is_playing = False
        return False
        
    new_index = current_track_index - 1
    if new_index < 0:
        new_index = len(current_playlist) - 1 if current_playlist else -1
        
    if new_index == -1: # Playlist became empty or was empty
        return False
            
    return _play_track_at_index(new_index) # This will set current_media_type to "playlist"

# # @app.route('/api/hello')
# def hello():
#     return jsonify({'message': 'Backend Flask Jukebox Attivo'})

@app.route('/')
def index():
    # Serves files from the 'template_folder' which is '../frontend'
    return send_from_directory(app.template_folder, 'index.html')

@app.route('/api/playlist')
def get_playlist_data(): # Renamed to avoid conflict with current_playlist global
    return jsonify([track.to_dict() for track in current_playlist])

@app.route('/api/history')
def get_history():
    return jsonify([track.to_dict() for track in history_data])

@app.route('/api/favorites')
def get_favorites():
    return jsonify([track.to_dict() for track in favorites_data])

# --- Web Radio API Routes ---
@app.route('/api/webradios', methods=['GET'])
def get_webradios():
    return jsonify(webradio_stations)

@app.route('/api/webradios/add', methods=['POST'])
def add_webradio():
    global webradio_stations, player, is_playing, current_track_index, current_media_type, current_radio_info
    data = request.json
    if not data or 'name' not in data or 'url_stream' not in data:
        return jsonify({"error": "Missing 'name' or 'url_stream' in request body"}), 400
    
    name = data['name'].strip()
    url_stream = data['url_stream'].strip()

    if not name or not url_stream:
        return jsonify({"error": "'name' and 'url_stream' cannot be empty"}), 400

    if not player:
        return jsonify({"error": "Player not initialized"}), 500

    if player.is_playing() or player.get_state() == vlc.State.Paused:
        player.stop()
        print("Stopped previous playback to play web radio.")

    try:
        media = vlc_instance.media_new(url_stream, ':network-caching=3000') # Standard caching for streams
        if not media:
            return jsonify({"error": f"VLC could not create media for URL: {url_stream}"}), 500
        
        player.set_media(media)
        media.release()
        
        if player.play() == -1:
            is_playing = False
            current_media_type = "none"
            current_radio_info = None
            return jsonify({"error": f"player.play() failed for web radio: {url_stream}"}), 500

        is_playing = True
        current_track_index = -1 # Indicate not a playlist track
        current_media_type = "webradio"
        current_radio_info = {"name": name, "url_stream": url_stream}
        print(f"Playing web radio: {name} - {url_stream}")
        
    except Exception as e:
        is_playing = False
        current_media_type = "none"
        current_radio_info = None
        print(f"Exception during web radio playback setup for {url_stream}: {e}")
        return jsonify({"error": f"Exception setting up web radio: {str(e)}"}), 500
        
    return jsonify(_get_player_status())


# --- Player API Routes ---

@app.route('/api/player/status', methods=['GET'])
def player_status():
    return jsonify(_get_player_status())

@app.route('/api/player/play', methods=['POST'])
def player_play():
    global current_track_index, current_playlist, is_playing, player
    data = request.json
    
    if data and 'track_index' in data:
        try:
            requested_index = int(data['track_index'])
            if 0 <= requested_index < len(current_playlist):
                _play_track_at_index(requested_index)
            else:
                return jsonify({"error": "Invalid track_index"}), 400
        except ValueError:
            return jsonify({"error": "track_index must be an integer"}), 400
    else: # No track_index provided
        if not player:
             return jsonify({"error": "Player not initialized"}), 500
        current_vlc_state = player.get_state()
        if current_vlc_state == vlc.State.Paused:
            player.play() # Resume
            is_playing = True
        elif current_vlc_state == vlc.State.Stopped or current_vlc_state == vlc.State.Ended or current_vlc_state == vlc.State.NothingSpecial:
            if 0 <= current_track_index < len(current_playlist):
                _play_track_at_index(current_track_index) # Play current (or last played)
            elif current_playlist:
                _play_track_at_index(0) # Play first track
        # If already playing, do nothing.
            
    return jsonify(_get_player_status())

@app.route('/api/player/pause', methods=['POST'])
def player_pause():
    global is_playing, player
    if player and player.can_pause():
        player.pause()
        is_playing = False
    return jsonify(_get_player_status())

@app.route('/api/player/next', methods=['POST'])
def player_next():
    _play_next_track()
    return jsonify(_get_player_status())

@app.route('/api/player/previous', methods=['POST'])
def player_previous():
    _play_previous_track()
    return jsonify(_get_player_status())

@app.route('/api/player/volume', methods=['POST'])
def player_volume():
    global current_volume, player
    data = request.json
    if data and 'volume' in data:
        try:
            vol = int(data['volume'])
            if 0 <= vol <= 200: # VLC volume can go higher than 100
                if player:
                    player.audio_set_volume(vol)
                current_volume = vol # Store our logical volume
            else:
                return jsonify({"error": "Volume must be between 0 and 200"}), 400
        except ValueError:
            return jsonify({"error": "Volume must be an integer"}), 400
    else:
        return jsonify({"error": "Missing volume parameter"}), 400
    return jsonify(_get_player_status())

if __name__ == '__main__':
    # Note: The original jukebox_data.py has PyQt GUI calls at import time.
    # These were addressed by commenting them out in jukebox_data.py.
    print("Attempting to load Jukebox data for Flask app...")
    print(f"Loaded {len(current_playlist)} tracks into playlist.")
    print(f"Loaded {len(history_data)} tracks into history.")
    print(f"Loaded {len(favorites_data)} tracks into favorites.")
    print(f"Serving static files from: {app.static_folder}")
    print(f"Serving templates from: {app.template_folder}")
    print(f"Initial player volume set to: {current_volume}")
    if player:
        print(f"VLC Player instance: {player}")
    else:
        print("VLC Player instance FAILED to initialize.")
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False) # use_reloader=False can be important with VLC
# def hello():
#     return jsonify({'message': 'Backend Flask Jukebox Attivo'})

@app.route('/')
def index():
    # Serves files from the 'template_folder' which is '../frontend'
    return send_from_directory(app.template_folder, 'index.html')

@app.route('/api/playlist')
def get_playlist():
    return jsonify([track.to_dict() for track in playlist_data])

@app.route('/api/history')
def get_history():
    return jsonify([track.to_dict() for track in history_data])

@app.route('/api/favorites')
def get_favorites():
    return jsonify([track.to_dict() for track in favorites_data])

if __name__ == '__main__':
    # Note: The original jukebox_data.py has PyQt GUI calls at import time.
    # These will likely cause issues when running as a Flask app,
    # especially in a headless environment. This needs to be addressed separately.
    print("Attempting to load Jukebox data for Flask app...")
    print(f"Loaded {len(playlist_data)} tracks into playlist.")
    print(f"Loaded {len(history_data)} tracks into history.")
    print(f"Loaded {len(favorites_data)} tracks into favorites.")
    print(f"Serving static files from: {app.static_folder}")
    print(f"Serving templates from: {app.template_folder}")
    app.run(debug=True, host='0.0.0.0', port=5000)
