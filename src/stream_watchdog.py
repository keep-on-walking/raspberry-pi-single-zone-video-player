#!/usr/bin/env python3
"""
Stream Watchdog - Monitors RTSP streams and auto-restarts on failure
Runs alongside the video player and automatically restarts streams when they die
"""

import subprocess
import time
import requests
import json
from pathlib import Path

# Configuration
API_URL = "http://localhost:5000"
CHECK_INTERVAL = 5  # Check every 5 seconds
LOG_FILE = Path("/opt/rpi-video-player/logs/watchdog.log")

def log(message):
    """Log messages with timestamp"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] {message}\n"
    print(log_message.strip())
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(log_message)
    except Exception as e:
        print(f"Failed to write to log: {e}")

def get_status():
    """Get current player status"""
    try:
        response = requests.get(f"{API_URL}/api/status", timeout=2)
        return response.json()
    except Exception as e:
        log(f"Failed to get status: {e}")
        return None

def is_rtsp_stream(source):
    """Check if source is an RTSP stream"""
    return source and source.startswith('rtsp://')

def restart_stream(source, loop=True, volume=50):
    """Restart the stream"""
    try:
        log(f"Restarting stream: {source}")
        response = requests.post(
            f"{API_URL}/api/play",
            json={"source": source, "loop": loop, "volume": volume},
            timeout=5
        )
        if response.status_code == 200:
            log("Stream restarted successfully")
            return True
        else:
            log(f"Failed to restart: HTTP {response.status_code}")
            return False
    except Exception as e:
        log(f"Failed to restart stream: {e}")
        return False

def main():
    """Main watchdog loop"""
    log("Stream Watchdog started")
    
    last_source = None
    last_loop = True
    last_volume = 50
    consecutive_failures = 0
    max_consecutive_failures = 3
    
    while True:
        try:
            status = get_status()
            
            if status:
                current_status = status.get('status')
                current_source = status.get('source')
                
                # Only monitor RTSP streams
                if is_rtsp_stream(current_source):
                    # Save stream info
                    last_source = current_source
                    last_loop = status.get('loop', True)
                    last_volume = status.get('volume', 50)
                    
                    # Check if stream died
                    if current_status == 'stopped':
                        consecutive_failures += 1
                        log(f"Stream stopped (failure {consecutive_failures}/{max_consecutive_failures})")
                        
                        if consecutive_failures >= max_consecutive_failures:
                            log(f"Stream failed {consecutive_failures} times, attempting restart...")
                            if restart_stream(last_source, last_loop, last_volume):
                                consecutive_failures = 0
                            else:
                                # Wait longer after failed restart
                                time.sleep(10)
                    else:
                        # Stream is playing, reset failure counter
                        if consecutive_failures > 0:
                            log("Stream recovered")
                        consecutive_failures = 0
                else:
                    # Not an RTSP stream, reset tracking
                    if last_source and is_rtsp_stream(last_source):
                        log("Stream changed to non-RTSP source, stopping monitoring")
                    last_source = None
                    consecutive_failures = 0
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            log("Watchdog stopped by user")
            break
        except Exception as e:
            log(f"Watchdog error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
