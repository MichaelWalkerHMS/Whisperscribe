"""
Whisperscribe - Local voice transcription with hotkey trigger
Hold Ctrl+` to record, release to transcribe to clipboard
"""

import subprocess
import tempfile
import os
import wave
import threading
import keyboard
import sounddevice as sd
import numpy as np
import pyperclip
import tkinter as tk

# Configuration
WHISPER_CLI = r"c:\whisper\Release\whisper-cli.exe"
WHISPER_MODEL = r"c:\whisper\Release\ggml-small.en.bin"
HOTKEY = "ctrl+`"
SAMPLE_RATE = 16000
CHANNELS = 1

# State
audio_buffer = []
is_recording = False


class StatusIndicator:
    """Floating status indicator that appears near the mouse cursor."""

    def __init__(self):
        self.root = None
        self.label = None
        self.ready = threading.Event()
        self._visible = False
        self._tracking = False
        self._start_tk_thread()
        self.ready.wait()  # Wait for Tk to initialize

    def _start_tk_thread(self):
        """Start Tkinter in a background thread."""
        thread = threading.Thread(target=self._run_tk, daemon=True)
        thread.start()

    def _run_tk(self):
        """Run the Tkinter main loop."""
        self.root = tk.Tk()
        self.root.overrideredirect(True)  # No window decorations
        self.root.attributes('-topmost', True)  # Always on top
        self.root.attributes('-alpha', 0.5)  # 50% transparent
        self.root.withdraw()  # Start hidden

        self.label = tk.Label(
            self.root,
            text="",
            font=("Segoe UI", 11, "bold"),
            padx=10,
            pady=5,
            relief="solid",
            borderwidth=1
        )
        self.label.pack()

        self.ready.set()  # Signal that Tk is ready
        self.root.mainloop()

    def _get_cursor_position(self):
        """Get current mouse cursor position."""
        return self.root.winfo_pointerx(), self.root.winfo_pointery()

    def _update_position(self):
        """Update window position to follow cursor."""
        if self._visible and self._tracking:
            x, y = self._get_cursor_position()
            self.root.geometry(f"+{x + 15}+{y + 15}")
            self.root.after(16, self._update_position)  # ~60fps

    def show(self, text, bg_color, fg_color="white", follow_cursor=True):
        """Show the indicator near the cursor."""
        if not self.root:
            return

        def _show():
            x, y = self._get_cursor_position()
            self.label.config(text=text, bg=bg_color, fg=fg_color)
            self.root.geometry(f"+{x + 15}+{y + 15}")
            self.root.deiconify()
            self.root.lift()
            self._visible = True
            if follow_cursor and not self._tracking:
                self._tracking = True
                self._update_position()

        self.root.after(0, _show)

    def hide(self):
        """Hide the indicator."""
        if not self.root:
            return

        def _hide():
            self._visible = False
            self._tracking = False
            self.root.withdraw()

        self.root.after(0, _hide)

    def show_recording(self):
        """Show recording state."""
        self.show("🎤 Recording...", "#e53935")  # Red

    def show_transcribing(self):
        """Show transcribing state."""
        self.show("⏳ Transcribing...", "#fb8c00")  # Orange

    def show_success(self, auto_hide_ms=1500):
        """Show success state, auto-hide after delay."""
        self.show("✓ Copied!", "#43a047")  # Green

        def _hide():
            self.hide()

        self.root.after(auto_hide_ms, _hide)

    def show_error(self, message="No speech", auto_hide_ms=2000):
        """Show error state, auto-hide after delay."""
        self.show(f"✗ {message}", "#757575")  # Gray

        def _hide():
            self.hide()

        self.root.after(auto_hide_ms, _hide)


# Global indicator instance
status_indicator = None


def start_recording():
    """Begin capturing audio from microphone."""
    global audio_buffer, is_recording
    if is_recording:
        return

    audio_buffer = []
    is_recording = True
    print("Recording... (release to transcribe)")
    if status_indicator:
        status_indicator.show_recording()


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
        if status_indicator:
            status_indicator.show_error("No audio")
        return

    print("Transcribing...")
    if status_indicator:
        status_indicator.show_transcribing()

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
            if status_indicator:
                status_indicator.show_success()
        else:
            print("No speech detected")
            if status_indicator:
                status_indicator.show_error("No speech")
            if result.stderr:
                print(f"Whisper stderr: {result.stderr[:200]}")

    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def main():
    """Main entry point."""
    global status_indicator

    print("Whisperscribe - Local Voice Transcription")
    print(f"Hold {HOTKEY.upper()} to record, release to transcribe")
    print("Press Ctrl+C to exit\n")

    # Initialize status indicator
    status_indicator = StatusIndicator()

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
