#!/usr/bin/env python3
# jukebox_workers.py
# Contiene le classi QThread per le operazioni in background
# (Ricerca YouTube, Download Copertine, Analisi File Locali).

import time
import requests
import yt_dlp
import vlc
from pathlib import Path
from PyQt5.QtCore import QThread, pyqtSignal

# Importa elementi necessari dal modulo data
from jukebox_data import Track, DOWNLOAD_DIR, AUDIO_EXTS, FFMPEG_PATH, YOUTUBE_REGEX

# -------------------- Worker Threads --------------------

class YoutubeSearchWorker(QThread):
    """Worker thread for performing YouTube searches or extracting info/downloading from URLs."""
    results_ready = pyqtSignal(list) # Emits list of Track objects
    error_occurred = pyqtSignal(str)
    progress_update = pyqtSignal(str) # Emits status messages for the UI

    def __init__(self, query, num_results, download_audio: bool):
        super().__init__()
        self.query = query
        self.num_results = num_results
        self.download_audio = download_audio
        self._is_cancelled = False
        self._ydl = None # Store the yt-dlp instance for potential cancellation

    def cancel(self):
        """Signals the worker to stop processing."""
        self._is_cancelled = True
        # Attempt to signal yt-dlp if it's active
        if self._ydl:
            try:
                # Use internal flag if available (may change in future yt-dlp versions)
                if hasattr(self._ydl, '_download_retries'): # Heuristic to check if download started
                    # Injecting a stop signal might be complex/unreliable.
                    # Relying on the progress hook check is safer.
                    print("YT Worker: Cancellation requested during potential download.")
                    pass
            except Exception as e:
                print(f"Error during yt-dlp cancellation signal: {e}")

    def _hook(self, d):
        """Yt-dlp progress hook to check cancellation flag and report download progress."""
        # Check cancellation flag frequently
        if self._is_cancelled:
            raise yt_dlp.utils.DownloadCancelled() # Stop yt-dlp processing

        status = d.get('status')
        filename_short = Path(d.get('filename', '...')).name[:35] # Shorten filename for display

        if status == 'extracting_video':
             # Note: 'info_dict' might not be available here yet
             title_short = d.get('title', d.get('id', '...'))[:40]
             self.progress_update.emit(f"Estrazione info: {title_short}...")
        elif status == 'downloading' and self.download_audio:
            total_bytes_str = d.get('total_bytes_str') or d.get('total_bytes_estimate_str')
            downloaded_bytes = d.get('downloaded_bytes', 0)
            elapsed_str = d.get('elapsed_str', '')
            speed_str = d.get('speed_str', '')
            eta_str = d.get('eta_str', '')

            # Prefer total_bytes_estimate if total_bytes isn't available yet
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate', 0)

            if total_bytes > 0:
                 percent = downloaded_bytes / total_bytes * 100
                 self.progress_update.emit(f"Download ({percent:.1f}%): {filename_short}... [{speed_str} ETA {eta_str}]")
            else:
                 # Downloading, but size unknown (e.g., live stream fragments)
                 downloaded_str = d.get('downloaded_bytes_str', f"{downloaded_bytes} B")
                 self.progress_update.emit(f"Download: {filename_short}... ({downloaded_str}) [{speed_str}]")

        elif status == 'postprocessing' and self.download_audio:
             # info_dict should be available here
             title_short = d.get('info_dict', {}).get('title', filename_short)[:30]
             # Check which postprocessor is running (if available)
             pp_key = d.get('postprocessor') # <-- CORRETTO: Nome variabile senza spazi
             # Extract the name before potential parenthesis (like 'FFmpegExtractAudio(finalize)' -> 'FFmpegExtractAudio')
             pp_name = pp_key.split('(')[0] if pp_key else "Conversione" # <-- CORRETTO: Usa la variabile pp_key
             self.progress_update.emit(f"{pp_name}: {title_short}...")
             self.progress_update.emit(f"{pp_name}: {title_short}...")

        elif status == 'finished':
             if self.download_audio:
                 self.progress_update.emit(f"Completato: {filename_short}")
             # else: # If only extracting info, 'finished' might mean info extraction done
                 # self.progress_update.emit(f"Info estratte per: {filename_short}")
                 pass # Avoid emitting message here if only extracting info


    def run(self):
        """Runs the yt-dlp extraction/download process."""
        if self._is_cancelled: return

        is_url = self.query.lower().startswith("http") or any(base in self.query.lower() for base in ["youtube.com/", "youtu.be/", "soundcloud.com/", "vimeo.com/"])
        ytq = self.query # The query or URL passed to yt-dlp
        search_type_msg = "URL" if is_url else "ricerca testuale"

        # Determine yt-dlp options
        opts = {
            'format': 'bestaudio/best', # Prioritize best audio
            'quiet': True, # Suppress yt-dlp console output (we use hooks)
            'noplaylist': False, # Allow playlists by default if URL is playlist-like
            'extract_flat': 'discard_in_playlist', # Faster playlist extraction, get full info later if needed
            'restrictfilenames': True, # Avoid special characters in filenames
            'default_search': 'ytsearch', # Use YouTube search if not a URL
            'progress_hooks': [self._hook], # Our custom hook
            'usenetrc': False, # Don't use .netrc file
            'cookiefile': None, # Don't use cookies unless specified
            'no_warnings': True, # Suppress yt-dlp warnings
            'ignoreerrors': True, # Try to continue if some items in playlist fail
            'skip_download': not self.download_audio, # Skip download if not requested
            'writethumbnail': self.download_audio, # Write thumbnail if downloading
            'writeinfojson': self.download_audio, # Write .info.json if downloading (useful for metadata)
            'outtmpl': str(DOWNLOAD_DIR / '%(extractor)s_%(id)s.%(ext)s'), # Default template (gets overwritten for MP3)
        }

        if is_url:
             # If it looks like a playlist, ensure playlist extraction is enabled
             if any(param in self.query.lower() for param in ["list=", "/playlist?", "/sets/"]) or \
                "music.youtube.com/playlist" in self.query.lower() or \
                "soundcloud.com/" in self.query.lower() and "/sets/" in self.query.lower():
                 opts['noplaylist'] = False
                 opts['extract_flat'] = True # Use flat extraction for playlists speed
                 search_type_msg = "Playlist/URL"
             else:
                 opts['noplaylist'] = True # Treat as single item URL
                 opts['extract_flat'] = False # Get full info directly for single items

             # If downloading audio for a single YouTube video, don't use flat extract
             if self.download_audio and YOUTUBE_REGEX.search(self.query) and not opts['noplaylist']:
                  opts['extract_flat'] = False

        else: # Text search
             ytq = f"ytsearch{self.num_results}:{self.query}" # Format for yt-dlp search
             opts['noplaylist'] = True # Search results are not playlists
             opts['extract_flat'] = False # Need full info for search results
             # Cannot download audio directly from text search results (requires URL first)
             if self.download_audio:
                 print("Warning: Download locale richiesto ma query è ricerca testuale. Verrà solo estratta l'informazione.")
                 self.download_audio = False
                 opts['skip_download'] = True


        # --- Configure MP3 Download ---
        if self.download_audio:
             opts['skip_download'] = False # Ensure download is enabled
             if not FFMPEG_PATH:
                  # FFmpeg not found, download best audio format but cannot convert
                  self.error_occurred.emit("Errore: FFmpeg non trovato. Impossibile convertire in MP3. Scarico nel formato audio migliore disponibile.")
                  # Keep the default outtmpl (will save as .webm, .m4a, etc.)
             else:
                  # FFmpeg found, configure for MP3 conversion
                  opts['outtmpl'] = str(DOWNLOAD_DIR / '%(extractor)s_%(id)s.%(ext)s') # Temp output
                  opts['postprocessors'] = [{
                       'key': 'FFmpegExtractAudio',
                       'preferredcodec': 'mp3',
                       'preferredquality': '192', # Adjust quality (e.g., '128', '320')
                       # Ensure final file is mp3, even if temporary was different
                       'nopostoverwrites': False,
                  },{
                       'key': 'EmbedThumbnail', # Embed thumbnail if downloaded
                  }]
                  opts['format'] = 'bestaudio/best' # Still request best audio source
                  opts['keepvideo'] = False # Don't keep original video/audio file after conversion

        # --- Start Processing ---
        self.progress_update.emit(f"Avvio {search_type_msg} per: \"{self.query[:50]}...\"")
        tracks = []
        try:
            # Create yt-dlp instance within the try block
            self._ydl = yt_dlp.YoutubeDL(opts)
            with self._ydl: # Use context manager for proper cleanup
                 if self._is_cancelled: return

                 # Use download=True only if we actually intend to download/convert
                 # Use download=False (simulate) if only getting info
                 should_download_flag = self.download_audio

                 self.progress_update.emit("Estrazione informazioni...")
                 # extract_info performs download/postprocessing if skip_download is False
                 info = self._ydl.extract_info(ytq, download=should_download_flag)

                 if self._is_cancelled:
                     self.results_ready.emit([])
                     return

                 if info is None:
                      # Check if cancelled during extraction
                      if self._is_cancelled: return
                      self.error_occurred.emit(f"Nessuna informazione estratta per \"{self.query}\". Potrebbe essere un URL non supportato, privato, con restrizioni geografiche, o un errore di rete.")
                      self.results_ready.emit([])
                      return

                 # --- Process results ---
                 entries_to_process = []
                 if 'entries' in info: # Playlist or search results
                     entries_to_process = info.get("entries", [])
                     # Filter out None entries which can occur with ignoreerrors=True
                     entries_to_process = [e for e in entries_to_process if e is not None]
                     if not is_url: # Limit results for text search
                          entries_to_process = entries_to_process[:self.num_results]
                 elif info: # Single video/item result
                     entries_to_process = [info]

                 self.progress_update.emit(f"Processando {len(entries_to_process)} risultati...")
                 time.sleep(0.1) # Brief pause for UI update

                 for i, entry in enumerate(entries_to_process):
                    if self._is_cancelled: break
                    if not entry: continue # Skip if entry is None or empty

                    # --- Extract details from the entry dictionary ---
                    title = entry.get("title", "Titolo Sconosciuto")
                    # Try different thumbnail keys yt-dlp might use
                    thumbnail_url = entry.get("thumbnail") or \
                                    (entry.get("thumbnails")[0].get("url") if entry.get("thumbnails") else None)
                    duration_sec = entry.get("duration", 0)
                    webpage_url = entry.get("webpage_url") or entry.get("original_url") # YouTube page etc.
                    video_id = entry.get("id")
                    extractor = entry.get("extractor_key", "Generic").lower()

                    # --- Determine URL/Path and is_local status ---
                    url_to_use = None
                    is_local_track = False
                    final_filepath = None # Store the path to the final downloaded/converted file

                    if self.download_audio:
                         # If download was successful, yt-dlp *should* add 'requested_downloads' or populate 'filepath'
                         # in the postprocessed entry. Let's check based on expected output.

                         # Construct expected filename based on whether conversion happened
                         expected_ext = '.mp3' if FFMPEG_PATH else '.' + entry.get('ext', 'unknown')
                         expected_filename = f"{entry.get('extractor','generic').lower()}_{video_id}{expected_ext}"
                         expected_path = DOWNLOAD_DIR / expected_filename

                         # Check if the expected file exists
                         if expected_path.exists():
                              final_filepath = expected_path
                         else:
                              # Fallback: Check if 'filepath' key exists (might point to temp before conversion)
                              # Or check 'requested_downloads' which contains info about the final file
                              req_downloads = entry.get('requested_downloads')
                              if req_downloads and isinstance(req_downloads, list) and req_downloads[0].get('filepath'):
                                   final_filepath = Path(req_downloads[0]['filepath'])
                              elif entry.get('filepath'): # Less reliable after postprocessing
                                   # Check if this path exists and has the right extension
                                   potential_path = Path(entry['filepath'])
                                   if potential_path.exists() and potential_path.suffix.lower() == expected_ext:
                                        final_filepath = potential_path


                         if final_filepath and final_filepath.exists():
                              url_to_use = str(final_filepath.resolve())
                              is_local_track = True
                              # Try to get duration from downloaded file's metadata if missing
                              if not duration_sec or duration_sec <= 0:
                                   duration_sec = entry.get('duration', 0) # Use original duration if possible
                              print(f"Download successful: {final_filepath.name}")
                         else:
                              # Download seems to have failed or file path is incorrect
                              print(f"Warning: Download/Conversion failed or final filepath missing for entry: {title}. Expected: {expected_path}. Falling back to stream URL if available.")
                              url_to_use = entry.get("url") # Stream URL (best available audio format)
                              is_local_track = False
                              if not url_to_use and webpage_url:
                                  print(f"Warning: Stream URL also missing for {title}, using webpage_url as last resort.")
                                  url_to_use = webpage_url # Last resort
                    else:
                         # Not downloading, just get the stream URL
                         url_to_use = entry.get("url") # Stream URL (best available audio format)
                         is_local_track = False
                         if not url_to_use and webpage_url:
                             print(f"Warning: Stream URL missing for {title}, using webpage_url as last resort.")
                             url_to_use = webpage_url # Last resort

                    # Ensure webpage_url is sensible (especially for YouTube)
                    if not webpage_url and video_id and extractor in ['youtube', 'youtubetab']:
                         webpage_url = f"https://www.youtube.com/watch?v={video_id}"

                    # Create Track object
                    track = Track(
                        url=url_to_use,
                        title=title,
                        thumbnail_url=thumbnail_url,
                        duration_sec=duration_sec or 0, # Ensure it's not None
                        is_local=is_local_track,
                        webpage_url=webpage_url
                    )

                    # Add track only if it has a valid URL or path
                    if track.url:
                         tracks.append(track)
                    else:
                         print(f"Avviso: Impossibile ottenere URL/path valido per '{track.title}'. Brano saltato.")


        except yt_dlp.utils.DownloadCancelled:
             print("YoutubeDL process explicitly cancelled by user.")
             self.results_ready.emit([]) # Emit empty list on cancellation
             return # Exit run method
        except yt_dlp.utils.ExtractorError as e:
             print(f"yt-dlp Extractor Error: {e}")
             self.error_occurred.emit(f"Errore estrattore yt-dlp: {e}. L'URL potrebbe essere errato, privato o non supportato.")
        except yt_dlp.utils.DownloadError as e:
             # This catches errors during download or postprocessing (like ffmpeg errors)
             print(f"yt-dlp Download/Conversion Error: {e}")
             # Try to provide a more specific error message
             error_msg = f"Errore download/conversione (yt-dlp): {e}. "
             if "ffmpeg" in str(e).lower():
                  error_msg += "Verifica che FFmpeg sia installato e nel PATH. "
             else:
                  error_msg += "Potrebbe essere un video non disponibile, protetto (DRM), con restrizioni, un errore di rete, o permessi mancanti nella cartella downloads."
             self.error_occurred.emit(error_msg)
        except Exception as exc:
            # Catch any other unexpected error during the process
            import traceback
            print(f"Errore generico in YoutubeSearchWorker: {exc}\n{traceback.format_exc()}")
            self.error_occurred.emit(f"Errore generico durante la ricerca/download: {exc}")
        finally:
            # Final check for cancellation before emitting results
            if self._is_cancelled:
                 print("Process finished after cancellation request.")
                 self.results_ready.emit([])
            else:
                 self.results_ready.emit(tracks) # Emit the collected tracks

            self.progress_update.emit("") # Clear progress label
            self._ydl = None # Clear reference to yt-dlp instance


