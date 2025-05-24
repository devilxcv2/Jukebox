// Custom JavaScript for Jukebox Web App

// --- Global State ---
let currentPlayerStatus = null;
let statusIntervalId = null;

// --- API Helper ---
async function callPlayerApi(endpoint, method = 'GET', body = null) {
    const options = {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        },
    };
    if (body) {
        options.body = JSON.stringify(body);
    }
    try {
        const response = await fetch(endpoint, options);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ message: 'Errore HTTP generico' }));
            throw new Error(`Errore API (${response.status}): ${errorData.message || 'Dettagli non disponibili'}`);
        }
        const status = await response.json();
        console.log(`API ${method} ${endpoint} success:`, status);
        updatePlayerUI(status); // Update UI after every successful API call
        currentPlayerStatus = status; // Store the latest status
        return status;
    } catch (error) {
        console.error(`Errore chiamata API ${method} ${endpoint}:`, error);
        // Optionally, display a generic error message to the user on the UI
        // displayGlobalError(error.message);
        throw error; // Re-throw per permettere gestione specifica se serve
    }
}

// --- Player API Functions ---
async function playTrack(trackIndex = null) {
    const body = trackIndex !== null ? { track_index: trackIndex } : {};
    return callPlayerApi('/api/player/play', 'POST', body);
}

async function pauseTrack() {
    return callPlayerApi('/api/player/pause', 'POST');
}

async function nextTrack() {
    return callPlayerApi('/api/player/next', 'POST');
}

async function previousTrack() {
    return callPlayerApi('/api/player/previous', 'POST');
}

async function setVolume(volumeLevel) {
    // HTML range is 0-100. Backend API /api/player/volume expects 0-200.
    // For now, script.js sends 0-100, and backend /api/player/volume handles it.
    // If backend strictly needed 0-200, we would scale here: e.g. volumeLevel * 2
    return callPlayerApi('/api/player/volume', 'POST', { volume: parseInt(volumeLevel) });
}

async function getPlayerStatus() {
    // This function is called by polling, so direct UI update is good.
    // For user-initiated actions, the update is chained via .then(updatePlayerUI)
    try {
        const status = await callPlayerApi('/api/player/status', 'GET');
        // currentPlayerStatus is updated by callPlayerApi
    } catch (error) {
        console.error("Polling: Errore recupero stato player:", error);
        // Stop polling on error to prevent flooding, or implement backoff
        // if (statusIntervalId) clearInterval(statusIntervalId);
    }
}

