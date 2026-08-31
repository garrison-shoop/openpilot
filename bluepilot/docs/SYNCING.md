# Syncing BluePilot with sunnypilot / BluePilotDev

Working notes for keeping this fork current. Written after the 2026-08 restructure
sync, which surfaced a long tail of runtime-only breakage; most of this file is the
list of ways that went wrong and how to catch each one *before* flashing.

**Keep this file current.** Any change to the sync process — a new gotcha, a different
resolution for a recurring conflict, or something moving out of the "deliberately not
done" list — gets written down here in the same change. The whole point is that the
work can be resumed cold, and a stale entry is worse than a missing one because it
gets trusted.

Read `AGENTS.md` at the repo root first — it is the authoritative guide to the
three-layer architecture (stock openpilot → sunnypilot → BluePilot) and the marker
convention. This file is the operational companion to it.

---

## 1. Branch topology

`bp-sp-sync-2026-08` is the base. Everything else sits on top of it:

```
bp-sp-sync-2026-08              the sync itself + fixes; nothing feature-specific
├── bp-external-storage         + developer-panel storage control
├── bp-egpu-3x                  + chestnut PCIe link probe, 3X sidebar eGPU icon
└── bp-egpu-storage             + both of the above
    └── bp-egpu-storage-cangps  + Ford CAN GPS (cangpsd)
```

Rule: **upstream changes land on `bp-sp-sync-2026-08` only**, then the feature
branches are rebased onto it. Never merge upstream into a feature branch directly —
you end up with the same upstream commits appearing on divergent bases.

## 2. Remotes

```bash
git remote add sunnypilot https://github.com/sunnypilot/sunnypilot.git
git remote add bluepilot  https://github.com/BluePilotDev/bluepilot.git
git remote add spopendbc  https://github.com/sunnypilot/opendbc.git   # for opendbc comparisons
```

