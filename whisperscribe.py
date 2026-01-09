"""
Whisperscribe - Local voice transcription with hotkey trigger
Hold Ctrl+` to record, release to transcribe to clipboard
"""

import subprocess
import tempfile
import os
import wave
import threading
import json
import keyboard
import mouse
import sounddevice as sd
import numpy as np
import pyperclip
import tkinter as tk

# Configuration
WHISPER_CLI = r"c:\whisper\Release\whisper-cli.exe"
WHISPER_MODEL = r"c:\whisper\Release\ggml-small.en.bin"
SAMPLE_RATE = 16000
CHANNELS = 1


class ConfigManager:
    """Manages persistent configuration stored in config.json."""

    CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    DEFAULTS = {
        "hotkey": "ctrl+`",
        "settings_hotkey": "ctrl+shift+h"
    }

    def __init__(self):
        self.config = self.load()

    def load(self):
        """Load config from file, returning defaults if missing/invalid."""
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults for any missing keys
                    return {**self.DEFAULTS, **loaded}
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config: {e}")
        return self.DEFAULTS.copy()

    def save(self):
        """Save current config to file."""
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(self.config, f, indent=2)
        except IOError as e:
            print(f"Error saving config: {e}")

    def get(self, key):
        return self.config.get(key, self.DEFAULTS.get(key))

    def set(self, key, value):
        self.config[key] = value
        self.save()


class HotkeyManager:
    """Manages hotkey registration and dynamic updates."""

    MOUSE_BUTTONS = {'x', 'x2', 'left', 'right', 'middle'}
    KEYBOARD_MODIFIERS = {'ctrl', 'shift', 'alt'}

    def __init__(self, config_manager):
        self.config = config_manager
        self.keyboard_press_handler = None
        self.keyboard_release_handler = None
        self.mouse_handler = None
        self.settings_handler = None
        self._on_press = None
        self._on_release = None
        self._mouse_pressed = False

    def parse_hotkey(self, hotkey_str):
        """Parse hotkey string into (modifier_keys, trigger_key, is_mouse)."""
        parts = hotkey_str.lower().split('+')
        trigger_key = parts[-1]
        modifiers = [p for p in parts[:-1] if p in self.KEYBOARD_MODIFIERS]
        is_mouse = trigger_key in self.MOUSE_BUTTONS
        return modifiers, trigger_key, is_mouse

    def register_recording_hotkey(self, on_press, on_release):
        """Register the recording hotkey handlers."""
        self.unregister_recording_hotkey()

        self._on_press = on_press
        self._on_release = on_release

        hotkey = self.config.get("hotkey")
        modifiers, trigger_key, is_mouse = self.parse_hotkey(hotkey)

        def check_modifiers():
            if not modifiers:
                return True
            return all(keyboard.is_pressed(mod) for mod in modifiers)

        if is_mouse:
            # Mouse button trigger
            def mouse_callback(event):
                # Only handle ButtonEvent (not MoveEvent or WheelEvent)
                if not hasattr(event, 'button') or not hasattr(event, 'event_type'):
                    return

                if event.button != trigger_key:
                    return

                if event.event_type == 'down' and check_modifiers():
                    self._mouse_pressed = True
                    on_press()
                elif event.event_type == 'up' and self._mouse_pressed:
                    self._mouse_pressed = False
                    on_release()

            self.mouse_handler = mouse.hook(mouse_callback)
        else:
            # Keyboard trigger
            self.keyboard_press_handler = keyboard.on_press_key(
                trigger_key,
                lambda e: on_press() if check_modifiers() else None
            )
            self.keyboard_release_handler = keyboard.on_release_key(
                trigger_key,
                lambda e: on_release()
            )

    def unregister_recording_hotkey(self):
        """Remove existing recording hotkey handlers."""
        if self.keyboard_press_handler:
            try:
                keyboard.unhook(self.keyboard_press_handler)
            except (KeyError, ValueError):
                pass
            self.keyboard_press_handler = None
        if self.keyboard_release_handler:
            try:
                keyboard.unhook(self.keyboard_release_handler)
            except (KeyError, ValueError):
                pass
            self.keyboard_release_handler = None
        if self.mouse_handler:
            try:
                mouse.unhook(self.mouse_handler)
            except (KeyError, ValueError):
                pass
            self.mouse_handler = None
        self._mouse_pressed = False

    def register_settings_hotkey(self, callback):
        """Register the settings dialog hotkey."""
        settings_hotkey = self.config.get("settings_hotkey")
        self.settings_handler = keyboard.add_hotkey(
            settings_hotkey,
            callback
        )

    def update_recording_hotkey(self, new_hotkey, on_press, on_release):
        """Update the recording hotkey to a new value."""
        self.config.set("hotkey", new_hotkey)
        self.register_recording_hotkey(on_press, on_release)


