"""
Whisperscribe - Local voice transcription with hotkey trigger
Hold Ctrl+` to record, release to transcribe to clipboard
"""

import subprocess
import tempfile
import os
import wave
import keyboard
import sounddevice as sd
import numpy as np
import pyperclip

# Configuration
WHISPER_CLI = r"c:\whisper\Release\whisper-cli.exe"
WHISPER_MODEL = r"c:\whisper\Release\ggml-small.en.bin"
HOTKEY = "ctrl+`"
SAMPLE_RATE = 16000
CHANNELS = 1

# State
audio_buffer = []
is_recording = False


def start_recording():
    """Begin capturing audio from microphone."""
    global audio_buffer, is_recording
    if is_recording:
        return

    audio_buffer = []
    is_recording = True
    print("Recording... (release to transcribe)")


def audio_callback(indata, frames, time, status):
    """Callback for audio stream - buffers incoming audio."""
    if is_recording:
        audio_buffer.append(indata.copy())


def stop_recording_and_transcribe():
    """Stop recording, save audio, transcribe with Whisper."""
    global audio_buffer, is_recording
    if not is_recording:
        return

    is_recording = False

    if not audio_buffer:
        print("No audio recorded")
        return

    print("Transcribing...")

    # Combine audio chunks
    audio_data = np.concatenate(audio_buffer, axis=0)

    # Save to temp WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        temp_path = f.name

    try:
        # Write WAV file
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio_data * 32767).astype(np.int16).tobytes())

        # Run Whisper
        result = subprocess.run(
            [WHISPER_CLI, "-m", WHISPER_MODEL, "-f", temp_path, "-nt", "-np"],
            capture_output=True,
            text=True
        )

        # Extract transcription (skip empty lines)
        transcription = "\n".join(
            line.strip() for line in result.stdout.strip().split("\n")
            if line.strip()
        )

        if transcription:
            pyperclip.copy(transcription)
            print(f"Copied to clipboard: {transcription}")
        else:
            print("No speech detected")
            if result.stderr:
                print(f"Whisper stderr: {result.stderr[:200]}")

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    """Main entry point."""
    print("Whisperscribe - Local Voice Transcription")
    print(f"Hold {HOTKEY.upper()} to record, release to transcribe")
    print("Press Ctrl+C to exit\n")

    # Start audio stream
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype='float32',
        callback=audio_callback
    )

    with stream:
        # Register hotkey handlers
        keyboard.on_press_key("`", lambda e: start_recording() if keyboard.is_pressed("ctrl") else None)
        keyboard.on_release_key("`", lambda e: stop_recording_and_transcribe())

        # Keep running
        keyboard.wait()


if __name__ == "__main__":
    main()