Careful: `git remote | grep bluepilot` also matches forks whose URL contains
"bluepilot" (e.g. cgrin's). Use `git remote | grep -qx bluepilot`.

## 3. The two upstreams behave completely differently

### sunnypilot — merge works

Same tree layout as us, so a normal merge is correct:

```bash
git checkout bp-sp-sync-2026-08
git branch -f backup-pre-merge-$(date +%F) bp-sp-sync-2026-08
git fetch sunnypilot master
git merge sunnypilot/master
```

Expect exactly one recurring conflict: `opendbc_repo`. Upstream tracks it as a
submodule gitlink; we vendor it as a real tree. Git creates a
`opendbc_repo~sunnypilot_master` artifact. Always resolve by **keeping our vendored
tree**:

```bash
git rm -q --cached 'opendbc_repo~sunnypilot_master'
rm -rf 'opendbc_repo~sunnypilot_master'
```

`.gitmodules` must never gain an opendbc entry, and `git ls-files -s opendbc_repo`
must show mode `100644` files (~533 of them), not `160000`.

### BluePilotDev/bp-dev — merge does NOT work

bp-dev predates the tree restructure. A merge makes git create stray
`openpilot/common~bluepilot_bp-dev`, `openpilot/selfdrive~bluepilot_bp-dev`
directories because it cannot map the layouts. **Apply commits as path-remapped
patches instead:**

```bash
git fetch bluepilot bp-dev
git log --oneline <last-applied>..bluepilot/bp-dev      # find what is new

# root-level paths (.gitattributes, pyproject.toml) and opendbc_repo/ apply as-is:
git show --format="" <sha> > /tmp/p.patch && git apply /tmp/p.patch

# common/, selfdrive/, system/, sunnypilot/ need the openpilot/ prefix:
git show --format="" <sha> \
  | sed -E 's|^diff --git a/(common\|selfdrive\|system\|sunnypilot)/|diff --git a/openpilot/\1/|;
            s|^--- a/(common\|selfdrive\|system\|sunnypilot)/|--- a/openpilot/\1/|;
            s|^\+\+\+ b/(common\|selfdrive\|system\|sunnypilot)/|+++ b/openpilot/\1/|' > /tmp/p.patch
git apply --check /tmp/p.patch && git apply /tmp/p.patch
```

Preserve the original author: `git commit --author="Name <email>"` and add a
`(cherry picked from commit <sha>)` trailer plus a note on what you remapped.

## 4. The restructure, in one table

Upstream moved everything under `openpilot/`. bp-dev and older forks did not.

| pre-restructure | here |
|---|---|
| `common/…`, `selfdrive/…`, `system/…`, `sunnypilot/…`, `cereal/…` | `openpilot/…` |
| `opendbc_repo/…` | unchanged |
| `bluepilot/…` | unchanged (root-level, and symlinked at `openpilot/bluepilot`) |
| `from cereal import log` | `from openpilot.cereal import log` |
| `from cereal import car` | `from opendbc.car.structs import car` |
| `import cereal.messaging as messaging` | `import openpilot.cereal.messaging as messaging` |
| `from openpilot.system.hardware import …` | `from openpilot.common.hardware import …` |
| `TICI` | `COMMA_HARDWARE` (`TICI` no longer exists) |

`openpilot/bluepilot` is a **committed symlink** (mode `120000`) to `../bluepilot`,
which is why `openpilot.bluepilot.*` imports resolve. `find` will not follow it.

## 5. Failure classes — the actual gotchas

Every one of these produced a device that built cleanly and then failed at runtime.
None were caught by the build.

### 5a. Modules that moved or vanished
`common/params_pyx.pyx` was deleted; `UnknownKeyName` now lives in
`openpilot/common/params.py`. Upstream also replaced pyserial with
`openpilot/common/serial.py`, which defines its **own** `SerialException` — importing
pyserial's identically-named class means `except` never matches.

### 5b. SubMaster service renames
`liveCalibration → extrinsicsCalibration`, `liveParameters → vehicleParameters`,
`liveDelay → lateralDelay`. `SubMaster` raises `KeyError` for an unsubscribed
service, and UI code often touches a service on one screen only — so it fires
minutes in, not at boot.

### 5c. capnp *field* renames
`RadarState.LeadData.status → present`. Fields also move into `deprecated :group`
blocks, after which they must be read as `lead.deprecated.aRel`. capnp only raises
when the struct is actually populated — i.e. seconds into a drive.

**Two different structs can share a simple name.** `log.capnp` has
`RadarState.LeadData` (has `present`); `custom.capnp` has a separate `LeadData`
(has `status`). Any checker that keys structs by simple name will merge them and
report a false negative.

### 5d. Enum value renames
`SteerControlType.curvatureDEPRECATED → curvature` killed `controlsd` instantly.
A field-level schema diff will **not** catch this — enum members need their own pass.

### 5e. Symbol renames sweeping a whole feature
`usbgpu → chestnut` (#38703) renamed params, helpers, ui_state attributes and icon
assets at once. The merge reported **no conflicts** because BluePilot's eGPU code
lives in files upstream did not touch — so the references went stale silently and
the icon would simply have drawn nothing.

### 5f. Dependencies dropped from `uv.lock`
`bp_build.py` runs `uv sync --frozen`, so **`uv.lock` is what installs — declaring a
dep in `pyproject.toml` alone does nothing.** bp-dev shipped `pyserial`, `psutil`,
`xattr`, `qrcode`; upstream does not.

Most such imports are wrapped in `try/except ImportError`, so a missing one degrades
a feature silently instead of crashing. `qcomgpsd`'s was not guarded, which is the
only reason it was noticed.

**Unresolved:** `/data/openpilot/.venv` on device contains only `.op_synced_lock` —
no `bin/`, no `lib/` — while the runtime python is `/usr/local/venv`. So
`sync_python_env()` may not be installing into the venv the device imports from.
Worth investigating before relying on any lockfile addition.

### 5g. The vendored opendbc is stale
This is the big one. We vendor `opendbc_repo` as a real tree, so the sunnypilot sync
updates `openpilot/` **around** it. Stock upstream code then reaches for schema the
old opendbc does not have. It has bitten four times:
`liveParameters`, `CarState.carNotReady`, `CarControl.driverMonitoringEscalation`,
`SteerControlType.curvature`.

`car.capnp` has been swept for fields, enums and structs against upstream's pin, so
the *schema* interface should be clean. The **Python and safety code in that tree is
still ~170 files behind**. Syncing it properly is its own project and should preserve
the 25 BluePilot-marked files in there.

## 6. Verification recipe

Run all of these after any sync, before flashing. They are cheap and each one caught
a real bug.

```bash
# 1. every openpilot/bluepilot import resolves to a real file
#    (expect only build-generated misses: cereal.log/custom, acados c_generated_code)

# 2. every SubMaster/PubMaster name exists in services.py
#    MUST include opendbc_repo/ -- skipping it hid the liveParameters crash

# 3. schema diff vs the previous known-good tree: fields AND enums AND structs
git show <old-ref>:openpilot/cereal/log.capnp > /tmp/old.capnp   # then diff field sets

# 4. schemas still compile (authoritative -- catches duplicate ordinals)
cd openpilot/cereal && capnp compile -o- -I<dir-with-car.capnp> -I. log.capnp
cd opendbc_repo/opendbc/car && capnp compile -o- -I. car.capnp

# 5. BluePilot marker census -- must not drop (currently 397)
git grep -c "BluePilot:" -- '*.py' '*.cc' '*.h' '*.sh' '*.toml' | awk -F: '{s+=$2} END{print s}'

# 6. after a rename-heavy sync, grep for the OLD names explicitly
git grep -n "usbgpu\|UsbGpu\|egpu\.png" -- '*.py'
```

Notes on writing checkers, learned the hard way:

- **Sanity-test the checker against a bug it should catch**, by re-introducing one.
  Two checkers written during this work silently failed that test.
- Scope structs by qualified path, not simple name (see 5c).
- capnp named groups are written `name :group {`, not `group name {`.
- Follow `msgq.*`/`opendbc.*` imports too, not just `openpilot.*` — `VisionStreamType`
  moved *out of* msgq.
- **Stubbed enum members all compare equal.** If the harness stubs a module that
  exports an enum (e.g. `ChestnutState`), every state assertion becomes a tautology
  that passes regardless. Give the stub a real `enum.Enum`.
- When sanity-testing by temporarily breaking a file, restore from a **saved copy**,
  not `git checkout <file>` — that restores from HEAD and silently discards whatever
  else was uncommitted in it.

## 7. Running tests without a built tree

Most suites need compiled artifacts (`libparams_c`, `msgq`, `opendbc.can.parser`).
A stub harness makes them runnable on a laptop: pre-stub `capnp`, `openpilot.cereal`,
`openpilot.common.params`, `openpilot.selfdrive.ui.ui_state`, plus a `sys.meta_path`
finder that stubs any non-`openpilot`/`bluepilot`/`opendbc` module. pyray stubs must
return **numbers** (gui_app does arithmetic at import); everything else should return
objects with permissive attributes.

Set `PYTHONPATH=.:opendbc_repo`. Suites: sidebar eGPU 12, external storage 54,
cangpsd 90, ALP lane-center-trim 27.

`uv lock` locally needs the path-dependency submodules checked out
(`git submodule update --init --depth 1 panda rednose_repo teleoprtc_repo tinygrad_repo msgq_repo`)
and `--python 3.12.12`, because `.python-version` pins 3.12.13 which uv cannot fetch
for macOS arm64.

## 8. Device debugging

`manager` only wraps **its own** startup in a try/except + TextWindow. A managed child
that dies is just logged — so a dead `ui` leaves the boot splash up with no error on
screen, which looks identical to a hung boot.

```bash
# a process's own traceback
grep -ah '"daemon": "ui"' /data/log/* | grep -a '"msg$s": "crash"' | tail -1
ls -t /data/community/crashes/ | head

# how it died: -9 = SIGKILL (OOM), 1 = exception, 0 = clean stop (manager asked it to)
grep -ah "is dead with" /data/log/* | tail

# which process manager thinks should be running but isn't
grep -ah "process_not_running" /data/log/* | tail -3
```

`dmesg` does **not** survive a reboot — capture it before rebooting or the OOM
evidence is gone. Params under `/data/params/d/` flagged `CLEAR_ON_MANAGER_START`
(e.g. `ChestnutActive`) are empty after a reboot and tell you nothing.

**SSH after a flash:** sshd reads `/data/params/d/GithubSshKeys` directly as its
authorized-keys file, and a factory reset wipes `/data`. Re-add via Settings →
Developer → SSH (it fetches `github.com/<user>.keys`) *before* you need it.

## 9. Propagating to the feature branches

```bash
OLD=<previous sync tip>; NEW=<new sync tip>
for b in bp-external-storage bp-egpu-3x bp-egpu-storage; do
  git branch -f backup-$b $b
  git rebase --onto $NEW $OLD $b
done
# cangps sits on bp-egpu-storage, not on the sync
git rebase --onto bp-egpu-storage <old bp-egpu-storage tip> bp-egpu-storage-cangps
```

Duplicate commits (e.g. a bp-dev commit already cherry-picked here) are dropped
automatically — rebase reports *"patch contents already upstream"*.

If a rename-heavy sync broke a feature branch, it is often cleaner to rebuild the
stack than to fight successive rebases: fix the lowest branch, then `git branch -f`
the next one onto it and cherry-pick that branch's own commit back.

**Put each fix on the lowest branch that needs it.** A fix committed on
`bp-egpu-storage` does not reach `bp-egpu-3x`; committed on `bp-egpu-3x` it reaches
both, plus cangps. If you notice after committing, cherry-pick it down and rebuild
the stack above — cheaper than three divergent copies.

Then verify per branch and `git push --force-with-lease`.

## 10. Preferred pattern: delegate to upstream, keep the delta small

When upstream grows a feature BluePilot already had, prefer **driving BluePilot's
version from upstream's state** over keeping a parallel implementation. Less code to
re-verify each sync, and upstream's improvements arrive for free.

Worked example — the eGPU icon. Upstream added a six-state `ChestnutState`
(DISCONNECTED/UNCOMPILED/READY/LOADING/ACTIVE/FAILED); BluePilot had its own three
colours. Rather than pick one, the icon now reads `ui_state.chestnut_state` and adds
a single check for the one thing upstream cannot express: `chestnutPresent` means
only that the ASM bridge enumerated over USB, so an empty dock is indistinguishable
from a populated one. `chestnut_link_up` (trained PCIe link) is the difference.

Net effect: gained LOADING and FAILED, kept the link distinction, and BluePilot's
custom surface shrank to one `if`. That is the shape to aim for.

Ordering within such a mapping matters — put the most actionable state first
(FAILED before the link check, so a model failure is not masked by a quiet probe).

## 11. Things deliberately not done

- **opendbc_repo full sync** (~170 files, +8.5k/-6.2k vs upstream's pin 06743dfb3).
  The real fix for 5g; needs its own session and must preserve the 25 BluePilot-marked
  files in that tree.
- `bluepilot/system/tests` in pyproject `testpaths` — upstream removed that key in
  the restructure, so there is no target here.