// --- UI Update Function ---
function formatDurationMs(totalMilliseconds) {
    if (isNaN(totalMilliseconds) || totalMilliseconds === null || totalMilliseconds < 0) {
        return "0:00"; // Return 0:00 for invalid or zero duration
    }
    const totalSeconds = Math.floor(totalMilliseconds / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

function updatePlayerUI(status) {
    if (!status) {
        console.warn("updatePlayerUI chiamato con stato nullo o indefinito.");
        return;
    }
    currentPlayerStatus = status; // Update global state

    // Album Cover
    const albumCoverImg = document.getElementById('albumCoverImage');
    if (status.current_track && status.current_track.thumbnail_url) {
        albumCoverImg.src = status.current_track.thumbnail_url;
    } else {
        albumCoverImg.src = 'static/placeholder_cover.png';
    }

    // Track Info
    const trackTitleEl = document.getElementById('trackTitle');
    const trackArtistAlbumEl = document.getElementById('trackArtistAlbum');
    if (status.current_track) {
        trackTitleEl.textContent = status.current_track.title || 'Titolo Sconosciuto';
        // Assuming 'artist' and 'album' might not be separate fields in Track.to_dict()
        // For now, using is_local as a placeholder for artist/album line
        trackArtistAlbumEl.textContent = status.current_track.is_local ? 'File Locale' : 'Stream';
    } else {
        trackTitleEl.textContent = 'Nessun brano selezionato';
        trackArtistAlbumEl.textContent = '-';
    }

    // Play/Pause Button
    const playPauseButton = document.getElementById('playPauseButton');
    const icon = playPauseButton.querySelector('i');
    if (status.is_playing) {
        icon.classList.remove('bi-play-fill');
        icon.classList.add('bi-pause-fill');
        playPauseButton.childNodes[1].nodeValue = " Pausa"; // Update text node
    } else {
        icon.classList.remove('bi-pause-fill');
        icon.classList.add('bi-play-fill');
        playPauseButton.childNodes[1].nodeValue = " Play"; // Update text node
    }

    // Progress Bar & Time Labels
    const progressBarEl = document.getElementById('progressBarElement');
    const currentTimeLabelEl = document.getElementById('currentTimeLabel');
    const totalTimeLabelEl = document.getElementById('totalTimeLabel');

    const durationSec = status.duration_ms > 0 ? Math.floor(status.duration_ms / 1000) : 0;
    const currentTimeSec = status.current_time_ms > 0 ? Math.floor(status.current_time_ms / 1000) : 0;

    progressBarEl.max = durationSec;
    progressBarEl.value = currentTimeSec;
    progressBarEl.style.width = durationSec > 0 ? `${(currentTimeSec / durationSec) * 100}%` : '0%';
    progressBarEl.setAttribute('aria-valuenow', currentTimeSec);
    progressBarEl.setAttribute('aria-valuemax', durationSec);


    currentTimeLabelEl.textContent = formatDurationMs(status.current_time_ms);
    totalTimeLabelEl.textContent = formatDurationMs(status.duration_ms);

    // Volume Control
    const volumeControlEl = document.getElementById('volumeControl');
    // Backend volume is 0-200 (VLC default). HTML slider is 0-100.
    // The backend API for GET /status returns the VLC volume (0-200).
    // We need to scale this for our 0-100 slider.
    // When POSTing volume, the backend currently expects 0-100 and scales it.
    // Let's make it consistent: backend expects 0-100. Status returns 0-100.
    // For now, assuming backend status.volume is 0-100. If it's 0-200, divide by 2.
    // The backend was modified to expect 0-200 from API POST, and returns 0-200 in status.
    // So, script.js volume slider 0-100. Send as 0-100. Backend scales.
    // Status returns 0-200. Scale down for UI.
    volumeControlEl.value = status.volume; // Assuming status.volume is already 0-100 as per previous discussion.
                                          // If backend sends 0-200, this should be status.volume / 2.
                                          // Let's assume backend sends 0-100 for now based on `current_volume` init in app.py
                                          // The `player.audio_set_volume` in backend app.py takes 0-100.
                                          // The status._get_player_status returns current_volume (0-100).
                                          // So, this should be fine.
}


// --- Fetching and Rendering Data for Lists (Playlist, History, Favorites) ---
async function fetchDataForList(apiUrl, listName) {
    try {
        const response = await fetch(apiUrl);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status} for ${listName}`);
        return await response.json();
    } catch (error) {
        console.error(`Error fetching ${listName}:`, error);
        return [];
    }
}

function renderTracksToList(tracks, containerId, listName) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = '';
    if (!tracks || tracks.length === 0) {
        container.innerHTML = `<p class="text-muted">La lista ${listName} è vuota.</p>`;
        return;
    }
    const listGroup = document.createElement('div');
    listGroup.className = 'list-group';
    tracks.forEach((track, index) => { // Added index
        const item = document.createElement('a');
        item.href = "#";
        item.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center track-item';
        item.setAttribute('data-track-url', track.webpage_url || track.url); // Keep for reference
        item.setAttribute('data-track-index', index); // Store the index in the current list
        
        const trackInfo = document.createElement('div');
        trackInfo.innerHTML = `<h6 class="mb-1">${track.title || 'Titolo Sconosciuto'}</h6>
                               <small class="text-muted">${track.is_local ? 'File Locale' : 'Stream'}</small>`;
        const durationSpan = document.createElement('span');
        durationSpan.className = 'badge bg-primary rounded-pill';
        durationSpan.textContent = formatDurationMs(track.duration_sec * 1000); // formatDurationMs expects ms

        item.appendChild(trackInfo);
        item.appendChild(durationSpan);
        listGroup.appendChild(item);

        item.addEventListener('click', (e) => {
            e.preventDefault();
            const clickedIndex = parseInt(e.currentTarget.getAttribute('data-track-index'), 10);
            console.log(`Track clicked: ${track.title}, Index: ${clickedIndex}`);
            // Only call playTrack if the click is on an item in the 'playlist-content' tab
            if (containerId === 'playlist-content') {
                 playTrack(clickedIndex).catch(err => console.error("Errore durante playTrack da click:", err));
            } else {
                // For history/favorites, one might want to add to playlist then play, or just play directly if API supports it.
                // For now, let's assume direct play by index is for the main playlist.
                // A more complex behavior (e.g. "add to queue and play") could be added here.
                console.log(`Azione di play per ${listName} non implementata direttamente. Indice: ${clickedIndex}`);

            }
        });
    });
    container.appendChild(listGroup);
}

// --- DOMContentLoaded Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    // Fetch initial data for lists
    fetchDataForList('/api/playlist', 'Playlist').then(tracks => renderTracksToList(tracks, 'playlist-content', 'Playlist'));
    fetchDataForList('/api/history', 'History').then(tracks => renderTracksToList(tracks, 'history-content', 'Cronologia'));
    fetchDataForList('/api/favorites', 'Favorites').then(tracks => renderTracksToList(tracks, 'favorites-content', 'Preferiti'));

    // Get initial player status
    getPlayerStatus().catch(err => console.error("Errore recupero stato iniziale player:", err));

    // Start polling for player status
    statusIntervalId = setInterval(getPlayerStatus, 1000); // Poll every 1 second

    // --- Event Listeners for Player Controls ---
    const playPauseButton = document.getElementById('playPauseButton');
    const prevButton = document.getElementById('prevButton');
    const nextButton = document.getElementById('nextButton');
    const volumeControl = document.getElementById('volumeControl');
    const searchInput = document.getElementById('searchInput'); // Keep for completeness
    const searchButton = document.getElementById('searchButton'); // Keep for completeness

    if (playPauseButton) {
        playPauseButton.addEventListener('click', () => {
            if (currentPlayerStatus && currentPlayerStatus.is_playing) {
                pauseTrack().catch(err => console.error("Errore Pausa:", err));
            } else {
                // If a track is loaded (current_track_index != -1), play it. Otherwise, play index 0.
                const trackIdxToPlay = (currentPlayerStatus && currentPlayerStatus.current_track_index !== -1) ? currentPlayerStatus.current_track_index : 0;
                playTrack(trackIdxToPlay).catch(err => console.error("Errore Play:", err));
            }
        });
    }

    if (prevButton) {
        prevButton.addEventListener('click', () => previousTrack().catch(err => console.error("Errore Precedente:", err)));
    }

    if (nextButton) {
        nextButton.addEventListener('click', () => nextTrack().catch(err => console.error("Errore Successivo:", err)));
    }

    if (volumeControl) {
        volumeControl.addEventListener('input', (event) => {
            setVolume(event.target.value).catch(err => console.error("Errore Impostazione Volume:", err));
        });
    }
    
    // Keep existing search listeners (no change from previous subtasks)
    if (searchButton && searchInput) {
        searchButton.addEventListener('click', () => {
            const searchTerm = searchInput.value;
            console.log(`Search button clicked. Query: "${searchTerm}" (placeholder - search logic not part of this subtask)`);
            // Actual search implementation would go here or be called from here
        });
        searchInput.addEventListener('keypress', (event) => {
            if (event.key === 'Enter') {
                console.log(`Search initiated by Enter key. Query: "${searchInput.value}" (placeholder)`);
                searchButton.click();
            }
        });
    }
});

// Cleanup polling on window unload (optional, good practice)
window.addEventListener('beforeunload', () => {
    if (statusIntervalId) {
        clearInterval(statusIntervalId);
    }
});

```
