/**
 * Dashboard Controller - Main UI logic
 */

// Initialize canvas controller
let canvas;
let currentSource = null;
let currentSourceType = 'file'; // 'file' or 'rtsp'

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    canvas = new CanvasController('layout-canvas');
    initializeUI();
    loadInitialData();
    startStatusPolling();
});

async function initializeUI() {
    // Source type toggle
    document.getElementById('source-type-file').addEventListener('click', () => {
        setSourceType('file');
    });
    
    document.getElementById('source-type-rtsp').addEventListener('click', () => {
        setSourceType('rtsp');
    });
    
    // Playback controls
    document.getElementById('play-btn').addEventListener('click', handlePlay);
    document.getElementById('pause-btn').addEventListener('click', handlePause);
    document.getElementById('stop-btn').addEventListener('click', handleStop);
    
    // Geometry controls
    document.getElementById('apply-geometry').addEventListener('click', handleApplyGeometry);
    
    // Manual geometry input changes
    ['geom-x', 'geom-y', 'geom-width', 'geom-height'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => {
            updateCanvasFromInputs();
        });
    });
    
    // Volume control
    const volumeSlider = document.getElementById('volume-slider');
    volumeSlider.addEventListener('input', (e) => {
        document.getElementById('volume-value').textContent = e.target.value;
    });
    volumeSlider.addEventListener('change', async (e) => {
        try {
            await apiClient.setVolume(parseInt(e.target.value));
        } catch (error) {
            showError('Failed to set volume: ' + error.message);
        }
    });
    
    // Seek controls
    document.getElementById('seek-back').addEventListener('click', async () => {
        try {
            await apiClient.seekRelative(-10);
        } catch (error) {
            showError('Seek failed: ' + error.message);
        }
    });
    
    document.getElementById('seek-forward').addEventListener('click', async () => {
        try {
            await apiClient.seekRelative(10);
        } catch (error) {
            showError('Seek failed: ' + error.message);
        }
    });
    
    const seekSlider = document.getElementById('seek-slider');
    seekSlider.addEventListener('change', async (e) => {
        try {
            const position = (parseFloat(e.target.value) / 100) * parseFloat(e.target.max);
            await apiClient.seek(position);
        } catch (error) {
            showError('Seek failed: ' + error.message);
        }
    });
    
    // Display resolution
    document.getElementById('update-resolution').addEventListener('click', handleUpdateResolution);
    
    // File upload
    document.getElementById('upload-btn').addEventListener('click', () => {
        document.getElementById('file-input').click();
    });
    
    document.getElementById('file-input').addEventListener('change', handleFileUpload);
    
    // Preset save
    document.getElementById('save-preset').addEventListener('click', handleSavePreset);
}

async function loadInitialData() {
    try {
        // Load files
        await loadFileList();
        
        // Load presets
        await loadPresets();
        
        // Load display resolution
        const resolution = await apiClient.getDisplayResolution();
        document.getElementById('display-width').value = resolution.width;
        document.getElementById('display-height').value = resolution.height;
        canvas.setDisplayResolution(resolution.width, resolution.height);
        
    } catch (error) {
        console.error('Failed to load initial data:', error);
    }
}

function setSourceType(type) {
    currentSourceType = type;
    
    // Update toggle buttons
    document.getElementById('source-type-file').classList.toggle('active', type === 'file');
    document.getElementById('source-type-rtsp').classList.toggle('active', type === 'rtsp');
    
    // Show/hide controls
    document.getElementById('source-file-controls').style.display = type === 'file' ? 'block' : 'none';
    document.getElementById('source-rtsp-controls').style.display = type === 'rtsp' ? 'block' : 'none';
}

async function handlePlay() {
    try {
        let source;
        
        if (currentSourceType === 'file') {
            source = document.getElementById('video-file').value;
            if (!source) {
                showError('Please select a video file');
                return;
            }
        } else {
            source = document.getElementById('rtsp-url').value.trim();
            if (!source) {
                showError('Please enter an RTSP URL');
                return;
            }
        }
        
        const loop = document.getElementById('loop-checkbox').checked;
        const volume = parseInt(document.getElementById('volume-slider').value);
        
        await apiClient.play(source, loop, volume);
        currentSource = source;
        
    } catch (error) {
        showError('Failed to start playback: ' + error.message);
    }
}

async function handlePause() {
    try {
        await apiClient.pause();
    } catch (error) {
        showError('Failed to pause: ' + error.message);
    }
}

async function handleStop() {
    try {
        await apiClient.stop();
        currentSource = null;
        document.getElementById('seek-section').style.display = 'none';
    } catch (error) {
        showError('Failed to stop: ' + error.message);
    }
}

