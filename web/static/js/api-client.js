/**
 * API Client - Handles all HTTP requests to the video player API
 */

class APIClient {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }
    
    // Player control
    async play(source, loop = true, volume = 50) {
        return this.post('/api/play', { source, loop, volume });
    }
    
    async stop() {
        return this.post('/api/stop');
    }
    
    async pause() {
        return this.post('/api/pause');
    }
    
    async seek(position) {
        return this.post('/api/seek', { position });
    }
    
    async seekRelative(seconds) {
        return this.post('/api/seek-relative', { seconds });
    }
    
    async setVolume(volume) {
        return this.post('/api/volume', { volume });
    }
    
    async setGeometry(x, y, width, height) {
        return this.post('/api/geometry', { x, y, width, height });
    }
    
    async getStatus() {
        return this.get('/api/status');
    }
    
    // Display resolution
    async setDisplayResolution(width, height) {
        return this.post('/api/display/resolution', { width, height });
    }
    
    async getDisplayResolution() {
        return this.get('/api/display/resolution');
    }
    
    // Presets
    async listPresets() {
        return this.get('/api/presets');
    }
    
    async savePreset(name, geometry, description = '') {
        return this.post('/api/presets', { name, geometry, description });
    }
    
    async loadPreset(name) {
        return this.post(`/api/presets/${name}/load`);
    }
    
    async deletePreset(name) {
        return this.delete(`/api/presets/${name}`);
    }
    
    async setDefaultPreset(name) {
        return this.post(`/api/presets/${name}/set-default`);
    }
    
    async clearDefaultPreset() {
        return this.post('/api/presets/clear-default');
    }
    
    // File management
    async listFiles() {
        return this.get('/api/files');
    }
    
    async uploadFile(file, onProgress = null) {
        const formData = new FormData();
        formData.append('file', file);
        
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            
            if (onProgress) {
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = (e.loaded / e.total) * 100;
                        onProgress(percent);
                    }
                });
            }
            
            xhr.addEventListener('load', () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        resolve(JSON.parse(xhr.responseText));
                    } catch (e) {
                        resolve({ status: 'ok' });
                    }
                } else {
                    reject(new Error(`Upload failed: ${xhr.status}`));
                }
            });
            
            xhr.addEventListener('error', () => {
                reject(new Error('Upload failed'));
            });
            
            xhr.open('POST', `${this.baseUrl}/api/upload`);
            xhr.send(formData);
        });
    }
    
    async deleteFile(filename) {
        return this.delete(`/api/files/${filename}`);
    }
    
    // Helper methods
    async get(endpoint) {
        const response = await fetch(`${this.baseUrl}${endpoint}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
    }
    
    async post(endpoint, data = {}) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(data)
        });
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || `HTTP ${response.status}`);
        }
        return response.json();
    }
    
    async delete(endpoint) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'DELETE'
        });
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        return response.json();
    }
    
    // UI helper methods
    updateGeometryInputs(geometry) {
        document.getElementById('geom-x').value = Math.round(geometry.x);
        document.getElementById('geom-y').value = Math.round(geometry.y);
        document.getElementById('geom-width').value = Math.round(geometry.width);
        document.getElementById('geom-height').value = Math.round(geometry.height);
    }
}

// Make available globally
window.apiClient = new APIClient();
