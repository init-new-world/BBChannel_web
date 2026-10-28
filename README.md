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
node --check webapp/static/i18n.js
node --check webapp/static/preset-team.js
node --check webapp/static/preset-assist.js
node --check webapp/static/preset-equips.js
node --check webapp/static/preset-settlement.js
node --check webapp/static/preset-drops.js
```

If optional runtime dependencies are missing, dependency-specific tests skip instead of failing. Install `requirements.txt` before running the server smoke test:

```bash
python -m webapp
```

Browser regression tests are optional and use isolated temporary data plus a simulated device. Install Playwright and point the test runner at a local Chromium or Google Chrome executable:

```bash
python -m pip install playwright
BBCHANNEL_TEST_CHROMIUM=/path/to/chromium python -m pytest -q tests/test_*_browser.py
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
- Script and strategy editing, independent copies, JSON import/export, validation, compiled-program inspection, and dry runs.
- Battle entry, support selection, team checks, skills, command-card strategies, result handling, repeated runs, and bounded crash or frozen-screen recovery.
- Assist filters for servant/CE identity, limit break, friendship, NP and servant level, main and append skill levels, custom tags, NP color, and Olga form.
- CE template creation and inventory management, plus a visual custom-tag crop/import/binding tool.
- Lottery, Valentine exchange, excavation, and supported EXP-material workflows, with job history, progress events, pause/resume, and cancellation.
- Material drop queries from the bundled data and a local notebook.

The console's top-bar language selector supports English and Simplified Chinese. It saves the choice in browser local storage and otherwise follows the browser language. Static interface controls and common live status text are translated; script JSON, device identifiers, names, and backend-provided messages remain unchanged.

The copy icons beside the script and strategy selectors load the selected preset into a new draft with an empty required name. Copies retain the complete JSON, including extension fields, and use the backend's existing-name protection. Canceling discards the draft; Save creates a separate file. A source-load response arriving after another editor was opened or closed is ignored.

Preset details include JSON `source` text from the same read as their parsed data. The save APIs accept exactly one of the original structured payload (`config` for scripts, `entries` for strategies) or a `source` string, with the same validation and overwrite protection. Source requests reject malformed JSON, the wrong top-level type, non-finite constants, and floating-point overflow before writing. Opening, copying, importing, exporting, and saving an unchanged preset now avoid a JavaScript numeric round trip, retaining Python floating-point types and integers beyond JavaScript's safe range. Files still use the server's existing save formatting. Other structured controls retain their existing JSON serialization behavior and can still canonicalize numbers when explicitly edited; this is not a claim that every editing workflow is source-preserving.

Execution is rejected when a script fails validation or contains unsupported compiled actions. Recognition-dependent behavior still requires suitable assets and a compatible device layout; this project does not claim complete parity with every original-client function or every live game screen.

### Assist Class Tabs

Assist class switching follows the bundled original client's `FGObattle.Battle.chooseRightClass` and `checkChoosedClass`: an already-selected target class or the friends tab is retained. `allNotSkip` preserves only the ALL/recommended tab (indices 0 and -1); it does not suppress correcting another class or an unrecognized selection. CE-only and first-support modes do not switch classes. Selection detection uses the original masked border templates, header search region, and separate ordinary/recommended-tab spacing, normalized to 1280x720. Class changes must be recognized before support selection proceeds, with at most three double-tap attempts and cancellation checkpoints between attempts. Retries recheck the recommended layout instead of reusing stale coordinates; an unrecognized or incorrect selection at the limit fails the job.

### Assist List Refresh

With `onlyFriendAssist` enabled, the runner follows the original `FGObattle.Battle.swipeFindAssist` early-refresh condition: after at least two scrolls in the current list, no matching candidate and no `friend.png` marker in the original right-hand region trigger a refresh instead of scrolling to the configured limit. Recognized friends keep scrolling eligible, and each refresh resets the two-scroll guard. A missing marker template disables this optimization rather than being treated as proof that there are no friends. Existing scroll and refresh limits still apply; results and recognition events record `friend_boundary_hits`.

### Assist Skills

`skillsLevel` stores three main skills followed by up to five append skills. Each entry is an integer from `0` to `10`; `0` means no requirement and positive values are minimum levels. The current CNTW layout supports three append slots. Nonzero requirements for its fourth or fifth append slot are rejected rather than ignored.

