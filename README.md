![](selfdrive/assets/img_bluepilot_boot.jpg)

Table of Contents
=======================

- [Table of Contents](#table-of-contents)
  - [Updates on Branch Names and Links](#-updates-on-branch-names-and-links)
  - [Join our Discord](#-join-our-discord)
  - [What is bluepilot?](#-what-is-bluepilot)
  - [Prohibited Safety Modifications](#-prohibited-safety-modifications)
  - [Installation](#-installation)
  - [BluePilot Specific Features - bp-7.0](#-bluepilot-specific-features---bp-70)
  - [Special Thanks](#-special-thanks)
  - [User Data](#-user-data)
  - [Licensing](#licensing)
  - [Support sunnypilot](#support-sunnypilot)
  - [Technical Documentation](#-technical-documentation)

---

<details><summary><h3>💭 Updates on Branch Names and Links</h3></summary>

---

As of May 2025, we are updating the way branches are named and how links are generated. We had initially intended to use a branch naming system similar to openpilot and sunnypilot where there was a "stable" or "release" branch which included all fully vetted code, and then "staging" or "beta" branches with new code that would eventually move into the stable/release branches.  However as we evolved we found everyone liked being able to bounce between newer and older branches to compare features and control. Moving forwards all releases will simply be named bp-"feature release number" as an example "staging-1.1" which features the bluepilot 1.1 features (custom tuning) will become "bp-1.1".  We will not delete older branches so that anyone can go back and view older code for references.  Branches that no longer work properly will be denoted as -deprecated.

To install any version of bluepilot, use the following URL formula (URL is case sensitive)

installer.comma.ai/BluePilotDev/"branch name"

For example

installer.comma.ai/BluePilotDev/bp-7.0

will install the **bp-7.0** branch (current release, synced with sunnypilot master as of August 16, 2026).  Branches known to no longer work due to changes in the comma codebase will be appended with -deprecated so it will be obvious they will not install or work correctly.

</details>


---

<details><summary><h3>💭 Join our Discord</h3></summary>

---

Join the official #ford channel at the sunnypilot Discord server to stay up to date with all the latest features and be a part of shaping the future of bluepilot!
* [sunnypilot Discord server](https://discord.sunnypilot.com)

</details>

<details><summary><h3>🌞 What is bluepilot?</h3></summary>

---

[bluepilot](https://github.com/bluepilotdev/bluepilot) is a fork of the hugely popular SunnyPilot project for the comma 3X and comma 4.  The goal of BluePilot is to develop, test, and stage Ford specific enhancements, validating them before submission to the SunnyPilot team for inclusion in the parent project.  BluePilot is always based upon sunnypilot's master branch.

**BluePilot bp-7.0** is synced with **sunnypilot master (August 16, 2026, openpilot 0.11.2 base)** and includes all upstream sunnypilot features plus Ford-specific enhancements. This release runs on AGNOS 19.6 and supports both the comma 3X and the comma 4.

### Upstream SunnyPilot Features
BluePilot includes **all** features from the upstream SunnyPilot project. For complete sunnypilot documentation:
* **[sunnypilot documentation](https://docs.sunnypilot.ai/)** - Features, installation, and FAQ
* **[README_SP.md](README_SP.md)** - The upstream sunnypilot README

Key upstream features include: MADS (Modular Assistive Driving System), Neural Network Lateral Control (NNLC), Dynamic Experimental Control (DEC), Speed Limit Assist (SLA), Intelligent Cruise Button Management (ICBM, extended to Ford by BluePilot), Smart Cruise Control Map & Vision (SCC-M / SCC-V), Driving Model Manager, sunnylink integration, and much more.

</details>

<details><summary><h3>⛔ Prohibited Safety Modifications</h3></summary>

---

All [official sunnypilot branches](https://github.com/sunnyhaibin/sunnypilot/branches) strictly adhere to [comma.ai's safety policy](https://github.com/commaai/openpilot/blob/master/docs/SAFETY.md). Any changes that go against this policy will result in your fork and your device being banned from both comma.ai and sunnypilot channels. This same stipulation applies to all bluepilot instances as well.

The following changes are a **VIOLATION** of this policy and **ARE NOT** included in any sunnypilot branches:
* Driver Monitoring:
    * ❌ "Nerfing" or reducing monitoring parameters.
* Panda safety:
    * ❌ No preventing disengaging of <ins>**LONGITUDINAL CONTROL**</ins> (acceleration/brake) on brake pedal press.
    * ❌ No auto re-engaging of <ins>**LONGITUDINAL CONTROL**</ins> (acceleration/brake) on brake pedal release.
    * ❌ No disengaging on ACC MAIN in OFF state.

</details>


<details><summary><h3>⚒ Installation</h3></summary>

* bluepilot not installed
  1. [Factory reset/uninstall](https://github.com/commaai/openpilot/wiki/FAQ#how-can-i-reset-the-device) the previous software if you have another software/fork installed.
  2. After factory reset/uninstall and upon reboot, select `Custom Software` when given the option.
  3. Input the installation URL based on the desired branch. Example: ```installer.comma.ai/BluePilotDev/bp-7.0``` (note: `https://` is not required on the comma device)
  4. Complete the rest of the installation following the onscreen instructions.

* bluepilot already installed
  1. On the device, go to `Settings` ▶️ `Software`.
  2. At the `Download` option, press `CHECK`. This will fetch the list of latest branches.
  3. At the `Target Branch` option, press `SELECT` to open the Target Branch selector.
  4. Scroll to select the desired branch

Requires further assistance with software installation? Join the [sunnypilot Discord server](https://discord.sunnypilot.com) and message us in the `#ford` channel.

  </details>

<details><summary><h3>🚗 BluePilot Specific Features - bp-7.0</h3></summary>

---

## What's New in bp-7.0

BluePilot 7.0 is a **major update** synced with sunnypilot master (August 16, 2026, openpilot 0.11.2 base) on AGNOS 19.6, headlined by a second, selectable Ford lateral control scheme with full panda safety enforcement.

### Angle-Primary Lateral Control (New)
A second Ford steering strategy, selectable at any time from the settings menu (no reinstall or reboot):

* **Primary Control Variable selector** - Choose between Curvature (the proven 4-signal strategy from previous releases) and Angle (path_angle as the primary actuator)
* **Per-platform tuning built in** - Separate gain defaults for CAN vehicles (Escape, Bronco Sport, Maverick, Edge), CAN-FD trucks (F-150, Lightning, Expedition, Ranger), and CAN-FD SUVs (Mustang Mach-E, Escape MK4.5)
* **Variable lookahead** - Model lookahead time adapts to speed and curve depth for earlier, smoother curve entry without early unwind at the apex
* **PSCM saturation handling** - Detects when the steering module is at its authority limit and manages the command to avoid snap corrections on release
* **User feel adjustments** - Low Speed and High Speed Adjustment Factors plus an angle-specific Lane Change Factor

### Panda Safety for Angle Mode
Angle mode runs under full panda safety enforcement, not a bypass:

* The safety firmware corroborates that angle mode is genuinely engaged through a redundant CAN channel before accepting angle-mode frames
* A shadow curvature cross-check continuously validates the commanded steering intent against the measured vehicle motion
* path_angle rate-of-change limits are enforced independently on the panda, tuned to the actual control cadence
* Full regression test coverage in the safety test suite, validated against recorded real-world routes with a replay harness

### Per-Scheme Tuning Parameters
Curvature and angle control no longer share any tuning values:

* Every lateral tuning parameter now belongs to exactly one scheme (curvature or angle)
* Switching schemes never overwrites or reuses the other scheme's tuning; each keeps its own values
* Existing settings migrate automatically on first boot after updating; no retuning required

### Settings Menu Reorganization
* **Nested lateral tuning sections** - Lateral Tuning now contains collapsible Angle Tuning and Curvature Tuning sub-sections; the disable toggle and scheme selector sit at the top
* Controls for the unselected scheme stay visible but grey out, so both tuning sets are always discoverable (comma 3X)
* Cleaned up and reorganized comma 4 menus, with an on-device vehicle selector and integer/float value pickers on both platforms

### SunnyLink Remote Settings
* **Ford BluePilot settings under the "vehicle" panel in sunnylink** - Configure BluePilot from the sunnylink interface, grouped by System, Vehicle, Visuals, Longitudinal Tuning, and Lateral Tuning
* Scheme-aware: angle and curvature tuning entries appear only when their control scheme is selected, with the same dependency gating as the on-device menu

### Connect Backend
* **Connect Backend** - Choose Comma Connect (stock servers), Konik Stable (stable.konik.ai), or Offline Mode (unreachable hosts so uploads never succeed)
* Dongle ID switches automatically between Comma and Konik and is cached per backend, so switching is reversible in both directions with a reboot
* Pairing QR codes and instructions follow the selected backend

### Visuals
* **Rainbow Lane Lines** - Inner lane lines become rainbow colored when longitudinal control is active
* **Minimal Driving View** - Hide the camera feed and show only lane lines and the model path
* **Show Lateral Control Mode** - Steering wheel icon overlay showing the active lateral scheme
* Steering arc fix for the comma 3X, with reduced false left-steer bias from road roll

### Platform & Stability
* Synced with sunnypilot master (June 10, 2026): Chrysler CUSW, Rivian, Tesla, Honda, and Hyundai updates, lateralManeuverPlan support, updated panda/msgq/rednose submodules
* AGNOS 18.4 with the AGNOS thermal framework managing CPU frequency (replaces the static frequency cap)
* Display initialization fixes for git-clone installs (EGL/GLES driver re-pointing on boot)
* is_bluepilot() detection system; all stock file overrides are guarded and labeled for clean upstream merges
* Ford opendbc code refactored into a sunnypilot extension layer, with the safety test harness synced to upstream

### BluePilot Settings & Tuning

The following settings are available in the BluePilot menu:

**System:**
* UI Debug Logging
* Connect Backend (Comma Connect / Konik Stable / Offline Mode)
* Preferred WiFi Network
* Clear Crashed Model
* Reset Menu Layout

**Vehicle:**
* Show BlueCruise UI on Cluster (supported digital dashes)
* 12V Battery Limit

**Visuals:**
* Hide Onroad Border
* Disable Lane Line Status Color
* Minimal Driving View
* Rainbow Lane Lines
* Show Blindspot Overlay
* Show Brake Status
* Show Confidence Ball (comma 3X)
* Animate Steering Wheel
* Show Lateral Control Mode
* Show Radar Lead Overlay (Ford ACC) with size selection
* Hybrid/EV Battery Status, Power Flow, gauge size and style options
* Lower Right Display selector (comma 4)

**Longitudinal Tuning:**
* Bypass BP Longitudinal Control
* Disable Downhill Compensation
* Disable Ford Radar (Vision-Only Leads)

**Lateral Tuning:**
* Disable BP Lateral Control
* Primary Control Variable (Curvature / Angle)
* Disable Lane Change Under Speed, with minimum speed selector
* Angle Tuning: Low Speed Adjustment Factor, High Speed Adjustment Factor, Lane Change Factor High
* Curvature Tuning: Human Turn Detection, Lane Change Factor High, Lane Positioning, In-Lane Offset, Lanefull Mode, Custom Tuning Profile, Predicted Curvature Blend Ratios (High/Low), Centering PID Gain

### Previous Releases (6.x)

BluePilot 6.0 through 6.1 introduced the React-based BluePilot Portal PWA (home dashboard, routes with video playback and GPS maps, settings, and diagnostics panels), comma 4 support with its own onroad UI and menus, separate BluePilot/SunnyPilot BSM toggles, ACC coasting improvements, the on-device vehicle selector, Ford Edge MK2 support, and Ford ICBM improvements. For the complete version-by-version history, see [BP_CHANGES.json](BP_CHANGES.json).

</details>

<details><summary><h3>🏆 Special Thanks</h3></summary>

---

* [twilsonco](https://github.com/twilsonco/openpilot)

</details>

<details><summary><h3>📊 User Data</h3></summary>

---

By default, sunnypilot/bluepilot uploads the driving data to comma servers. You can also access your data through [comma connect](https://connect.comma.ai/). The Connect Backend setting can instead send data to Konik (stable.konik.ai), or Offline Mode (unreachable hosts so uploads never succeed).

sunnypilot/bluepilot is open source software. The user is free to disable data collection if they wish to do so.

sunnypilot/bluepilot logs the road-facing camera, CAN, GPS, IMU, magnetometer, thermal sensors, crashes, and operating system logs.
The driver-facing camera and microphone are only logged if you explicitly opt-in in settings.

By using this software, you understand that use of this software or its related services will generate certain types of user data, which may be logged and stored at the sole discretion of comma. By accepting this agreement, you grant an irrevocable, perpetual, worldwide right to comma for the use of this data.

</details>

<details><summary><h3>Licensing</h3></summary>

openpilot is released under the MIT license. Some parts of the software are released under other licenses as specified.

Any user of this software shall indemnify and hold harmless comma.ai, Inc. and its directors, officers, employees, agents, stockholders, affiliates, subcontractors and customers from and against all allegations, claims, actions, suits, demands, damages, liabilities, obligations, losses, settlements, judgments, costs and expenses (including without limitation attorneys’ fees and costs) which arise out of, relate to or result from any use of this software by user.

**THIS IS ALPHA QUALITY SOFTWARE FOR RESEARCH PURPOSES ONLY. THIS IS NOT A PRODUCT.
YOU ARE RESPONSIBLE FOR COMPLYING WITH LOCAL LAWS AND REGULATIONS.
NO WARRANTY EXPRESSED OR IMPLIED.**

For full license terms, please see the [`LICENSE`](LICENSE) file.

</details>

<details><summary><h3>Support sunnypilot</h3></summary>
<h3>💰 Support sunnypilot</h3>

---

If you find any of the features useful, consider becoming a [sponsor on GitHub](https://github.com/sponsors/sunnyhaibin) to support future feature development and improvements.


By becoming a sponsor, you will gain access to exclusive content, early access to new features, and the opportunity to directly influence the project's development.

<h3>GitHub Sponsor</h3>

<a href="https://github.com/sponsors/sunnyhaibin">
  <img src="https://user-images.githubusercontent.com/47793918/244135584-9800acbd-69fd-4b2b-bec9-e5fa2d85c817.png" alt="Become a Sponsor" width="300" style="max-width: 100%; height: auto;">
</a>
<br>

<h3>PayPal</h3>

<a href="https://paypal.me/sunnyhaibin0850" target="_blank">
<img src="https://www.paypalobjects.com/en_US/i/btn/btn_donateCC_LG.gif" alt="PayPal this" title="PayPal - The safer, easier way to pay online!" border="0" />
</a>
<br></br>
</details>

<details><summary><h3>🔧 Technical Documentation</h3></summary>

---

### BluePilot Portal

The BluePilot Portal is a React-based Progressive Web App served directly from the device at `http://<device-ip>:8088` (WebSocket updates on port 8089):

* **Home Dashboard** - System status, drive stats, and disk space visualization
* **Routes** - Browse recorded routes with video playback, GPS maps, camera exports, and qlog/rlog downloads
* **Settings** - Configure all parameters from the browser with live WebSocket updates
* **Diagnostics** - Real-time TMUX streaming and parameter browser

Modification endpoints are blocked (HTTP 403) while the vehicle is driving.

### Backend Architecture

```
bluepilot/backend/
├── bp_portal.py             # Main HTTP server (BluePilot Portal)
├── config.py                # Configuration and constants
├── handlers/                # HTTP endpoint handlers
├── params/                  # Parameter management and watching
├── routes/                  # Route discovery, GPS metrics, preprocessing
├── video/                   # FFmpeg export and HEVC to MP4 remuxing
├── realtime/                # WebSocket broadcasting
├── logs/                    # Cereal log parsing
├── cache/                   # Metrics/thumbnail/remux caching
├── storage/                 # Route preservation
├── network/                 # Network utilities
├── system/                  # CPU/memory/disk metrics
├── core/                    # Thread-safe state and lifecycle
└── utils/                   # Helper functions
```

### Development

**Backend testing:**
```bash
python3 bluepilot/backend/test_backend_import.py   # Test backend imports
python3 bluepilot/backend/test_modules_only.py     # Test modular components
python3 bluepilot/test_web_routes.py               # Run local server for testing
```

**Frontend development (React + Vite):**
```bash
cd bluepilot/web
npm install
npm run dev      # Development server
npm run build    # Production build
```

</details>


<span>-</span> BluePilotDev Team
