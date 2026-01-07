# Whisperscribe

Local voice transcription using Whisper.cpp. Hold a hotkey to record, release to transcribe directly to your clipboard.

## Features

- **Push-to-talk**: Hold `Ctrl+\`` to record, release to transcribe
- **Fully local**: All processing happens on your machine, no data leaves your device
- **Fast**: Uses Whisper.cpp small model for quick transcription
- **Clipboard output**: Transcription automatically copied to clipboard

## Prerequisites

- Python 3.8+
- [Whisper.cpp](https://github.com/ggml-org/whisper.cpp) installed at `c:\whisper`
- Whisper small model (`ggml-small.en.bin`) in the whisper Release folder

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/Whisperscribe.git
cd Whisperscribe

# Install dependencies
pip install -r requirements.txt
```

## Usage

```bash
# Run with admin privileges (required for global hotkeys)
python whisperscribe.py
```

1. Hold `Ctrl+\`` while speaking
2. Release to transcribe
3. Paste (`Ctrl+V`) anywhere

## Configuration

Edit the constants at the top of `whisperscribe.py`:

```python
WHISPER_CLI = r"c:\whisper\Release\whisper-cli.exe"
WHISPER_MODEL = r"c:\whisper\Release\ggml-small.en.bin"
HOTKEY = "ctrl+`"
```

## License

MIT
