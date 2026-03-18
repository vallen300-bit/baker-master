# iOS Shortcuts — Ask Baker & Baker Vision

Two iOS Shortcuts that let you talk to Baker from anywhere on your iPhone.

## Prerequisites

- Baker URL: `https://baker-master.onrender.com`
- API Key: your Baker API key (X-Baker-Key header)

---

## Shortcut 1: Ask Baker

Ask Baker a question via text input or the share sheet.

### Setup in iOS Shortcuts App

1. Open **Shortcuts** app > tap **+** to create new
2. Name it **"Ask Baker"**
3. Add actions in this order:

**Action 1: Ask for Input**
- Type: Text
- Prompt: "What do you want to ask Baker?"
- (This is skipped when triggered from share sheet)

**Action 2: Get Contents of URL**
- URL: `https://baker-master.onrender.com/api/scan/quick`
- Method: POST
- Headers:
  - `X-Baker-Key`: your API key
  - `Content-Type`: `application/json`
- Request Body (JSON):
  - `message`: Shortcut Input (or the Ask for Input result)

**Action 3: Get Dictionary Value**
- Key: `response`

**Action 4: Show Result**
- Or use **Quick Look** / **Speak Text** for voice readback

### Share Sheet Setup
- Tap the **i** icon on the shortcut
- Enable **Show in Share Sheet**
- Accept types: **Text**
- Now you can select text anywhere, tap Share, and pick "Ask Baker"

### Siri Setup
- The shortcut name IS the Siri trigger
- Say "Hey Siri, Ask Baker" to activate

---

## Shortcut 2: Baker Vision

Send a photo to Baker for analysis.

### Setup in iOS Shortcuts App

1. Open **Shortcuts** app > tap **+** to create new
2. Name it **"Baker Vision"**
3. Add actions in this order:

**Action 1: Take Photo** (or **Select Photos**)
- Use "Take Photo" for camera, or "Select Photos" for library
- To support both: use **Choose from Menu** with "Camera" and "Photo Library" options

**Action 2: Get Contents of URL**
- URL: `https://baker-master.onrender.com/api/scan/image`
- Method: POST
- Headers:
  - `X-Baker-Key`: your API key
- Request Body: **Form**
  - `file`: the photo (Magic Variable from Action 1)
  - `question`: "What is this? Analyze it and tell me anything relevant."
  - (Or add an **Ask for Input** action to let you type a custom question)

**Action 3: Get Dictionary Value**
- Key: `answer`

**Action 4: Show Result**
- Or **Speak Text** for voice readback

### Share Sheet Setup
- Tap the **i** icon
- Enable **Show in Share Sheet**
- Accept types: **Images**
- Now you can share any photo to "Baker Vision"

---

## API Reference

### POST /api/scan/quick
Non-streaming text question. Returns within ~5-15 seconds.

```
POST /api/scan/quick
X-Baker-Key: <key>
Content-Type: application/json

{"message": "What meetings do I have today?"}
```

Response:
```json
{"response": "You have 3 meetings today...", "elapsed_s": 4.2}
```

### POST /api/scan/image
Image analysis via Claude Vision. Accepts multipart form.

```
POST /api/scan/image
X-Baker-Key: <key>
Content-Type: multipart/form-data

file: <image>
question: "What is this document?"
```

Response:
```json
{"answer": "This appears to be...", "model": "claude-haiku-4-5-20251001", "tokens": {"input": 1200, "output": 350}}
```

---

## Tips

- **Timeout**: iOS Shortcuts has a ~30s timeout. The quick endpoint uses single-pass RAG (no agent loop) to stay within this.
- **Automation**: You can trigger shortcuts from Automations (e.g., NFC tag tap, time of day).
- **Widget**: Add shortcuts to your home screen as widgets for one-tap access.