The script editor's numeric controls stay synchronized with its JSON editor. Append filtering verifies the skill display, checks each requested slot, restores the main view, and rechecks the candidate before selection. The full-run NP color/Olga filter is a per-run option and does not change the saved script.

### Operation Timing

The original `intervalBF` and `intervalAF` settings apply before and after each device tap or swipe, not before and after a battle. Profile-backed device jobs use a task-local timing scope, including all stages within a full run, and wait through the cancel-aware run context. The defaults are 0 seconds before and 0.1 seconds after; post-operation waiting has the original minimum of 0.1 seconds even when a lower value is stored. Existing 0-through-600-second execution bounds remain in place. Screenshots, manual device calls, and diagnostic jobs do not inherit another task's timing. Nested stages apply timing once, and completion, failure, and cancellation always restore the prior scope.

Execution plans now expose `interval_before_operation` and `interval_after_operation`. The older `interval_before_fight` and `interval_after_fight` keys remain for API compatibility but no longer cause per-battle waits. Recognition-specific settling waits, including `intervalAFswipeAssist` and `intervalBFchooseCard`, remain separate. Both operation delays are validated before the first actuation wait or backend action; capture-only inspections remain usable when a legacy profile contains invalid, unused timing values.

### Card Recovery

Command-card strategies exclude face cards with recognized action-blocking status text. If a selection containing Noble Phantasms leaves the command-card back button visible, the runner checks the selected NP cards for sealing or immobilization. Confirmed unavailable NPs are excluded when the runner returns to battle and reopens card selection. This applies to direct selection, strategies, no-chain selection, and extra turns; unavailable positions are tracked only for that turn and allow at most three recovery cycles.

The runner does not infer NP availability from an unrecognized gauge. It also does not retry when the back button has disappeared or when no selected NP has a recognized blocking status. Returning to battle must be confirmed before another attack tap is sent.

### Bond Stop Exclusions

`ignoreFriendship` follows the bundled original client's `FGObattle.Battle.dealIgnoreFriendShip` and `checkBattleEnd` behavior: string characters or list entries convertible to integers from 1 through 5 identify reward-panel positions excluded from the existing-full-bond check. Other entries are ignored. With `fullFriendshipStop` enabled, the runner masks only those positions before rechecking `jbMax`; full-bond markers elsewhere still stop the run. The separate `jblevel10` level-up dialog still stops the run even when every reward position is excluded. The original 1920x1080 mask coordinates are scaled to the normalized capture, and other recognition uses the unmodified capture.

The editor's collapsible Settlement section exposes the original `fullFriendshipStop`, `ignoreFriendship`, and `addFriend` settings. The ignored-position text field keeps the original client's free-text behavior and refers to settlement positions 1 through 5 excluding the support servant. Existing non-string values are displayed as JSON and retained until the field is edited. Text edits synchronize to the JSON draft on input, so a late strategy-list response cannot discard focused text. Checkbox display follows the execution plan's truth value, including legacy empty arrays and objects. These changes stay in the draft until Save and lock during pending preset application or saving.

### Drop Templates

The recognition service supports optional template crops and grayscale matching for individual, batched, and multi-result searches. Batched candidates share one screenshot decode and cache the original template and mask without mutating them when crops or grayscale views differ. Cropped or grayscale templates with no spatial contrast after resizing, including inside their effective mask, are treated as unconfirmed rather than allowing undefined normalized correlation to produce a perfect match. Crop coordinates must be actual integers. Existing calls that request neither crop nor grayscale keep their default color behavior.

Drop-stop recognition resolves the complete configured path inside `assets/drop/` before considering a filename fallback. Original Windows paths containing `assets/drop/` retain their directory choice; older external paths and bare filenames resolve only when exactly one indexed drop image has that filename. Missing explicit paths and ambiguous filenames never select another image. Resolution examines the full catalog rather than a 200-result substring page, and verifies that the file still exists within the asset root. The drop catalog and PNG preview endpoints share this resolver; previews are restricted to drop images and reject traversal and links escaping the asset root.

