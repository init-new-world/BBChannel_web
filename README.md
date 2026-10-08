# BBchannel Web PoC

This project is a local Web interface for the BBchannel automation stack. It includes device control, visual recognition, script editing, battle execution, and several event workflows. The port remains experimental: automated fixture tests do not replace verification on the target emulator, game server, and screen layout.

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

The default server binds only to loopback. Keep it local: device-control and automation endpoints are not intended for unauthenticated public access. Job state is stored in `runtime/bbchannel.db`; set `BBCHANNEL_RUNTIME_DB` to use another SQLite database.

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
node --check webapp/static/preset-team.js
node --check webapp/static/preset-assist.js
node --check webapp/static/preset-equips.js
```

If optional runtime dependencies are missing, dependency-specific tests skip instead of failing. Install `requirements.txt` before running the server smoke test:

```bash
python -m webapp
```

Browser regression tests are optional and use isolated temporary data plus a simulated device. Install Playwright and point the test runner at a local Chromium or Google Chrome executable:

```bash
python -m pip install playwright
BBCHANNEL_TEST_CHROMIUM=/path/to/chromium python -m pytest -q tests/test_assist_tags_browser.py tests/test_command_tags_browser.py tests/test_strategy_entries_browser.py tests/test_strategy_assignment_browser.py tests/test_turn_np_browser.py tests/test_script_waves_browser.py tests/test_run_options_browser.py tests/test_team_editor_browser.py tests/test_master_editor_browser.py tests/test_assist_options_browser.py tests/test_assist_equips_browser.py
```

Manual smoke steps:

1. Open `http://127.0.0.1:8000`.
2. Confirm `/api/health` returns `{"ok": true}`.
3. Confirm capabilities load for ADB and MuMu.
4. Connect an online ADB device or emulator.
5. Capture a screenshot, select a template, run match, send a tap, send a swipe, and check the event log.
6. Import or edit a script and inspect its validation and compiled-program status before executing it.
7. Check assist recognition and the intended starting screen, then run a single battle with supervision before enabling repeated runs.

## Scope

Implemented workflows include:

- Device discovery and connection, normalized screenshots, manual taps/swipes, template matching, and diagnostic jobs.
- Script and strategy editing, JSON import/export, validation, compiled-program inspection, and dry runs.
- Battle entry, support selection, team checks, skills, command-card strategies, result handling, repeated runs, and bounded crash or frozen-screen recovery.
- Assist filters for servant/CE identity, limit break, friendship, NP and servant level, main and append skill levels, custom tags, NP color, and Olga form.
- CE template creation and inventory management, plus a visual custom-tag crop/import/binding tool.
- Lottery, Valentine exchange, excavation, and supported EXP-material workflows, with job history, progress events, pause/resume, and cancellation.
- Material drop queries from the bundled data and a local notebook.

Execution is rejected when a script fails validation or contains unsupported compiled actions. Recognition-dependent behavior still requires suitable assets and a compatible device layout; this project does not claim complete parity with every original-client function or every live game screen.

### Assist Skills

`skillsLevel` stores three main skills followed by up to five append skills. Each entry is an integer from `0` to `10`; `0` means no requirement and positive values are minimum levels. The current CNTW layout supports three append slots. Nonzero requirements for its fourth or fifth append slot are rejected rather than ignored.

The script editor's numeric controls stay synchronized with its JSON editor. Append filtering verifies the skill display, checks each requested slot, restores the main view, and rechecks the candidate before selection. The full-run NP color/Olga filter is a per-run option and does not change the saved script.

### Card Recovery

Command-card strategies exclude face cards with recognized action-blocking status text. If a selection containing Noble Phantasms leaves the command-card back button visible, the runner checks the selected NP cards for sealing or immobilization. Confirmed unavailable NPs are excluded when the runner returns to battle and reopens card selection. This applies to direct selection, strategies, no-chain selection, and extra turns; unavailable positions are tracked only for that turn and allow at most three recovery cycles.

The runner does not infer NP availability from an unrecognized gauge. It also does not retry when the back button has disappeared or when no selected NP has a recognized blocking status. Returning to battle must be confirmed before another attack tap is sent.

