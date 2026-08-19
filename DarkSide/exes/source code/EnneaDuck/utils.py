"""
Utility functions for EnneaDuck application.
"""

import os
import wave
import array
import shutil
import tempfile
import logging
import requests
from typing import Optional, Tuple, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def setup_temp_directory() -> str:
    """Create and return a temporary directory for audio processing."""
    return tempfile.mkdtemp()

def cleanup_temp_directory(temp_dir: str) -> None:
    """Clean up temporary directory and its contents."""
    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        logger.error(f"Error cleaning up temp directory: {e}")

def adjust_audio_volume(audio_file: str, temp_dir: str, volume: float = 0.3) -> str:
    """
    Adjust the volume of a WAV file.
    
    Args:
        audio_file (str): Path to the WAV file
        temp_dir (str): Directory for temporary files
        volume (float): Volume level between 0.0 and 1.0
    
    Returns:
        str: Path to the volume-adjusted temporary file
    """
    try:
        temp_path = os.path.join(temp_dir, os.path.basename(audio_file))
        shutil.copy2(audio_file, temp_path)
        
        with wave.open(temp_path, 'rb') as wav_file:
            params = wav_file.getparams()
            frames = wav_file.readframes(wav_file.getnframes())
            frame_array = array.array('h', frames)
            
            for i in range(len(frame_array)):
                frame_array[i] = int(frame_array[i] * volume)
            
            with wave.open(temp_path, 'wb') as new_wav:
                new_wav.setparams(params)
                new_wav.writeframes(frame_array.tobytes())
        
        return temp_path
    except Exception as e:
        logger.error(f"Error adjusting volume: {e}")
        return audio_file

def verify_file_paths(paths: List[str]) -> List[str]:
    """
    Verify that files exist and return valid paths.
    
    Args:
        paths (List[str]): List of file paths to verify
    
    Returns:
        List[str]: List of valid file paths
    """
    return [path for path in paths if os.path.exists(path)]

def get_dark_joke() -> str:
    """
    Fetch a dark joke from the JokeAPI.
    
    Returns:
        str: A dark joke, or a default joke if the API call fails
    """
    try:
        response = requests.get("https://v2.jokeapi.dev/joke/Dark?type=single")
        if response.status_code == 200:
            return response.json()["joke"]
    except Exception as e:
        logger.error(f"Error fetching joke: {e}")
    
    return "Why did the duck cross the road? To prove he wasn't chicken!"

def calculate_window_position(screen_width: int, screen_height: int, 
                            window_width: int, window_height: int) -> Tuple[int, int]:
    """
    Calculate the center position for the window.
    
    Args:
        screen_width (int): Width of the screen
        screen_height (int): Height of the screen
        window_width (int): Width of the window
        window_height (int): Height of the window
    
    Returns:
        Tuple[int, int]: (x, y) coordinates for window position
    """
    x = (screen_width - window_width) // 2
    y = (screen_height - window_height) // 2
    return x, y

def log_position(x: float, y: float, mouse_x: float, mouse_y: float) -> None:
    """
    Log the current position of the duck and mouse.
    
    Args:
        x (float): Duck's x position
        y (float): Duck's y position
        mouse_x (float): Mouse's x position
        mouse_y (float): Mouse's y position
    """
    distance = ((mouse_x - x) ** 2 + (mouse_y - y) ** 2) ** 0.5
    logger.info(f"Position: Duck({int(x)}, {int(y)}), Mouse({int(mouse_x)}, {int(mouse_y)}), Distance: {distance:.1f}") 