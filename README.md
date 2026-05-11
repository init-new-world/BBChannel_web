# BBchannel Web PoC

This project is a Web proof of concept for the BBchannel automation stack. It starts with the device and recognition foundation: device capability checks, ADB connection, screenshots, manual taps/swipes, template matching, and event logs.

## Setup

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python -m webapp
```

Open the printed local URL in a browser.

## Scope

The PoC does not implement full battle automation. It is intended to validate the browser-to-local-device control path before porting BBchannel's higher-level scripts.

## Resources

Recognition resources are expected under `assets/`. Data files are expected under `data/`. The first implementation imports these from the parent BBchannel package directory.