## Resources

Recognition resources are expected under `assets/`, and data files under `data/`. Populate them from the BBchannel package when setting up a fresh checkout. Scripts live in `data/settings/` and strategies in `data/strategy/`.

Custom assist tags live in `assets/assist/assist_tags/`. Their PNG filenames encode the source dimensions, crop offsets, and confidence threshold. A tag referenced by a script cannot be deleted until it is unbound; missing or inconsistent tag images fail script validation.

Custom command-card tags in `specialKeys` use their filename's source dimensions and card-local crop bounds during recognition. The search region keeps the original client's animation tolerance and stays inside each card. Strategy preferences such as `S0` refer to the tag's index in `specialKeys`. Invalid metadata or missing/inconsistent images fail script validation.

The Tag Maker's **Command Cards** tab captures a normalized 1280x720 screenshot and restricts crops to the selected card. It stores PNGs under `assets/battle/customCommandCard/` and supports import, preview, and script binding. Imported original-client PNGs keep their filename metadata. New bindings append an `S` index; unbinding is allowed only for the last entry when no embedded strategy in that script references it. Existing indices are never silently renumbered. Removing an image is blocked while any script still references it. Switching tag modes clears the capture and ignores responses belonging to the previous mode.

Strategy preferences accept ordinary card codes (`1B`), tag-only codes (`S0`), and combined codes (`1BS0`). Selection tries alternative matching cards when an earlier preference prevents a complete three-card assignment. The two `breakpoint` booleans require different servants across the first/second and second/third face-card boundaries respectively; a boundary involving a Noble Phantasm is exempt.

The strategy editor exposes each card's type, ordered preferences, and minimum/maximum critical-star threshold. Controls preserve unrelated JSON fields and other entries. Invalid control drafts remain visible across unrelated changes and prevent saving, including when the invalid draft belongs to another entry. Editing raw JSON replaces the control drafts. Strategy files and embedded script strategies reject invalid types, preference codes, star thresholds outside `0` through `10`, and non-boolean comparison values.

New strategy presets start with one editable entry. Entries can be added, duplicated, renamed, reordered, and deleted without editing JSON. Reordering preserves both extension fields and invalid input drafts; duplicating copies the entry and its drafts, while deletion discards only that entry's drafts. The editor does not write the preset file until Save. Local toolbar icons come from Lucide Static 1.43.0; their license is included in `webapp/static/icons/LICENSE.txt`.

The script editor's Turn Strategy controls apply a saved strategy preset to a regular turn or a wave's extra turns. Applying copies all strategy entries in order, including extension fields, without linking future preset edits to that script. Replacing or clearing existing strategies requires confirmation; clearing leaves an empty strategy array so turns inferred from legacy keys are retained. Changes remain in the editor until Save. Loading a preset locks strategy actions and Save, rejects responses for a changed JSON draft, and ignores responses after the editor is closed. The turn selector refuses lists above 1,000 entries without changing the source JSON.

Regular turns also expose an ordered list of up to three Noble Phantasms. Selecting an NP already in the sequence exchanges positions; choosing None removes that slot and compacts the sequence. These selections are preselected before command-card strategy evaluation. The controls preserve other turns and raw extension fields. Malformed sequences remain unchanged until explicitly cleared, and clearing keeps the empty NP array so inferred turns are retained. NP editing is unavailable for extra turns or during a pending preset load or save. Save and Cancel remain visible at the bottom of the scrollable editor.

The collapsible Waves section can append waves and turns without editing JSON. A new wave starts with one turn. Removing a turn deletes only the last turn of its wave, including extension fields under that turn's key prefix; deleting a wave is allowed only for the highest-numbered wave and removes that wave's fields after confirmation. Other wave numbers and fields are never renumbered or rewritten. Counts include turns inferred from existing script fields. An empty script opens this section automatically; existing nonempty scripts keep it collapsed. Structural editing is disabled for noncanonical round/turn keys, invalid declared counts, or lists exceeding 1,000 waves or 1,000 selectable turn entries. All changes stay in the draft until Save, and wave controls are locked during preset loads and saves.