class CoverDownloadWorker(QThread):
    """Worker thread for downloading a cover image and saving it to cache."""
    cover_ready = pyqtSignal(str) # Emits the path to the saved cover file
    cover_error = pyqtSignal()    # Emits on any error

    def __init__(self, url, save_path):
        super().__init__()
        self.url = url
        self.save_path = Path(save_path)
        self._is_cancelled = False

    def cancel(self):
        """Signals the worker to stop."""
        self._is_cancelled = True

    def run(self):
        """Downloads the image from URL and saves it."""
        if self._is_cancelled or not self.url or not str(self.url).startswith("http"):
            # print(f"Cover download cancelled or invalid URL: {self.url}") # Debug
            self.cover_error.emit()
            return

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8', # Accept various image types
                'Accept-Language': 'en-US,en;q=0.9',
            }
            # Use stream=True to avoid loading large images into memory at once
            response = requests.get(self.url, timeout=20, headers=headers, allow_redirects=True, stream=True)
            response.raise_for_status() # Check for HTTP errors (4xx, 5xx)

            # Check content type if possible
            content_type = response.headers.get('Content-Type', '').lower()
            if not content_type.startswith('image/'):
                 print(f"Warning: URL {self.url} did not return an image content type ({content_type}). Aborting download.")
                 response.close()
                 self.cover_error.emit()
                 return

            # Ensure target directory exists
            self.save_path.parent.mkdir(parents=True, exist_ok=True)

            # Download and save chunk by chunk
            try:
                with open(self.save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if self._is_cancelled:
                             print(f"Cover download cancelled during transfer: {self.url}")
                             response.close()
                             # Clean up partially downloaded file
                             if self.save_path.exists():
                                 try: self.save_path.unlink()
                                 except OSError: pass
                             self.cover_error.emit()
                             return
                        f.write(chunk)
            except IOError as e:
                 print(f"Error saving cover to {self.save_path}: {e}")
                 self.cover_error.emit()
                 return # Exit if saving fails
            finally:
                 response.close() # Ensure connection is closed

            # Check if cancelled immediately after loop
            if self._is_cancelled:
                 print(f"Cover download cancelled shortly after finishing transfer: {self.url}")
                 # Clean up the completed file if cancelled
                 if self.save_path.exists():
                     try: self.save_path.unlink()
                     except OSError: pass
                 self.cover_error.emit()
                 return

            # Success: emit the path
            # print(f"Cover downloaded successfully: {self.save_path}") # Debug
            self.cover_ready.emit(str(self.save_path))

        except requests.exceptions.Timeout:
             print(f"Timeout scaricando copertina: {self.url}")
             self.cover_error.emit()
        except requests.exceptions.RequestException as e:
            # Covers network errors, SSL errors, invalid URLs etc.
            print(f"Errore network scaricando copertina {self.url}: {e}")
            self.cover_error.emit()
        except Exception as e:
            # Catch any other unexpected error
            import traceback
            print(f"Errore generico durante download copertina {self.url}: {e}\n{traceback.format_exc()}")
            self.cover_error.emit()


class FileProbeWorker(QThread):
    """Worker thread to get the duration of a local media file using VLC."""
    probe_done = pyqtSignal(str, int) # Emits (path, duration_ms)

    def __init__(self, path):
        super().__init__()
        self.path = str(path) # Ensure path is a string
        self._is_cancelled = False
        self._local_vlc_instance = None
        self._media = None

    def cancel(self):
         """Signals the worker to stop."""
         self._is_cancelled = True
         # Release VLC resources if held
         if self._media:
             try: self._media.release()
             except Exception: pass
             self._media = None
         if self._local_vlc_instance:
             try: self._local_vlc_instance.release()
             except Exception: pass
             self._local_vlc_instance = None

    def run(self):
        """Probes the file for its duration."""
        duration_ms = 0
        try:
            if self._is_cancelled: return

            # Create a short-lived VLC instance for probing
            # Avoids potential conflicts with the main player instance
            self._local_vlc_instance = vlc.Instance(['--quiet', '--no-xlib' if sys.platform.startswith('linux') else ''])
            if not self._local_vlc_instance:
                 raise RuntimeError("Impossibile creare istanza VLC locale per probe.")

            if self._is_cancelled: return

            # Create media object from the file path
            self._media = self._local_vlc_instance.media_new_path(self.path)
            if not self._media:
                 raise RuntimeError(f"Impossibile creare media per il probe: {self.path}")

            # Asynchronously parse the media to get metadata like duration
            # Use flags to parse locally only, don't fetch network resources
            parse_flags = vlc.MediaParseFlag.parse_local | vlc.MediaParseFlag.do_not_fetch_network
            self._media.parse_with_options(parse_flags, 10000) # Timeout 10 seconds for parsing

            # Wait for parsing to complete or timeout/error
            parsed = False
            # Check more frequently for shorter period
            for _ in range(500): # Max ~5 seconds wait (500 * 0.01s)
                if self._is_cancelled: break
                state = self._media.get_state()
                # Parsing is done when state is Parsed or beyond (Playing, Paused etc.)
                if state >= vlc.State.Parsed:
                    parsed = True
                    break
                # Stop waiting if an error occurs or media stops unexpectedly
                if state in (vlc.State.Error, vlc.State.NothingSpecial, vlc.State.Ended, vlc.State.Stopped):
                     print(f"Warning: Media state became {state} during parse for {self.path}")
                     break
                time.sleep(0.01) # Small sleep to avoid busy-waiting

            if self._is_cancelled: return

            # If parsing completed successfully, get the duration
            if parsed:
                duration_ms = self._media.get_duration()
                if duration_ms is None or duration_ms <= 0:
                    # print(f"Warning: Parsed but got invalid duration ({duration_ms}) for {self.path}") # Debug
                    duration_ms = 0
                # else: # Debug
                    # print(f"Probe successful for {self.path}: {duration_ms} ms")
            else:
                print(f"Warning: Failed to parse media within timeout for {self.path}. State: {self._media.get_state()}")
                duration_ms = 0 # Indicate failure to get duration

        except Exception as e:
            print(f"Errore durante il probe del file {self.path}: {e}")
            duration_ms = 0 # Indicate failure
        finally:
            # --- Release VLC resources ---
            # Use temporary variables to avoid race conditions with cancel()
            media_to_release = self._media
            instance_to_release = self._local_vlc_instance
            self._media = None
            self._local_vlc_instance = None

            if media_to_release:
                try: media_to_release.release()
                except Exception as e_rel: print(f"Error releasing media for {self.path}: {e_rel}")
            if instance_to_release:
                 try: instance_to_release.release()
                 except Exception as e_rel: print(f"Error releasing local VLC instance for {self.path}: {e_rel}")
            # --- End Release VLC resources ---

            # Emit signal only if not cancelled
            if not self._is_cancelled:
                 self.probe_done.emit(self.path, duration_ms)

print("jukebox_workers.py loaded.")