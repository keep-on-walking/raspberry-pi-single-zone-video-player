/**
 * Canvas Controller - Interactive drag-and-drop zone positioning
 * Single-zone version with working corner resize handles
 */

class CanvasController {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        
        // Display resolution (actual output)
        this.displayWidth = 1920;
        this.displayHeight = 1080;
        
        // Canvas dimensions (UI representation)
        this.canvasWidth = this.canvas.width;
        this.canvasHeight = this.canvas.height;
        
        // Scale factor between canvas and display
        this.scale = this.canvasWidth / this.displayWidth;
        
        // Zone data (single zone)
        this.zone = { 
            x: 0, 
            y: 0, 
            width: 1920, 
            height: 1080, 
            color: '#3b82f6' 
        };
        
        // Interaction state
        this.dragging = false;
        this.resizing = null; // null or corner: 'tl', 'tr', 'bl', 'br'
        this.dragStart = { x: 0, y: 0 };
        this.zoneStart = { x: 0, y: 0, width: 0, height: 0 };
        
        // Resize handle size (large for easy grabbing)
        this.handleSize = 30;
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Initial render
        this.render();
    }
    
    setupEventListeners() {
        this.canvas.addEventListener('mousedown', (e) => this.handleMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this.handleMouseMove(e));
        this.canvas.addEventListener('mouseup', (e) => this.handleMouseUp(e));
        this.canvas.addEventListener('mouseleave', (e) => this.handleMouseUp(e));
        
        // Update cursor based on hover
        this.canvas.addEventListener('mousemove', (e) => this.updateCursor(e));
    }
    
    setDisplayResolution(width, height) {
        this.displayWidth = width;
        this.displayHeight = height;
        this.scale = this.canvasWidth / this.displayWidth;
        this.render();
    }
    
    updateZone(geometry) {
        this.zone = { ...this.zone, ...geometry };
        this.render();
    }
    
    getMousePos(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: (e.clientX - rect.left) / this.scale,
            y: (e.clientY - rect.top) / this.scale
        };
    }
    
    handleMouseDown(e) {
        const pos = this.getMousePos(e);
        
        // Check if clicking on resize handle
        const handle = this.getResizeHandle(this.zone, pos);
        if (handle) {
            this.resizing = handle;
            this.dragStart = pos;
            this.zoneStart = { ...this.zone };
            return;
        }
        
        // Check if clicking inside zone (for dragging)
        if (this.isInsideZone(this.zone, pos)) {
            this.dragging = true;
            this.dragStart = pos;
            this.zoneStart = { ...this.zone };
        }
    }
    
    handleMouseMove(e) {
        const pos = this.getMousePos(e);
        
        if (this.resizing) {
            // Resize from corner
            const dx = pos.x - this.dragStart.x;
            const dy = pos.y - this.dragStart.y;
            
            const newZone = { ...this.zoneStart };
            
            switch (this.resizing) {
                case 'tl': // Top-left
                    newZone.x = this.zoneStart.x + dx;
                    newZone.y = this.zoneStart.y + dy;
                    newZone.width = this.zoneStart.width - dx;
                    newZone.height = this.zoneStart.height - dy;
                    break;
                case 'tr': // Top-right
                    newZone.y = this.zoneStart.y + dy;
                    newZone.width = this.zoneStart.width + dx;
                    newZone.height = this.zoneStart.height - dy;
                    break;
                case 'bl': // Bottom-left
                    newZone.x = this.zoneStart.x + dx;
                    newZone.width = this.zoneStart.width - dx;
                    newZone.height = this.zoneStart.height + dy;
                    break;
                case 'br': // Bottom-right
                    newZone.width = this.zoneStart.width + dx;
                    newZone.height = this.zoneStart.height + dy;
                    break;
            }
            
            // Ensure minimum size
            newZone.width = Math.max(100, newZone.width);
            newZone.height = Math.max(100, newZone.height);
            
            // Ensure within display bounds
            newZone.x = Math.max(0, Math.min(this.displayWidth - newZone.width, newZone.x));
            newZone.y = Math.max(0, Math.min(this.displayHeight - newZone.height, newZone.y));
            
            this.zone = newZone;
            this.render();
            this.notifyGeometryChange();
            
        } else if (this.dragging) {
            // Move zone
            const dx = pos.x - this.dragStart.x;
            const dy = pos.y - this.dragStart.y;
            
            let newX = this.zoneStart.x + dx;
            let newY = this.zoneStart.y + dy;
            
            // Constrain to display bounds
            newX = Math.max(0, Math.min(this.displayWidth - this.zone.width, newX));
            newY = Math.max(0, Math.min(this.displayHeight - this.zone.height, newY));
            
            this.zone.x = newX;
            this.zone.y = newY;
            
            this.render();
            this.notifyGeometryChange();
        }
    }
    
    handleMouseUp(e) {
        this.dragging = false;
        this.resizing = null;
    }
    
    updateCursor(e) {
        if (this.dragging || this.resizing) {
            return; // Don't change cursor while actively dragging/resizing
        }
        
        const pos = this.getMousePos(e);
        const handle = this.getResizeHandle(this.zone, pos);
        
        if (handle) {
            // Set resize cursor based on corner
            const cursors = {
                'tl': 'nw-resize',
                'tr': 'ne-resize',
                'bl': 'sw-resize',
                'br': 'se-resize'
            };
            this.canvas.style.cursor = cursors[handle];
        } else if (this.isInsideZone(this.zone, pos)) {
            this.canvas.style.cursor = 'move';
        } else {
            this.canvas.style.cursor = 'default';
        }
    }
    
    getResizeHandle(zone, pos) {
        const corners = {
            tl: { x: zone.x, y: zone.y },
            tr: { x: zone.x + zone.width, y: zone.y },
            bl: { x: zone.x, y: zone.y + zone.height },
            br: { x: zone.x + zone.width, y: zone.y + zone.height }
        };
        
        const handleRadius = this.handleSize / this.scale;
        
        for (const [corner, point] of Object.entries(corners)) {
            const dist = Math.sqrt(
                Math.pow(pos.x - point.x, 2) + 
                Math.pow(pos.y - point.y, 2)
            );
            
            if (dist <= handleRadius) {
                return corner;
            }
        }
        
        return null;
    }
    
    isInsideZone(zone, pos) {
        return pos.x >= zone.x && 
               pos.x <= zone.x + zone.width &&
               pos.y >= zone.y && 
               pos.y <= zone.y + zone.height;
    }
    
    render() {
        // Clear canvas
        this.ctx.fillStyle = '#1e1e1e';
        this.ctx.fillRect(0, 0, this.canvasWidth, this.canvasHeight);
        
        // Draw grid
        this.drawGrid();
        
        // Draw zone
        this.drawZone(this.zone);
        
        // Draw info overlay
        this.drawInfo();
    }
    
    drawGrid() {
        const gridSize = 100 * this.scale; // 100px grid in display coordinates
        
        this.ctx.strokeStyle = '#333';
        this.ctx.lineWidth = 1;
        
        // Vertical lines
        for (let x = 0; x <= this.canvasWidth; x += gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvasHeight);
            this.ctx.stroke();
        }
        
        // Horizontal lines
        for (let y = 0; y <= this.canvasHeight; y += gridSize) {
            this.ctx.beginPath();
            this.ctx.moveTo(0, y);
            this.ctx.lineTo(this.canvasWidth, y);
            this.ctx.stroke();
        }
    }
    
    drawZone(zone) {
        const x = zone.x * this.scale;
        const y = zone.y * this.scale;
        const w = zone.width * this.scale;
        const h = zone.height * this.scale;
        
        // Draw zone rectangle
        this.ctx.fillStyle = zone.color + '40'; // 25% opacity
        this.ctx.fillRect(x, y, w, h);
        
        // Draw border
        this.ctx.strokeStyle = zone.color;
        this.ctx.lineWidth = 2;
        this.ctx.strokeRect(x, y, w, h);
        
        // Draw resize handles at corners
        this.drawHandle(x, y); // Top-left
        this.drawHandle(x + w, y); // Top-right
        this.drawHandle(x, y + h); // Bottom-left
        this.drawHandle(x + w, y + h); // Bottom-right
        
        // Draw label
        this.ctx.fillStyle = zone.color;
        this.ctx.font = 'bold 14px sans-serif';
        this.ctx.fillText(
            `VIDEO ZONE`,
            x + 10,
            y + 25
        );
        
        // Draw dimensions
        this.ctx.font = '12px monospace';
        this.ctx.fillText(
            `${Math.round(zone.width)}×${Math.round(zone.height)}`,
            x + 10,
            y + 45
        );
        this.ctx.fillText(
            `X:${Math.round(zone.x)} Y:${Math.round(zone.y)}`,
            x + 10,
            y + 60
        );
    }
    
    drawHandle(x, y) {
        const size = this.handleSize;
        
        // Draw handle circle
        this.ctx.fillStyle = '#fff';
        this.ctx.beginPath();
        this.ctx.arc(x, y, size / 2, 0, Math.PI * 2);
        this.ctx.fill();
        
        // Draw handle border
        this.ctx.strokeStyle = '#3b82f6';
        this.ctx.lineWidth = 2;
        this.ctx.stroke();
    }
    
    drawInfo() {
        // Draw resolution info
        this.ctx.fillStyle = '#fff';
        this.ctx.font = '12px monospace';
        this.ctx.fillText(
            `Display: ${this.displayWidth}×${this.displayHeight}`,
            10,
            this.canvasHeight - 30
        );
        this.ctx.fillText(
            'Drag zone to position • Drag corners to resize',
            10,
            this.canvasHeight - 10
        );
    }
    
    notifyGeometryChange() {
        // Notify the API client of geometry change
        if (window.apiClient) {
            window.apiClient.updateGeometryInputs(this.zone);
        }
    }
}