Run Options exposes the script's single-NP no-chain preference (`noChain`), crash recovery (`gameCrushRestart`), and frozen-screen recovery (`stuckRestart`). The no-chain preference applies to default command selection with one preselected NP and no explicit card strategy. The frozen-screen check interval accepts numeric values from 1 through 600 seconds, including fractions, and defaults to 30 when absent. Invalid interval drafts survive unrelated edits and keep blocking Save even after the watchdog is switched off; saving opens the section to show the invalid field. Editing raw JSON or canceling the editor discards these control drafts. Recovery still uses the existing per-run restart bound and requires compatible device assets and screens.

Run Options also exposes randomized tap positions (`randomTouch`) and an added random wait of 0 through 10 seconds (`randomTime`). The wait can be fractional and defaults to zero when absent. Existing truthy checkbox values and numeric values stay unchanged until edited. Invalid or incomplete wait drafts survive unrelated controls and block Save until corrected; malformed source values remain in JSON until explicitly replaced.

Team exposes six servant slots using the script server's local servant catalog, plus the assist slot. Selecting None clears only that servant name; selecting Not set removes only `assistIdx`, without moving servants or changing `usedServant`. Existing aliases, unknown names, and malformed fields remain unchanged until explicitly replaced. Catalog loading never changes the JSON draft, and responses from an older server selection or closed editor are ignored. A failed catalog load can be retried and does not block unrelated editing or Save. Team controls lock during a preset application or save; all team changes stay in the draft until Save.

Team also selects a master outfit from `master_info.json`. Choosing an outfit writes its catalog `SN` to `master_equip`, preserving numeric zero and string identifiers with leading zeroes; choosing None removes that field. Existing identifier types and unknown, empty, or null values remain unchanged until explicitly replaced. Duplicate identifiers follow the execution plan's first-match order, while malformed catalog entries show an error instead of being skipped. The outfit catalog loads independently of the servant catalog and server, supports retry, and ignores responses for closed editors. A missing catalog still permits clearing an existing outfit. This control does not change `master_sex` or execution behavior.

Verify servants edits `usedServant`, the slot list checked during team recognition. When the field is absent, the first three slots reflect the execution plan's default without changing the draft. Toggling a checkbox writes an explicit list while preserving unrelated array entries and their order; unchecking a slot removes every occurrence of that slot. A non-array value disables these controls until corrected in JSON. Verification choices remain editable when the servant catalog is unavailable and lock during preset loads and saves.

Assist Filters exposes the six existing recognition modes and the saved minimum NP level, friends-only, max-limit-break CE, grand bond CE, and grand-boundary refresh settings. The NP Any option writes level 1, which does not require NP-level recognition. CE-only modes disable servant filters; servant-only mode disables the limit-break filter; selecting the first support bypasses recognition filters. Grand bond and boundary-refresh options are enabled only for grand modes. Switching modes never clears the stored filter values or changes CE names, skill levels, tags, and other script fields. Unknown or malformed selections remain visible as current values until explicitly replaced, and changes are saved only with the rest of the script. Non-boolean checkbox values display their backend truth value and remain unchanged until toggled. The grand-boundary refresh control uses the legacy `noGrandRefresh` field: it requests a refresh when scrolling reaches a non-grand section, not a ban on refreshing.

Assist CEs adds active templates to `assistEquip`, previews configured candidates, removes candidates, and clears the list after confirmation. Archived templates cannot be added, and these controls never activate, archive, or otherwise modify template inventory. Legacy strings and nested arrays remain unchanged on load; adding appends a name, while removal deletes every occurrence of that name and preserves the other array structure. Missing templates remain visible and removable. Null values are retained until edited. Unsupported values and structures exceeding 1,000 JSON values disable structural edits but can be explicitly cleared. The section is inactive when the recognition mode does not use CEs. Catalog refreshes preserve the current draft, ignore closed editors, and do not block saving; unavailable images do not prevent list editing. All candidate changes stay in the draft until Save.
