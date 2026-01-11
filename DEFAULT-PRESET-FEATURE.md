# Default Preset Feature Implementation

## Overview
This feature allows users to set any preset as the "default" preset. When set, the default preset's geometry will automatically apply when playing any video (local file or RTSP stream).

## Backend Changes (✅ Complete)

### 1. preset_manager.py
**Added:**
- `self.default_preset` tracking
- `set_default(name)` - Set a preset as default
- `get_default()` - Get default preset geometry
- `get_default_name()` - Get name of default preset
- Updated `load_presets()` to handle `_default` key in JSON
- Updated `save_preset()` to persist default setting

### 2. video_controller.py
**Added:**
- Default geometry application in `api_play()` endpoint
- New endpoint: `POST /api/presets/<name>/set-default`
- New endpoint: `POST /api/presets/clear-default`
- Updated `GET /api/presets` to return `{"presets": {...}, "default": "name"}`

## Frontend Changes (⚠️ Needs Manual Implementation)

### 3. web/static/js/api-client.js
**Add methods:**
```javascript
async setDefaultPreset(name) {
    const response = await fetch(`/api/presets/${name}/set-default`, {
        method: 'POST'
    });
    return await response.json();
}

async clearDefaultPreset() {
    const response = await fetch('/api/presets/clear-default', {
        method: 'POST'
    });
    return await response.json();
}
```

### 4. web/static/js/dashboard.js

**Update `loadPresets()` function (line 315):**
```javascript
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
```

**Update `createPresetItem()` function (line 345):**
```javascript
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
```

**Add new handler functions (add after `handleDeletePreset`):**
```javascript
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
```

### 5. web/static/css/dashboard.css

**Add styling for default presets:**
```css
/* Default preset styling */
.btn-default {
    background: linear-gradient(135deg, var(--primary-color), var(--success-color));
    border-color: var(--primary-color);
    font-weight: bold;
}

.preset-default {
    border-left: 4px solid var(--primary-color);
    background: rgba(79, 172, 254, 0.1);
}

.preset-default .preset-name {
    font-weight: bold;
    color: var(--primary-color);
}
```

## How It Works

1. **User sets a preset as default:**
   - Click the ☆ button next to any preset
   - It becomes ⭐ and shows "(Default)"
   - The preset button at the top gets a star: "⭐ fullscreen"

2. **When playing a video:**
   - If a default preset is set, its geometry is automatically applied
   - User can manually change geometry after playback starts
   - Next video will again use the default preset

3. **Clearing default:**
   - Click the ⭐ button on the default preset
   - Or set a different preset as default (replaces the old one)

## API Endpoints

### Set Default
```
POST /api/presets/<name>/set-default
Response: {"status": "default set", "name": "fullscreen"}
```

### Clear Default
```
POST /api/presets/clear-default
Response: {"status": "default cleared"}
```

### List Presets (Updated)
```
GET /api/presets
Response: {
  "presets": {
    "fullscreen": {...},
    "top-half": {...}
  },
  "default": "fullscreen"
}
```

## Testing

1. Set "fullscreen" as default
2. Play a video - should automatically be fullscreen
3. Stop video
4. Play a different video - should again be fullscreen
5. Change geometry manually - works fine
6. Play another video - back to fullscreen (default)
7. Clear default
8. Play video - uses last geometry (no automatic change)

## Files Modified

Backend (✅ Complete):
- `src/preset_manager.py` - Default preset logic
- `src/video_controller.py` - API endpoints and auto-apply

Frontend (⚠️ Manual):
- `web/static/js/api-client.js` - Add 2 methods
- `web/static/js/dashboard.js` - Update 2 functions, add 2 handlers
- `web/static/css/dashboard.css` - Add 3 CSS rules

---

**Note:** Backend is complete and functional. Frontend changes need to be manually applied to the JavaScript and CSS files as shown above.