class SettingsDialog:
    """Settings dialog for configuring hotkeys."""

    MOUSE_BUTTONS = {'x', 'x2', 'left', 'right', 'middle'}
    KEYBOARD_MODIFIERS = {'ctrl', 'shift', 'alt'}

    def __init__(self, root, config_manager, on_hotkey_changed):
        self.config = config_manager
        self.on_hotkey_changed = on_hotkey_changed
        self.parent_root = root
        self.dialog = None
        self.capturing = False
        self.captured_keys = set()
        self.captured_mouse_button = None
        self.keyboard_capture_handler = None
        self.mouse_capture_handler = None

    def show(self):
        """Show the settings dialog."""
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return

        self._create_dialog()

    def _create_dialog(self):
        """Create the settings dialog window."""
        self.dialog = tk.Toplevel(self.parent_root)
        self.dialog.title("Whisperscribe Settings")
        self.dialog.geometry("350x200")
        self.dialog.resizable(False, False)
        self.dialog.attributes('-topmost', True)

        # Center on screen
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 350) // 2
        y = (self.dialog.winfo_screenheight() - 200) // 2
        self.dialog.geometry(f"+{x}+{y}")

        # Current hotkey display
        frame = tk.Frame(self.dialog, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(frame, text="Recording Hotkey:", font=("Segoe UI", 10)).pack(anchor=tk.W)

        self.hotkey_label = tk.Label(
            frame,
            text=self.config.get("hotkey").upper(),
            font=("Segoe UI", 14, "bold"),
            fg="#1976d2"
        )
        self.hotkey_label.pack(anchor=tk.W, pady=(5, 15))

        # Capture button
        self.capture_btn = tk.Button(
            frame,
            text="Press to Set New Hotkey",
            command=self._start_capture,
            width=25,
            height=2
        )
        self.capture_btn.pack(pady=10)

        # Status label
        self.status_label = tk.Label(frame, text="", fg="#666666")
        self.status_label.pack()

        # Close button
        tk.Button(
            frame,
            text="Close",
            command=self._close,
            width=10
        ).pack(side=tk.BOTTOM, pady=10)

        self.dialog.protocol("WM_DELETE_WINDOW", self._close)

    def _start_capture(self):
        """Start capturing a new hotkey combination."""
        if self.capturing:
            return

        self.capturing = True
        self.captured_keys = set()
        self.captured_mouse_button = None
        self.capture_btn.config(text="Press key/mouse combo...", state=tk.DISABLED)
        self.status_label.config(text="Press keyboard combo or mouse button", fg="#666666")

        # Hook keyboard and mouse events
        self.keyboard_capture_handler = keyboard.hook(self._on_key_event)
        self.mouse_capture_handler = mouse.hook(self._on_mouse_event)

    def _on_key_event(self, event):
        """Handle keyboard events during capture."""
        if not self.capturing:
            return

        if event.event_type == keyboard.KEY_DOWN:
            self.captured_keys.add(event.name.lower())
        elif event.event_type == keyboard.KEY_UP:
            # Only finish on key up if we have a non-modifier key or mouse button
            has_trigger = self.captured_mouse_button or any(
                k not in self.KEYBOARD_MODIFIERS for k in self.captured_keys
            )
            if has_trigger:
                self._finish_capture()

    def _on_mouse_event(self, event):
        """Handle mouse events during capture."""
        if not self.capturing:
            return

        # Only handle ButtonEvent (not MoveEvent or WheelEvent)
        if not hasattr(event, 'button') or not hasattr(event, 'event_type'):
            return

        # Only capture side buttons and right click, not left click or movement
        if event.event_type == 'down' and event.button in ('x', 'x2', 'right', 'middle'):
            self.captured_mouse_button = event.button
            self._finish_capture()

    def _finish_capture(self):
        """Finalize the captured hotkey."""
        # Unhook handlers
        if self.keyboard_capture_handler:
            keyboard.unhook(self.keyboard_capture_handler)
            self.keyboard_capture_handler = None
        if self.mouse_capture_handler:
            mouse.unhook(self.mouse_capture_handler)
            self.mouse_capture_handler = None
        self.capturing = False

        # Build hotkey string (modifiers first, then trigger)
        captured_modifiers = sorted([k for k in self.captured_keys if k in self.KEYBOARD_MODIFIERS])
        captured_keyboard_keys = [k for k in self.captured_keys if k not in self.KEYBOARD_MODIFIERS]

        # Determine the trigger (mouse button or keyboard key)
        if self.captured_mouse_button:
            trigger = self.captured_mouse_button
        elif captured_keyboard_keys:
            trigger = captured_keyboard_keys[0]
        else:
            self._reset_capture("Please press a key or mouse button")
            return

        # For keyboard-only, require a modifier; for mouse, modifiers are optional
        if not self.captured_mouse_button and not captured_modifiers:
            self._reset_capture("Keyboard hotkeys need a modifier (Ctrl, Shift, Alt)")
            return

        # Build the hotkey string
        if captured_modifiers:
            new_hotkey = '+'.join(captured_modifiers + [trigger])
        else:
            new_hotkey = trigger

        # Apply the new hotkey
        self._apply_hotkey(new_hotkey)

    def _apply_hotkey(self, new_hotkey):
        """Apply the new hotkey."""
        self.hotkey_label.config(text=new_hotkey.upper())
        self.capture_btn.config(text="Press to Set New Hotkey", state=tk.NORMAL)
        self.status_label.config(text="Hotkey saved!", fg="#43a047")

        # Notify callback to re-register hotkeys (deferred to avoid unhooking during event)
        if self.on_hotkey_changed:
            self.parent_root.after(100, lambda: self.on_hotkey_changed(new_hotkey))

    def _reset_capture(self, error_msg):
        """Reset capture state with error message."""
        self.capture_btn.config(text="Press to Set New Hotkey", state=tk.NORMAL)
        self.status_label.config(text=error_msg, fg="#e53935")

    def _close(self):
        """Close the dialog."""
        if self.capturing:
            if self.keyboard_capture_handler:
                keyboard.unhook(self.keyboard_capture_handler)
                self.keyboard_capture_handler = None
            if self.mouse_capture_handler:
                mouse.unhook(self.mouse_capture_handler)
                self.mouse_capture_handler = None
            self.capturing = False
        if self.dialog:
            self.dialog.destroy()
            self.dialog = None


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

    def get_root(self):
        """Return the Tk root window for creating child dialogs."""
        return self.root

    def schedule(self, callback):
        """Schedule a callback to run on the Tk thread."""
        if self.root:
            self.root.after(0, callback)


# Global instances
config_manager = None
hotkey_manager = None
settings_dialog = None
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
    global status_indicator, config_manager, hotkey_manager, settings_dialog

    # Initialize configuration
    config_manager = ConfigManager()

    print("Whisperscribe - Local Voice Transcription")
    print(f"Hold {config_manager.get('hotkey').upper()} to record, release to transcribe")
    print(f"Press {config_manager.get('settings_hotkey').upper()} to open settings")
    print("Press Ctrl+C to exit\n")

    # Initialize status indicator
    status_indicator = StatusIndicator()

    # Initialize hotkey manager
    hotkey_manager = HotkeyManager(config_manager)

    # Callback for when hotkey changes
    def on_hotkey_changed(new_hotkey):
        print(f"Hotkey changed to: {new_hotkey.upper()}")
        hotkey_manager.update_recording_hotkey(
            new_hotkey,
            start_recording,
            stop_recording_and_transcribe
        )

    # Initialize settings dialog
    settings_dialog = SettingsDialog(
        status_indicator.get_root(),
        config_manager,
        on_hotkey_changed
    )

    # Function to show settings dialog on Tk thread
    def show_settings():
        status_indicator.schedule(settings_dialog.show)

    # Start audio stream
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype='float32',
        callback=audio_callback
    )

    with stream:
        # Register hotkeys
        hotkey_manager.register_recording_hotkey(
            start_recording,
            stop_recording_and_transcribe
        )
        hotkey_manager.register_settings_hotkey(show_settings)

        # Keep running
        keyboard.wait()


if __name__ == "__main__":
    main()
