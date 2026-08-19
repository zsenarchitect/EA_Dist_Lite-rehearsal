import wave
import struct
import math
import os

def create_beep(filename, frequency=440, duration=0.1, volume=0.5):
    """Create a simple beep sound"""
    # Audio parameters
    sample_rate = 44100
    num_samples = int(sample_rate * duration)
    
    # Create audio data
    audio_data = []
    for i in range(num_samples):
        t = float(i) / sample_rate
        # Simple sine wave with exponential decay
        sample = volume * math.sin(2.0 * math.pi * frequency * t) * math.exp(-4 * t)
        audio_data.append(struct.pack('h', int(32767 * sample)))
    
    # Write to WAV file
    with wave.open(filename, 'wb') as wav_file:
        # Set parameters
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 2 bytes per sample
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b''.join(audio_data))

def main():
    # Create sounds directory if it doesn't exist
    sounds_dir = os.path.join(os.path.dirname(__file__), "assets", "sounds")
    os.makedirs(sounds_dir, exist_ok=True)
    
    # Create different sound effects
    create_beep(os.path.join(sounds_dir, "talk.wav"), frequency=880, duration=0.1)  # High-pitched short beep
    create_beep(os.path.join(sounds_dir, "walk.wav"), frequency=440, duration=0.05)  # Mid-pitched very short beep
    create_beep(os.path.join(sounds_dir, "steal.wav"), frequency=220, duration=0.2)  # Low-pitched longer beep

if __name__ == "__main__":
    main()
    print("Sound effects created in assets/sounds folder") 