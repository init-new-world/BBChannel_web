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

## ADB Discovery

The ADB backend first lists devices already known to `adb devices -l`. When auto discovery is enabled, it also probes a small set of common emulator endpoints, connects open ADB ports, then refreshes the device list. In WSL, `auto` hosts include the Windows host IP read from `/etc/resolv.conf`, which lets the server discover Windows-hosted emulators such as MuMu without hard-coding the host address.

Environment overrides:

```bash
BBCHANNEL_ADB_AUTO_CONNECT=1
BBCHANNEL_ADB_SCAN_HOSTS=auto
BBCHANNEL_ADB_SCAN_PORTS=5555,16384,7555,62001
BBCHANNEL_ADB_CONNECT_TIMEOUT_MS=300
BBCHANNEL_ADB_DISCOVERY_TTL_SECONDS=10
BBCHANNEL_ADB_ENRICH_DETAILS=1
```

For a MuMu instance exposed to WSL through the Windows host, `/api/devices` should return an ADB device id like `172.x.x.x:16384` with model, Android version, resolution, network, and root details.

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
