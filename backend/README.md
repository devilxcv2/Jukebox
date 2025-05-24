# Python YouTube/Local Jukebox 🎵

A simple graphical Jukebox built with Python and PyQt5 that allows searching and playing music from YouTube (using `yt-dlp` and VLC) and importing/managing local audio files.
![image](https://github.com/user-attachments/assets/4a811036-bb8b-4427-bd82-8fc8fb2614c0)


## ✨ Key Features

*   **YouTube Search:** Search for videos/music on YouTube and display results.
*   **YouTube Stream Playback:** Plays audio directly from the stream URL provided by `yt-dlp`.
*   **Local File Import:** Import and play your local audio files (supports MP3, FLAC, WAV, OGG, M4A, WEBM, OPUS).
*   **MP3 Download (Optional):** Download audio from YouTube videos and convert it to local MP3 format (requires `ffmpeg`).
*   **Playlist Management:**
    *   Add tracks to the playback queue.
    *   Automatically saves/loads the playlist (`playlist.json`).
*   **History:** Keeps track of played songs (`history.json`).
*   **Favorites:** Save your favorite tracks (`favorites.json`).
*   **Graphical User Interface (GUI):**
    *   Built with PyQt5.
    *   Frameless window with basic dragging support.
    *   Cover art display (with asynchronous download and local caching).
    *   Progress bar with seeking capability.
    *   Volume control.
    *   On-screen virtual keyboard for input (useful for touch screens or kiosk environments).
*   **Controls & Shortcuts:**
    *   Play/Pause, Previous, Next buttons.
    *   Keyboard shortcuts (Space, Arrow keys, Volume, F11 for fullscreen, Esc to close).
*   **Drag & Drop:** Drag local audio files or YouTube URLs directly onto the application window.
*   **Auto-Play:** Automatically plays the next track when the current one finishes.

---

## ⚙️ Requirements

### Software
*   **Python:** Version 3.7 or higher recommended.
*   **VLC (libvlc Library):** The core VLC library needs to be installed on the system. The application uses `python-vlc`, which interfaces with this library.
    *   **Linux:** Usually installable via package manager (e.g., `sudo apt install libvlc-dev libvlccore-dev vlc` on Debian/Ubuntu, `sudo dnf install vlc-devel` on Fedora).
    *   **Windows/macOS:** Installing VLC Media Player from the official [videolan.org](https://www.videolan.org/vlc/) website should provide the necessary libraries.
*   **FFmpeg (Optional, for MP3 Download):** Only required if you want to use the MP3 download and conversion feature. It must be installed and available in the system's PATH for the script to detect it.
    *   Visit [ffmpeg.org](https://ffmpeg.org/download.html) for installation instructions for your platform.

### Python Libraries
You can install these using `pip`:
```bash
pip install -r requirements.txt
