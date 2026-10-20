# FletTechspotlight app

## Project layout

Three independent uv projects, each with its own `pyproject.toml`,
`uv.lock` and `.venv` — run `uv sync` inside a directory to create its
environment:

- `ui/src` — the Flet app; `flet run` and `flet build` are executed here
  (build output lands in `ui/src/build/`)
- `ui/tests` — pytest suite for the app (`cd ui/tests && uv run pytest`)
- `backend/tools` — payments heatmap data generator

The pytest run renders a Flutter test host into `ui/tests/build/`
(git-ignored). It needs the same macOS deployment-target patch as
`ui/src/build/flutter/macos/` (see below) — reapply it to
`ui/tests/build/flutter/macos/` whenever a dependency change re-renders
the host.

## Run the app

### uv

Run as a desktop app:

```bash
cd ui/src && uv run flet run
```

Run as a web app:

```bash
cd ui/src && uv run flet run --web
```

For more details on running the app, refer to the [Getting Started Guide](https://flet.dev/docs/).

## Heatmap data

A background asyncio service populates the SQLite database that will feed
the Flet app's US payment heatmap (design: `docs/database-design.md`).

- **Database**: `data/heatmap_data.db` (git-ignored, created on first
  use), SQLite in WAL mode so the two processes can use it concurrently.
- **Schema**: a `payments` table (SQLModel) with `created_at` Unix epoch
  timestamps, `amount_cents` integer amounts, and `zipcode` / `state` /
  `state_name` location columns.
- **Generator**: `backend/tools/main.py` inserts a batch of payments every
  5 seconds. Amounts range from 100 to 10000 cents; timestamps spread
  across the just-elapsed 5-second window; locations are weighted by
  state population and zip rank, shaped by a bell curve over 9-5 local
  business hours in each state's time zone, so the wave of activity
  follows the clock across the United States.
- **Flet side**: `ui/src/database.py` reads the same file; the app shows
  a one-line payment summary until the heatmap UI lands.

```bash
cd backend/tools
uv sync

# Create the database, insert one batch, then exit
uv run python main.py --once

# ...or run the generator continuously
uv run python main.py
```

Override the database location for either side with the `HEATMAP_DATA_DB`
environment variable. Without the database, the app shows
"no heatmap data yet — run backend/tools/main.py".

## Build the app

### Android

```bash
cd ui/src && flet build apk -v
```

For more details on building and signing `.apk` or `.aab`, refer to the [Android Packaging Guide](https://flet.dev/docs/publish/android/).

### iOS

```bash
cd ui/src && flet build ipa -v
```

For more details on building and signing `.ipa`, refer to the [iOS Packaging Guide](https://flet.dev/docs/publish/ios/).

### iOS simulator

Prerequisites (checked with Xcode 27.0 on macOS 27):

- **Xcode** with the iOS SDK (`xcode-select -p`, `xcodebuild -showsdks`).
- **iOS simulator runtime** — if no devices show under
  `xcrun simctl list devices available`, download it with
  `xcodebuild -downloadPlatform iOS` (multi-GB, one time).
- **CocoaPods** — required by the flet Flutter template:
  `brew install cocoapods`.

Full workflow:

```bash
# 1. Boot a simulator (device appears under `xcrun simctl list devices`)
xcrun simctl boot "iPhone 17"

# 2. Build the app bundle for the simulator
cd ui/src && uv run flet build ios-simulator -v

# 3. Install and launch it on the booted device
xcrun simctl install booted ui/src/build/ios-simulator/flet-techspotlight.app
xcrun simctl launch booted com.mycompany.flet-techspotlight

# 4. (Optional) capture a screenshot to verify what the device is showing
xcrun simctl io booted screenshot /tmp/sim.png
```

#### DeviceHub replaces the Simulator app (Xcode 26+)

There is no `Simulator.app` in Xcode 26 or later — don't go looking for it
or assume a broken Xcode install. Apple replaced it with **DeviceHub**,
shipped inside the Xcode bundle at
`Xcode.app/Contents/Applications/DeviceHub.app` (alongside Instruments,
FileMerge, etc., which all moved there too).

Notes from working with it:

- `simctl` drives simulators fine on its own — build, install, launch, and
  screenshots all work headlessly, with no GUI app running.
- To get the phone window on screen, open DeviceHub:

  ```bash
  open -a "$(xcode-select -p)/Applications/DeviceHub.app"
  ```

- DeviceHub does not reliably auto-open a device window on launch, even
  with a booted simulator present. Opening it manually is the dependable
  path; use it to pick the simulator and display its screen.
- `open -a Simulator` fails by design on this Xcode version — that is the
  new layout, not damage. Reinstalling Xcode will not bring Simulator.app
  back.

#### Deployment target patch (required for Xcode 27+)

The flet build template (v1.0.4) hardcodes an iOS deployment target of
**13.0**, but Xcode 27 refuses deployment targets below **15.0**, so the
build fails with errors like:

```
The iOS deployment target "IPHONEOS_DEPLOYMENT_TARGET" is set to 13.0,
but the range of supported deployment target versions is 15.0 to 27.0.x
```

There is no config option to change this (`pyproject.toml` has no override,
and the template's `cookiecutter.json` exposes no variable), so the fix is
applied directly to the generated project in
`ui/src/build/flutter/ios/` (which is git-ignored):

1. `Runner.xcodeproj/project.pbxproj` — replace all three occurrences of
   `IPHONEOS_DEPLOYMENT_TARGET = 13.0;` with `15.0`:

   ```bash
   sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 13\.0;/IPHONEOS_DEPLOYMENT_TARGET = 15.0;/g' \
     ui/src/build/flutter/ios/Runner.xcodeproj/project.pbxproj
   ```

2. `Podfile` — raise the platform:

   ```ruby
   platform :ios, '15.0'
   ```

3. `Podfile` — inside the `post_install` block, add a floor so every pod
   target lands at 15.0 or above (pods may declare older minimums):

   ```ruby
   target.build_configurations.each do |config|
     current_min = config.build_settings['IPHONEOS_DEPLOYMENT_TARGET']
     if current_min.nil? || Gem::Version.new(current_min) < Gem::Version.new('15.0')
       config.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '15.0'
     end
   end
   ```

**When to reapply:** the patch lives in regenerated build artifacts. Reapply
it whenever `flet build` re-renders the Flutter project — i.e. after a flet
upgrade, or when build options change in `pyproject.toml` (flet re-renders
when its template hash changes). If a build fails with the 13.0 error above,
reapplying the three edits is enough. A more durable alternative is keeping
a patched copy of the flet build template and building with
`flet build ios-simulator --template <patched-template-dir> --template-dir ui/src/build`.

### macOS

```bash
cd ui/src && flet build macos -v
```

For more details on building macOS package, refer to the [macOS Packaging Guide](https://flet.dev/docs/publish/macos/).

#### Deployment target patch (required for Xcode 27+)

The flet build template (v1.0.4) hardcodes a macOS deployment target of
**11.0** (and some pods declare **10.15**), but Xcode 27 refuses
deployment targets below **12.0**, so the build fails with errors like:

```
The macOS deployment target "MACOSX_DEPLOYMENT_TARGET" is set to 11.0,
but the range of supported deployment target versions is 12.0 to 27.0.x
```

There is no config option to change this (`pyproject.toml` has no
override), so the fix is applied directly to the generated project in
`ui/src/build/flutter/macos/` (which is git-ignored):

1. `Runner.xcodeproj/project.pbxproj` — replace all occurrences of
   `MACOSX_DEPLOYMENT_TARGET = 11.0;` with `12.0`:

   ```bash
   sed -i '' 's/MACOSX_DEPLOYMENT_TARGET = [0-9.]*;/MACOSX_DEPLOYMENT_TARGET = 12.0;/g' \
     ui/src/build/flutter/macos/Runner.xcodeproj/project.pbxproj
   ```

2. `Podfile` — raise the platform:

   ```ruby
   platform :osx, '12.0'
   ```

3. `Podfile` — inside the `post_install` block, add a floor so every pod
   target lands at 12.0 or above (pods may declare older minimums):

   ```ruby
   target.build_configurations.each do |config|
     current_min = config.build_settings['MACOSX_DEPLOYMENT_TARGET']
     if current_min.nil? || Gem::Version.new(current_min) < Gem::Version.new('12.0')
       config.build_settings['MACOSX_DEPLOYMENT_TARGET'] = '12.0'
     end
   end
   ```

**When to reapply:** same as the iOS patch above — reapply it whenever
flet re-renders the Flutter project (flet upgrade, or a build-option
change in `pyproject.toml`, such as editing `[tool.flet.app] path`).
If a build fails with the 11.0 error above, reapplying the three edits
is enough.

### Linux

```bash
cd ui/src && flet build linux -v
```

For more details on building Linux package, refer to the [Linux Packaging Guide](https://flet.dev/docs/publish/linux/).

### Windows

```bash
cd ui/src && flet build windows -v
```

For more details on building Windows package, refer to the [Windows Packaging Guide](https://flet.dev/docs/publish/windows/).

### Web

```bash
cd ui/src && flet build web -v
```

For more details on building Web app, refer to the [Web Packaging Guide](https://flet.dev/docs/publish/web/).
