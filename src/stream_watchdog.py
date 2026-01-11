#!/usr/bin/env python3
"""
Stream Watchdog V2 - Monitors RTSP streams and auto-restarts on failure
Detects both stopped streams and frozen frames
"""

import subprocess
import time
import requests
import json
from pathlib import Path

# Configuration
API_URL = "http://localhost:5000"
CHECK_INTERVAL = 5  # Check every 5 seconds
FREEZE_THRESHOLD = 15  # Consider frozen if no position change for 15 seconds
MAX_RESTART_ATTEMPTS = 3  # Max consecutive restart attempts before giving up temporarily
BACKOFF_TIME = 60  # Wait 60 seconds after max attempts before trying again
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

def is_mpv_running():
    """Check if MPV process is running"""
    try:
        result = subprocess.run(['pgrep', '-f', 'mpv.*rtsp://'], 
                               capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except Exception as e:
        log(f"Failed to check MPV process: {e}")
        return False

def kill_mpv():
    """Force kill all MPV processes"""
    try:
        log("Force killing MPV processes...")
        subprocess.run(['pkill', '-9', 'mpv'], timeout=5)
        time.sleep(2)
        return True
    except Exception as e:
        log(f"Failed to kill MPV: {e}")
        return False

def restart_stream(source, loop=True, volume=50):
    """Restart the stream"""
    try:
        log(f"Restarting stream: {source}")
        
        # First, force kill any existing MPV
        kill_mpv()
        
        # Then restart via API
        response = requests.post(
            f"{API_URL}/api/play",
            json={"source": source, "loop": loop, "volume": volume},
            timeout=5
        )
        if response.status_code == 200:
            log("Stream restart command sent successfully")
            return True
        else:
            log(f"Failed to restart: HTTP {response.status_code}")
            return False
    except Exception as e:
        log(f"Failed to restart stream: {e}")
        return False

def main():
    """Main watchdog loop"""
    log("Stream Watchdog V2 started (with freeze detection)")
    
    last_source = None
    last_loop = True
    last_volume = 50
    last_position = None
    last_position_time = None
    consecutive_failures = 0
    restart_attempts = 0
    in_backoff = False
    backoff_until = None
    
    while True:
        try:
            # Check if we're in backoff period
            if in_backoff and backoff_until:
                if time.time() < backoff_until:
                    time.sleep(CHECK_INTERVAL)
                    continue
                else:
                    log("Backoff period ended, resuming monitoring")
                    in_backoff = False
                    restart_attempts = 0
            
            status = get_status()
            current_time = time.time()
            
            if status:
                current_status = status.get('status')
                current_source = status.get('source')
                current_position = status.get('position', 0)
                
                # Only monitor RTSP streams
                if is_rtsp_stream(current_source):
                    # Save stream info
                    last_source = current_source
                    last_loop = status.get('loop', True)
                    last_volume = status.get('volume', 50)
                    
                    needs_restart = False
                    restart_reason = ""
                    
                    # Check 1: Stream reported as stopped
                    if current_status == 'stopped':
                        consecutive_failures += 1
                        restart_reason = f"Stream stopped (failure {consecutive_failures})"
                        if consecutive_failures >= 2:  # Restart after 2 checks (10s)
                            needs_restart = True
                    
                    # Check 2: MPV process died
                    elif current_status == 'playing' and not is_mpv_running():
                        restart_reason = "MPV process died"
                        needs_restart = True
                    
                    # Check 3: Stream frozen (position not changing)
                    elif current_status == 'playing':
                        if last_position is not None and last_position_time is not None:
                            position_delta = abs(current_position - last_position)
                            time_delta = current_time - last_position_time
                            
                            # If position hasn't changed in FREEZE_THRESHOLD seconds
                            if position_delta < 0.1 and time_delta >= FREEZE_THRESHOLD:
                                restart_reason = f"Stream frozen ({int(time_delta)}s no progress)"
                                needs_restart = True
                        
                        # Update position tracking
                        if current_position != last_position:
                            last_position = current_position
                            last_position_time = current_time
                            consecutive_failures = 0  # Reset on successful playback
                    
                    # Perform restart if needed
                    if needs_restart:
                        log(restart_reason)
                        
                        # Check restart attempts
                        if restart_attempts >= MAX_RESTART_ATTEMPTS:
                            log(f"Max restart attempts ({MAX_RESTART_ATTEMPTS}) reached, entering backoff period")
                            in_backoff = True
                            backoff_until = current_time + BACKOFF_TIME
                            restart_attempts = 0
                            continue
                        
                        restart_attempts += 1
                        if restart_stream(last_source, last_loop, last_volume):
                            consecutive_failures = 0
                            last_position = None
                            last_position_time = None
                            time.sleep(5)  # Give stream time to start
                        else:
                            log(f"Restart attempt {restart_attempts} failed")
                            time.sleep(10)  # Wait longer after failed restart
                    else:
                        # Stream is healthy
                        if restart_attempts > 0:
                            log(f"Stream recovered after {restart_attempts} restart(s)")
                            restart_attempts = 0
                
                else:
                    # Not an RTSP stream, reset tracking
                    if last_source and is_rtsp_stream(last_source):
                        log("Stream changed to non-RTSP source, stopping monitoring")
                    last_source = None
                    last_position = None
                    last_position_time = None
                    consecutive_failures = 0
                    restart_attempts = 0
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            log("Watchdog stopped by user")
            break
        except Exception as e:
            log(f"Watchdog error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
