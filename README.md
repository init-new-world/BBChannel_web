# BBchannel Web PoC

This project is a Web proof of concept for the BBchannel automation stack. It starts with the device and recognition foundation: device capability checks, ADB connection, screenshots, manual taps/swipes, template matching, and event logs.

## Setup

```bash
python -m pip install -r requirements.txt
```

FastAPI and Uvicorn are required to run the local web server. OpenCV and NumPy are required for template matching. ADB is discovered from the parent BBchannel `adb/` directory or from `PATH`.

## Run

```bash
python -m webapp
```

Open `http://127.0.0.1:8000` in a browser.

## Verify

```bash
python -m pytest -q
node --check webapp/static/app.js
```

If optional runtime dependencies are missing, dependency-specific tests skip instead of failing. Install `requirements.txt` before running the server smoke test:

```bash
python -m webapp
```

Manual smoke steps:

1. Open `http://127.0.0.1:8000`.
2. Confirm `/api/health` returns `{"ok": true}`.
3. Confirm capabilities load for ADB and MuMu.
4. Connect an online ADB device or emulator.
5. Capture a screenshot, select a template, run match, send a tap, send a swipe, and check the event log.

## Scope

The PoC does not implement full battle automation. It is intended to validate the browser-to-local-device control path before porting BBchannel's higher-level scripts.

## Resources

Recognition resources are expected under `assets/`. Data files are expected under `data/`. The first implementation imports these from the parent BBchannel package directory.