async function handleApplyGeometry() {
    try {
        const x = parseInt(document.getElementById('geom-x').value);
        const y = parseInt(document.getElementById('geom-y').value);
        const width = parseInt(document.getElementById('geom-width').value);
        const height = parseInt(document.getElementById('geom-height').value);
        
        await apiClient.setGeometry(x, y, width, height);
        canvas.updateZone({ x, y, width, height });
        
    } catch (error) {
        showError('Failed to apply geometry: ' + error.message);
    }
}

function updateCanvasFromInputs() {
    const x = parseInt(document.getElementById('geom-x').value);
    const y = parseInt(document.getElementById('geom-y').value);
    const width = parseInt(document.getElementById('geom-width').value);
    const height = parseInt(document.getElementById('geom-height').value);
    
    canvas.updateZone({ x, y, width, height });
}

async function handleUpdateResolution() {
    try {
        const width = parseInt(document.getElementById('display-width').value);
        const height = parseInt(document.getElementById('display-height').value);
        
        await apiClient.setDisplayResolution(width, height);
        canvas.setDisplayResolution(width, height);
        
    } catch (error) {
        showError('Failed to update resolution: ' + error.message);
    }
}

async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const progressDiv = document.getElementById('upload-progress');
    const progressBar = document.getElementById('upload-progress-bar');
    const progressText = document.getElementById('upload-progress-text');
    
    try {
        progressDiv.style.display = 'block';
        progressBar.style.width = '0%';
        progressText.textContent = '0%';
        
        await apiClient.uploadFile(file, (percent) => {
            progressBar.style.width = percent + '%';
            progressText.textContent = Math.round(percent) + '%';
        });
        
        progressDiv.style.display = 'none';
        await loadFileList();
        
        // Clear file input
        e.target.value = '';
        
    } catch (error) {
        progressDiv.style.display = 'none';
        showError('Upload failed: ' + error.message);
    }
}

async function loadFileList() {
    try {
        const files = await apiClient.listFiles();
        
        // Update file select dropdown
        const select = document.getElementById('video-file');
        select.innerHTML = '<option value="">Select a video...</option>';
        files.forEach(file => {
            const option = document.createElement('option');
            option.value = file.name;
            option.textContent = file.name;
            select.appendChild(option);
        });
        
        // Update file list display
        const fileList = document.getElementById('file-list');
        fileList.innerHTML = '';
        
        files.forEach(file => {
            const item = createFileItem(file);
            fileList.appendChild(item);
        });
        
    } catch (error) {
        console.error('Failed to load file list:', error);
    }
}

function createFileItem(file) {
    const div = document.createElement('div');
    div.className = 'file-item';
    
    const info = document.createElement('div');
    info.className = 'file-info';
    
    const name = document.createElement('div');
    name.className = 'file-name';
    name.textContent = file.name;
    
    const size = document.createElement('div');
    size.className = 'file-size';
    size.textContent = formatFileSize(file.size);
    
    info.appendChild(name);
    info.appendChild(size);
    
    const actions = document.createElement('div');
    actions.className = 'file-actions';
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-danger btn-icon';
    deleteBtn.textContent = '🗑';
    deleteBtn.onclick = () => handleDeleteFile(file.name);
    
    actions.appendChild(deleteBtn);
    
    div.appendChild(info);
    div.appendChild(actions);
    
    return div;
}

async function handleDeleteFile(filename) {
    if (!confirm(`Delete ${filename}?`)) return;
    
    try {
        await apiClient.deleteFile(filename);
        await loadFileList();
    } catch (error) {
        showError('Failed to delete file: ' + error.message);
    }
}

async function loadPresets() {
    try {
        const response = await apiClient.listPresets();
        const presets = response.presets || response;
        const defaultPreset = response.default || null;
        
        // Update preset buttons
        const buttonContainer = document.getElementById('preset-buttons');
        buttonContainer.innerHTML = '';
        
        Object.keys(presets).forEach(name => {
            const btn = document.createElement('button');
            btn.className = 'btn btn-secondary';
            if (name === defaultPreset) {
                btn.className += ' btn-default';
                btn.textContent = `⭐ ${name}`;
            } else {
                btn.textContent = name;
            }
            btn.onclick = () => handleLoadPreset(name);
            buttonContainer.appendChild(btn);
        });
        
        // Update preset list
        const listContainer = document.getElementById('preset-list');
        listContainer.innerHTML = '';
        
        Object.entries(presets).forEach(([name, data]) => {
            const item = createPresetItem(name, data, name === defaultPreset);
            listContainer.appendChild(item);
        });
        
    } catch (error) {
        console.error('Failed to load presets:', error);
    }
}

