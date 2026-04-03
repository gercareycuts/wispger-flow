# WispGer Flow

Voice-to-text desktop app. Hold a hotkey, speak, release — your speech is transcribed and auto-pasted wherever your cursor is.

## Features

- **Hotkey recording** — Hold Ctrl+Win (Windows) or Ctrl+Cmd (Mac) to record
- **Fast cloud transcription** — Powered by Groq Whisper API
- **Smart cleanup** — Removes filler words, adds punctuation, fixes capitalization
- **Auto-paste** — Transcribed text is pasted at your cursor automatically
- **500ms pre-buffer** — Captures audio from just before you press the hotkey
- **Voice profile** — Learns your vocabulary to improve accuracy over time
- **Achievements** — Track your usage with fun milestones
- **Dark/light theme** — Customizable appearance

## Install (macOS)

### Option 1: Download the app (easiest)

1. Go to the [Actions tab](https://github.com/gercareycuts-maker/wispger-flow/actions) on GitHub
2. Click the latest successful build (green checkmark)
3. Scroll down to **Artifacts** and download **WispGer-Flow-macOS**
4. Unzip it — you'll get a `.dmg` file
5. Open the `.dmg` and drag **WispGer Flow** to your Applications folder
6. On first launch, right-click the app and select **Open** (macOS blocks unsigned apps by default)
7. You'll be asked for a [Groq API key](https://console.groq.com/keys) — it's free to sign up

### Option 2: Run from source

```bash
# Install Python 3.10+ if you don't have it
brew install python

# Clone the repo
git clone https://github.com/gercareycuts-maker/wispger-flow.git
cd wispger-flow

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

You'll need a [Groq API key](https://console.groq.com/keys) (free tier available).

## Install (Windows)

Same as macOS Option 1, but download **WispGer-Flow-Windows** from the Actions artifacts. Unzip and run `WispGer Flow.exe`.

## Usage

1. Press and hold **Ctrl+Win** (Windows) or **Ctrl+Cmd** (Mac)
2. Speak naturally
3. Release the keys
4. Your transcribed text is automatically pasted at your cursor

## Requirements

- A [Groq API key](https://console.groq.com/keys) (free)
- A microphone
- Windows 10+ or macOS 12+