Counting now follows the original `FGObattle.Battle.getDropTemp` and `checkDrop` two-stage rules. An image of size `(w, h)` derives `s = (w / 176 + h / 193) / 2`, with full-image reference resolution `(int(1920*s), int(1080*s))`. A color search at threshold 0.65 uses the smaller screenshot-to-reference ratio. Each candidate is then checked against the template's central half, cropped at integer quarter bounds, in grayscale at threshold 0.65. That check uses the candidate's size against its separate reference `(int(176*s), int(193*s))`. Both stages ignore an image's alpha channel, matching the original drop templates' unmasked normalized centered correlation; other recognition callers retain automatic alpha masking by default, and explicit masks remain effective even when implicit alpha masking is disabled. The crop-local matched center is rounded before its squared offset from the candidate center is compared with `min(50, max(30, candidate_height / 193 * 50))`; this is a squared-distance bound, not a 30-to-50-pixel radius.

Only verified candidates enter the existing animation deduplication and cross-run count. Recognition events report initial candidates, verified matches, central-match failures, and excessive offsets separately. Verification runs in groups of 16 with pause/cancellation checks before and after each group, and retains the existing 100-candidate frame bound. Disabled monitoring does not verify images; images too small to form a central crop fail with a clear template error when monitoring is enabled. The port retains its existing OpenCV resampling and overlap suppression, so pixel-identical results to every original-client environment are not claimed.

The editor's initially collapsed Drop Stop section exposes `dropStopNum` and `dropImage`. A zero count disables monitoring; new count edits must be non-negative JavaScript-safe integers, while legacy types and values remain unchanged until explicitly corrected. Selecting a catalog image writes its full `drop/` path, and choosing None removes only `dropImage`, without resetting the count. Original paths resolve to their preview without rewriting the saved path. Missing or ambiguous selections stay visible as current values. Catalog and preview failures never block unrelated edits or Save; Refresh retries the index and image. Delayed responses cannot replace a newer raw-JSON selection or a closed editor. Numeric drafts survive catalog refreshes and unrelated controls, invalid drafts block Save, and the section locks during preset application, saving, and invalid JSON.

## Resources

Recognition resources are expected under `assets/`, and data files under `data/`. Populate them from the BBchannel package when setting up a fresh checkout. Scripts live in `data/settings/` and strategies in `data/strategy/`.

Custom assist tags live in `assets/assist/assist_tags/`. Their PNG filenames encode the source dimensions, crop offsets, and confidence threshold. A tag referenced by a script cannot be deleted until it is unbound; missing or inconsistent tag images fail script validation.

Custom command-card tags in `specialKeys` use their filename's source dimensions and card-local crop bounds during recognition. The search region keeps the original client's animation tolerance and stays inside each card. Strategy preferences such as `S0` refer to the tag's index in `specialKeys`. Invalid metadata or missing/inconsistent images fail script validation.

The Tag Maker's **Command Cards** tab captures a normalized 1280x720 screenshot and restricts crops to the selected card. It stores PNGs under `assets/battle/customCommandCard/` and supports import, preview, and script binding. Imported original-client PNGs keep their filename metadata. New bindings append an `S` index; unbinding is allowed only for the last entry when no embedded strategy in that script references it. Existing indices are never silently renumbered. Removing an image is blocked while any script still references it. Switching tag modes clears the capture and ignores responses belonging to the previous mode.

Strategy preferences accept ordinary card codes (`1B`), tag-only codes (`S0`), and combined codes (`1BS0`). Selection tries alternative matching cards when an earlier preference prevents a complete three-card assignment. The two `breakpoint` booleans require different servants across the first/second and second/third face-card boundaries respectively; a boundary involving a Noble Phantasm is exempt.

The strategy editor exposes each card's type, ordered preferences, and minimum/maximum critical-star threshold. Controls preserve unrelated JSON fields and other entries. Invalid control drafts remain visible across unrelated changes and prevent saving, including when the invalid draft belongs to another entry. Editing raw JSON replaces the control drafts. Strategy files and embedded script strategies reject invalid types, preference codes, star thresholds outside `0` through `10`, and non-boolean comparison values.

New strategy presets start with one editable entry. Entries can be added, duplicated, renamed, reordered, and deleted without editing JSON. Reordering preserves both extension fields and invalid input drafts; duplicating copies the entry and its drafts, while deletion discards only that entry's drafts. The editor does not write the preset file until Save. Local toolbar icons come from Lucide Static 1.43.0; their license is included in `webapp/static/icons/LICENSE.txt`.