function createPresetItem(name, data, isDefault = false) {
    const div = document.createElement('div');
    div.className = 'preset-item';
    if (isDefault) {
        div.className += ' preset-default';
    }
    
    const info = document.createElement('div');
    info.className = 'preset-info';
    
    const nameDiv = document.createElement('div');
    nameDiv.className = 'preset-name';
    nameDiv.textContent = isDefault ? `⭐ ${name} (Default)` : name;
    
    const desc = document.createElement('div');
    desc.className = 'preset-description';
    desc.textContent = data.description || 'No description';
    
    info.appendChild(nameDiv);
    info.appendChild(desc);
    
    const actions = document.createElement('div');
    actions.className = 'preset-actions';
    
    // Set as Default button
    const defaultBtn = document.createElement('button');
    defaultBtn.className = isDefault ? 'btn btn-secondary btn-icon' : 'btn btn-primary btn-icon';
    defaultBtn.textContent = isDefault ? '⭐' : '☆';
    defaultBtn.title = isDefault ? 'Clear default' : 'Set as default';
    defaultBtn.onclick = () => isDefault ? handleClearDefault() : handleSetDefault(name);
    
    const loadBtn = document.createElement('button');
    loadBtn.className = 'btn btn-success btn-icon';
    loadBtn.textContent = '📂';
    loadBtn.title = 'Load preset';
    loadBtn.onclick = () => handleLoadPreset(name);
    
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn btn-danger btn-icon';
    deleteBtn.textContent = '🗑';
    deleteBtn.title = 'Delete preset';
    deleteBtn.onclick = () => handleDeletePreset(name);
    
    actions.appendChild(defaultBtn);
    actions.appendChild(loadBtn);
    actions.appendChild(deleteBtn);
    
    div.appendChild(info);
    div.appendChild(actions);
    
    return div;
}

async function handleSavePreset() {
    const name = document.getElementById('preset-name').value.trim();
    if (!name) {
        showError('Please enter a preset name');
        return;
    }
    
    const description = document.getElementById('preset-description').value.trim();
    
    const geometry = {
        x: parseInt(document.getElementById('geom-x').value),
        y: parseInt(document.getElementById('geom-y').value),
        width: parseInt(document.getElementById('geom-width').value),
        height: parseInt(document.getElementById('geom-height').value)
    };
    
    try {
        await apiClient.savePreset(name, geometry, description);
        await loadPresets();
        
        // Clear inputs
        document.getElementById('preset-name').value = '';
        document.getElementById('preset-description').value = '';
        
    } catch (error) {
        showError('Failed to save preset: ' + error.message);
    }
}

async function handleLoadPreset(name) {
    try {
        const result = await apiClient.loadPreset(name);
        const geometry = result.geometry;
        
        // Update inputs
        document.getElementById('geom-x').value = geometry.x;
        document.getElementById('geom-y').value = geometry.y;
        document.getElementById('geom-width').value = geometry.width;
        document.getElementById('geom-height').value = geometry.height;
        
        // Update canvas
        canvas.updateZone(geometry);
        
    } catch (error) {
        showError('Failed to load preset: ' + error.message);
    }
}

async function handleDeletePreset(name) {
    if (!confirm(`Delete preset "${name}"?`)) return;
    
    try {
        await apiClient.deletePreset(name);
        await loadPresets();
    } catch (error) {
        showError('Failed to delete preset: ' + error.message);
    }
}

async function handleSetDefault(name) {
    try {
        await apiClient.setDefaultPreset(name);
        await loadPresets();
        showSuccess(`Set "${name}" as default preset`);
    } catch (error) {
        showError(`Failed to set default: ${error.message}`);
    }
}

async function handleClearDefault() {
    try {
        await apiClient.clearDefaultPreset();
        await loadPresets();
        showSuccess('Cleared default preset');
    } catch (error) {
        showError(`Failed to clear default: ${error.message}`);
    }
}

// Status polling
let statusInterval;

function startStatusPolling() {
    statusInterval = setInterval(updateStatus, 2000);
    updateStatus(); // Initial update
}

async function updateStatus() {
    try {
        const status = await apiClient.getStatus();
        
        // Update status indicator
        const indicator = document.getElementById('status-indicator');
        const text = document.getElementById('status-text');
        
        indicator.className = `status-${status.status}`;
        text.textContent = status.status.charAt(0).toUpperCase() + status.status.slice(1);
        
        // Show/hide seek controls
        if (status.status === 'playing' || status.status === 'paused') {
            document.getElementById('seek-section').style.display = 'block';
            
            // Update seek slider
            const seekSlider = document.getElementById('seek-slider');
            if (status.duration > 0) {
                seekSlider.max = status.duration;
                seekSlider.value = status.position;
            }
            
            // Update time display
            document.getElementById('current-time').textContent = formatTime(status.position);
            document.getElementById('duration-time').textContent = formatTime(status.duration);
        } else {
            document.getElementById('seek-section').style.display = 'none';
        }
        
    } catch (error) {
        console.error('Status update failed:', error);
    }
}

// Utility functions
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function formatTime(seconds) {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function showError(message) {
    alert(message); // Simple for now, could be improved with toast notifications
}
