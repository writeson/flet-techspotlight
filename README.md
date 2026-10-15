# FletTechspotlight app

## Run the app

### uv

Run as a desktop app:

```bash
uv run flet run
```

Run as a web app:

```bash
uv run flet run --web
```

For more details on running the app, refer to the [Getting Started Guide](https://flet.dev/docs/).

## Build the app

### Android

```bash
flet build apk -v
```

For more details on building and signing `.apk` or `.aab`, refer to the [Android Packaging Guide](https://flet.dev/docs/publish/android/).

### iOS

```bash
flet build ipa -v
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
uv run flet build ios-simulator -v

# 3. Install and launch it on the booted device
xcrun simctl install booted build/ios-simulator/flet-techspotlight.app
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
applied directly to the generated project in `build/flutter/ios/` (which is
git-ignored):

1. `Runner.xcodeproj/project.pbxproj` — replace all three occurrences of
   `IPHONEOS_DEPLOYMENT_TARGET = 13.0;` with `15.0`:

   ```bash
   sed -i '' 's/IPHONEOS_DEPLOYMENT_TARGET = 13\.0;/IPHONEOS_DEPLOYMENT_TARGET = 15.0;/g' \
     build/flutter/ios/Runner.xcodeproj/project.pbxproj
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
`flet build ios-simulator --template <patched-template-dir> --template-dir build`.

### macOS

```bash
flet build macos -v
```

For more details on building macOS package, refer to the [macOS Packaging Guide](https://flet.dev/docs/publish/macos/).

### Linux

```bash
flet build linux -v
```

For more details on building Linux package, refer to the [Linux Packaging Guide](https://flet.dev/docs/publish/linux/).

### Windows

```bash
flet build windows -v
```

For more details on building Windows package, refer to the [Windows Packaging Guide](https://flet.dev/docs/publish/windows/).

### Web

```bash
flet build web -v
```

For more details on building Web app, refer to the [Web Packaging Guide](https://flet.dev/docs/publish/web/).