The script editor's Turn Strategy controls apply a saved strategy preset to a regular turn or a wave's extra turns. Applying copies all strategy entries in order, including extension fields, without linking future preset edits to that script. Replacing or clearing existing strategies requires confirmation; clearing leaves an empty strategy array so turns inferred from legacy keys are retained. Changes remain in the editor until Save. Loading a preset locks strategy actions and Save, rejects responses for a changed JSON draft, and ignores responses after the editor is closed. The turn selector refuses lists above 1,000 entries without changing the source JSON.

Regular turns also expose an ordered list of up to three Noble Phantasms. Selecting an NP already in the sequence exchanges positions; choosing None removes that slot and compacts the sequence. These selections are preselected before command-card strategy evaluation. NP edits replace only the selected source value, preserving other turns, float spellings, large integers, and the types of unrelated skill commands. Malformed or float-typed sequences remain unchanged until explicitly cleared, and clearing keeps the empty NP array so inferred turns are retained. Duplicate NP fields and noncanonical wave keys disable both selection and clear. NP editing is unavailable for extra turns or during a pending preset load or save. NP options, validation errors, and the clear confirmation follow the selected language; late catalog updates preserve a focused NP slot. Save and Cancel remain visible at the bottom of the scrollable editor.

The initially collapsed Skill Sequence section edits ordinary servant and master skills for the selected regular or extra turn. Each command can select a servant target, move up or down, or be removed. Enemy target commands use the original `[13, position]` format and select one of six enemy positions in sequence with the skills. Switching to enemy targeting starts at enemy 1; switching back to a skill clears its target rather than reusing a position from the other domain. The list is bounded at 1,000 entries and scrolls independently. Advanced, malformed, or float-typed commands make the whole sequence read-only until it is explicitly cleared after confirmation; clearing retains the empty skill field and inferred turns. Ambiguous duplicate skill fields cannot be edited or cleared. Edits replace only the selected JSON value, preserving unrelated float spellings, large integers, and invalid control drafts. Loading strategies, saving, or invalid JSON locks these controls. Changes remain draft-only until Save.

Source-aware skill and NP edits use the pinned MIT-licensed `jsonc-parser` 3.3.1 bundle in `webapp/static/vendor/`, built with esbuild 0.28.2. Its license is included beside the bundle. The parser is configured for strict JSON, not comments or trailing commas; a shared source-field helper binds AST offsets to the original source and performs targeted edits rather than numerically round-tripping the entire document. Other older structured controls still use their existing JSON serialization when explicitly edited.

Skill Sequence also exposes order change for each of the three master-skill positions. The original three-number command selects one frontline position (1 through 3) and one reserve position (4 through 6). Opening a script preserves either selection order from a valid original command; explicitly editing its positions writes frontline then reserve. Entering this mode starts with positions 1 and 4, changing its master skill keeps the pair, and leaving it discards the swap parameters. Same-side pairs and malformed or float-typed commands remain read-only. The editor does not delete existing NP choices or rewrite the saved team; execution uses the existing runtime servant-position exchange after the compiled command runs. Order-change edits work for regular and extra turns, remain draft-only until Save, and preserve unrelated JSON source values.

The original NP-charge and heal command spells can also be selected in Skill Sequence. Both require a servant target from 1 through 3; entering a spell starts at servant 1, switching between the two spells keeps the target, and leaving the spell domain resets the target for the new command type. Saved commands keep the original canonical names understood by the execution compiler. Missing, malformed, unknown, or float-targeted spell commands remain read-only until explicitly cleared. Editing, displaying, and saving these commands never runs them; game interactions occur only when a battle execution is explicitly started.

The collapsible Waves section can append waves and turns without editing JSON. A new wave starts with one turn. Removing a turn deletes only the last turn of its wave, including extension fields under that turn's key prefix; deleting a wave is allowed only for the highest-numbered wave and removes that wave's fields after confirmation. Other wave numbers and fields are never renumbered or rewritten. Counts include turns inferred from existing script fields. An empty script opens this section automatically; existing nonempty scripts keep it collapsed. Structural editing is disabled for noncanonical round/turn keys, invalid declared counts, or lists exceeding 1,000 waves or 1,000 selectable turn entries. All changes stay in the draft until Save, and wave controls are locked during preset loads and saves.

Run Options exposes the script's single-NP no-chain preference (`noChain`), crash recovery (`gameCrushRestart`), and frozen-screen recovery (`stuckRestart`). The no-chain preference applies to default command selection with one preselected NP and no explicit card strategy. The frozen-screen check interval accepts numeric values from 1 through 600 seconds, including fractions, and defaults to 30 when absent. Invalid interval drafts survive unrelated edits and keep blocking Save even after the watchdog is switched off; saving opens the section to show the invalid field. Editing raw JSON or canceling the editor discards these control drafts. Recovery still uses the existing per-run restart bound and requires compatible device assets and screens.

Run Options also exposes randomized tap positions (`randomTouch`) and an added random wait of 0 through 10 seconds (`randomTime`). The wait can be fractional and defaults to zero when absent. Existing truthy checkbox values and numeric values stay unchanged until edited. Invalid or incomplete wait drafts survive unrelated controls and block Save until corrected; malformed source values remain in JSON until explicitly replaced.

The first-battle settings switch (`firstBattleSet`) normalizes the battle menu toggles, speed, and NP skip when the first full-run battle starts. The skill animation switch (`noSpeedupSkill`) suppresses extra taps used to advance skill animations. Both checkboxes show the execution plan's truth value but leave the saved value and type untouched until toggled.

The separately collapsed Operation Timing section edits the original operation waits (`intervalBF`, `intervalAF`) and card-recognition settling wait (`intervalBFchooseCard`) while keeping Run Options compact. The controls show absent-field defaults 0, 0.1, and 0.5 without adding JSON keys; editable ranges follow the original 0-through-10-second controls, with a 0.1-second minimum for the post-operation field. Existing larger values and malformed types stay visible as current values and remain unchanged until explicitly replaced, including legacy `intervalAF: 0` which execution clamps to 0.1. New timing inputs synchronize valid edits to the JSON draft immediately and preserve native incomplete numbers across unrelated renders. Invalid edits block Save and open the section containing the invalid field; raw JSON remains authoritative, and all controls lock during preset application or saving.

AP Management exposes the original `clearAP` and `allowOtherApple` flags in a separate, initially collapsed section. Clear remaining AP uses the existing full-run behavior: after the requested runs, keep running without AP recovery until AP is insufficient or the `max_clear_runs` bound is reached (default 100 additional runs). Allow other apples enables the existing fallback among gold, silver, blue, and copper apples when the selected type is unavailable; it never selects Saint Quartz. Absent fields display off without adding keys. These and the other Run Options checkboxes use the execution plan's truth value, including empty legacy arrays and objects; values and types stay unchanged until toggled. A disabled legacy freeze watchdog also disables its interval field unless that field has an active editing draft. Edits stay in the JSON draft until Save and are discarded on Cancel; controls lock during preset application, saving, and invalid JSON.

Team exposes six servant slots using the script server's local servant catalog, plus the assist slot. Selecting None clears only that servant name; selecting Not set removes only `assistIdx`, without moving servants or changing `usedServant`. Existing aliases, unknown names, and malformed fields remain unchanged until explicitly replaced. Catalog loading never changes the JSON draft, and responses from an older server selection or closed editor are ignored. A failed catalog load can be retried and does not block unrelated editing or Save. Team controls lock during a preset application or save; all team changes stay in the draft until Save.

Team also selects the script's game server (`CH`, `CNTW`, or `JP`). Switching servers refreshes the servant catalog and the supported append-skill slots without replacing servant names, skill values, or other draft fields. Lowercase supported server names display their normalized choice while retaining the saved spelling until changed; unknown or malformed values stay visible as current values. Not set removes only `server`. Existing invalid input drafts survive a server change, and nonzero values in unsupported CNTW append slots remain editable so they can be corrected. Saving still applies the backend's server and servant validation.

Team also selects a master outfit from `master_info.json`. Choosing an outfit writes its catalog `SN` to `master_equip`, preserving numeric zero and string identifiers with leading zeroes; choosing None removes that field. Existing identifier types and unknown, empty, or null values remain unchanged until explicitly replaced. Duplicate identifiers follow the execution plan's first-match order, while malformed catalog entries show an error instead of being skipped. The outfit catalog loads independently of the servant catalog and server, supports retry, and ignores responses for closed editors. A missing catalog still permits clearing an existing outfit. Changing the outfit does not change `master_sex` or execution behavior.

Master gender follows the original `Master` and `MasterSex.changeSex` interface: an absent `master_sex` displays Female without adding a JSON key, while explicit selections write numeric 0 (Female) or 1 (Male), as confirmed by the bundled `masterface` images. Unknown and legacy values remain visible as current values and are retained until replaced. Gender editing works even if the outfit catalog is unavailable, preserves unrelated values and invalid numeric drafts, and locks during preset application, saving, or invalid JSON. Changes stay in the draft until Save, and Cancel discards them. This display setting does not add a gender requirement to team recognition.

The master controls also preview the original `masterface/{outfit_name}_{sex}.png` portrait at a fixed 50-pixel size. The read-only `/api/masters/image` endpoint resolves the selected catalog identifier using the execution plan's first-match order, preserves leading zeroes, and does not fall back to another gender or duplicate identifier. Pre-existing path traversal and links outside `masterface` are rejected, even when their targets are still inside `assets`. Resource directories are trusted local inputs, not an isolation boundary against a local process that can concurrently rewrite them. Unknown outfits and legacy gender values have no preview until explicitly replaced. Missing images never block Save; the retry icon reloads failed previews. Replaced-image and closed-editor callbacks are ignored, invalid JSON clears the preview, and preset application or saving locks retries. Preview requests do not change the JSON draft or execution settings.

Verify servants edits `usedServant`, the slot list checked during team recognition. When the field is absent, the first three slots reflect the execution plan's default without changing the draft. Toggling a checkbox writes an explicit list while preserving unrelated array entries and their order; unchecking a slot removes every occurrence of that slot. A non-array value disables these controls until corrected in JSON. Verification choices remain editable when the servant catalog is unavailable and lock during preset loads and saves.

Assist Filters exposes the six existing recognition modes and the saved minimum NP level, friends-only, ALL-tab retention, max-limit-break CE, grand bond CE, and grand-boundary refresh settings. The NP Any option writes level 1, which does not require NP-level recognition. Keep ALL tab uses the original `allNotSkip` flag, defaults to enabled when absent without changing the source, and is active only for servant recognition. CE-only modes disable servant filters; servant-only mode disables the limit-break filter; selecting the first support bypasses recognition filters. Grand bond and boundary-refresh options are enabled only for grand modes. Switching modes never clears the stored filter values or changes CE names, skill levels, tags, and other script fields. Unknown or malformed selections remain visible as current values until explicitly replaced, and changes are saved only with the rest of the script. Non-boolean checkbox values display their backend truth value and remain unchanged until toggled. The grand-boundary refresh control uses the legacy `noGrandRefresh` field: it requests a refresh when scrolling reaches a non-grand section, not a ban on refreshing.

Assist Filters also edits the original `servantLevel`, `intervalAFswipeAssist`, and `scrollLimit` fields. Minimum servant level accepts integers 1 through 120 and is active for servant recognition; scroll wait accepts 0 through 10 seconds and scroll boundary accepts 0 through 1 in search modes. Absent fields show execution defaults 1, 0.5, and 0.96 without adding JSON keys. Existing values outside these editable ranges or with legacy types remain unchanged and are identified as current values until explicitly edited. Valid edits update the JSON draft immediately, while incomplete or invalid numeric drafts survive mode changes and asynchronous renders and block Save. Invalid drafts remain editable even after switching to an otherwise inapplicable mode. Editing raw JSON clears the numeric drafts; applying presets and saving lock the controls.

Assist CEs adds active templates to `assistEquip`, previews configured candidates, removes candidates, and clears the list after confirmation. Archived templates cannot be added, and these controls never activate, archive, or otherwise modify template inventory. Legacy strings and nested arrays remain unchanged on load; adding appends a name, while removal deletes every occurrence of that name and preserves the other array structure. Missing templates remain visible and removable. Null values are retained until edited. Unsupported values and structures exceeding 1,000 JSON values disable structural edits but can be explicitly cleared. The section is inactive when the recognition mode does not use CEs. Catalog refreshes preserve the current draft, ignore closed editors, and do not block saving; unavailable images do not prevent list editing. All candidate changes stay in the draft until Save.
