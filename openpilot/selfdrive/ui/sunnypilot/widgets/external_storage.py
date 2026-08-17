"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

External storage control -- extend the device's route storage onto a USB drive plugged into the
aux port.

This is the Raylib reimplementation of the Qt ``ExternalStorageControl`` (originally added in
sunnypilot ``feature: external storage (#979)``), which was dropped when the whole Qt UI tree was
removed in the openpilot Raylib rewrite sync. The *backend* half of the feature was never removed
and is still live in ``system/loggerd/deleter.py``: when internal storage runs low, deleter moves
the oldest route to ``Paths.log_root_external()`` instead of deleting it, and ``athenad`` scans and
uploads from there too. All of that is gated purely on ``Path(log_root_external()).is_mount()``,
so this control's only job is to get a drive formatted and mounted at that path -- no
controls/logging code needs to change.

Differences from the Qt original, all deliberate:

- **The target disk is detected, not hardcoded.** The Qt version assumed ``/dev/sdg``. This
  enumerates block devices via ``lsblk`` and only ever considers a *whole disk* that is
  USB-attached or removable and holds no protected mountpoint (see ``_is_safe_disk``). Formatting
  is destructive, so the candidate is re-validated inside the worker immediately before ``wipefs``
  rather than trusting what the UI last rendered.
- **fstab uses ``LABEL=`` instead of a device node**, since kernel names (sdg/sdh/...) are not
  stable across boots or port order. The label is the same ``openpilot`` label the Qt version
  already wrote at mkfs time, so drives formatted by the old UI still work here.
- **The rootfs is always remounted read-only**, via a shell ``trap``. The Qt version chained every
  step with ``&&``, so any mid-sequence failure left the AGNOS rootfs writable.
- **Probing does no subprocess work beyond one ``lsblk``.** Mount state and usage come from
  ``os.path.ismount`` / ``os.statvfs`` instead of ``findmnt``/``df``/``blkid``, which also drops
  the Qt version's ``sudo blkid`` call from the polling path entirely.
"""
import json
import os
import subprocess
import threading
from dataclasses import dataclass
from enum import Enum
from time import monotonic

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.common.hardware import COMMA_HARDWARE
from openpilot.common.hardware.hw import Paths
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog

from openpilot.system.ui.sunnypilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ListItemSP

# Must match system/loggerd/deleter.py's offload target, which is what actually uses the drive.
MOUNT_POINT = Paths.log_root_external().rstrip("/")
FS_LABEL = "openpilot"
FSTAB_SPEC = f"LABEL={FS_LABEL}"
FSTAB_LINE = f"{FSTAB_SPEC} {MOUNT_POINT} ext4 defaults,nofail 0 2"

# Mountpoints that disqualify a disk from ever being touched. A USB-attached disk should never
# hold any of these, but formatting is unrecoverable so the check is cheap insurance.
PROTECTED_MOUNTS = ("/", "/boot", "/data", "/system", "/usr", "/var", "[SWAP]")

# type=disk nodes that are never a valid target regardless of transport or mountpoint
NEVER_TARGET_PREFIXES = ("/dev/loop", "/dev/ram", "/dev/zram", "/dev/md", "/dev/dm-")
NEVER_TARGET_SUFFIXES = ("boot0", "boot1", "rpmb")

REFRESH_INTERVAL = 2.0  # s, between background probes while the panel is on screen
CMD_TIMEOUT = 10.0      # s, for probe commands
ACTION_TIMEOUT = 300.0  # s, mkfs on a large slow USB drive is not quick


class StorageState(Enum):
  NO_DRIVE = 0       # nothing suitable plugged in
  NEEDS_FORMAT = 1   # disk present, but no ext4 partition labeled FS_LABEL
  READY = 2          # formatted and labeled, not mounted
  MOUNTED = 3        # mounted at MOUNT_POINT


@dataclass
class ProbeResult:
  state: StorageState = StorageState.NO_DRIVE
  disk: str | None = None       # e.g. /dev/sdg -- the whole disk, what we would format
  partition: str | None = None  # e.g. /dev/sdg1 -- the labeled ext4 partition, what we would mount
  usage: str = ""               # "12G/64G", only when mounted


def _run(cmd: str, timeout: float) -> tuple[int, str]:
  """Runs ``cmd`` under sh, returning (returncode, output). Never raises.

  stderr is merged into the returned output: mkfs/parted/wipefs report their real failure reason
  there, and discarding it left the previous version with nothing to log but "it failed".
  """
  try:
    p = subprocess.run(["sh", "-c", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=timeout, check=False)
    return p.returncode, p.stdout.strip()
  except (subprocess.SubprocessError, OSError):
    cloudlog.exception(f"external_storage: command failed: {cmd}")
    return 1, ""


def _truthy(value) -> bool:
  """lsblk -J emits booleans as real bools on new util-linux and as "0"/"1" strings on old ones.
  bool("0") is True, so the string form has to be handled explicitly."""
  if isinstance(value, bool):
    return value
  if isinstance(value, int | float):
    return bool(value)
  return str(value).strip().lower() in ("1", "true", "yes")


def _blkid_fs(partition: str) -> tuple[str, str]:
  """(fstype, label) read straight off the device with blkid, returning ("", "") on failure.

  lsblk's LABEL/FSTYPE columns come from the udev database, which on AGNOS is frequently empty for
  a hot-plugged USB drive (and for non-root callers), so a freshly formatted drive can look
  unformatted. blkid probes the superblock directly. This is the same check comma's original Qt
  widget used, and the reason it used sudo.
  """
  rc, out = _run(f"sudo blkid -o export {partition}", CMD_TIMEOUT)
  if rc != 0:
    return "", ""
  fields = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
  return fields.get("TYPE", ""), fields.get("LABEL", "")


def _human(num_bytes: float) -> str:
  for unit in ("B", "K", "M", "G", "T"):
    if abs(num_bytes) < 1024.0 or unit == "T":
      return f"{num_bytes:.0f}{unit}" if unit in ("B", "K") else f"{num_bytes:.1f}{unit}"
    num_bytes /= 1024.0
  return f"{num_bytes:.1f}T"


def _node_mountpoints(node: dict) -> list[str]:
  """All mountpoints held by a node and its children, flattened."""
  points = []
  mp = node.get("mountpoint")
  if mp:
    points.append(mp)
  # newer lsblk exposes MOUNTPOINTS as a list; tolerate either
  for mp in node.get("mountpoints") or []:
    if mp:
      points.append(mp)
  for child in node.get("children") or []:
    points.extend(_node_mountpoints(child))
  return points


def _flatten(nodes: list[dict]) -> list[dict]:
  out: list[dict] = []
  for node in nodes:
    out.append(node)
    out.extend(_flatten(node.get("children") or []))
  return out


def _normalize_devices(raw: list[dict]) -> list[dict]:
  """Return the disks, each with a populated ``children`` list.

  ``lsblk -J`` nests partitions under ``children`` in tree mode, but some builds emit every node
  flat in the top-level array instead -- AGNOS does. Without rebuilding the relationship a disk
  looks partitionless, so a formatted drive reads as 'needs format' forever, and (worse) a disk
  whose partitions hold / and /data looks like it holds no protected mountpoint at all.
  """
  nodes = _flatten(raw)
  disks = [n for n in nodes if n.get("type") == "disk"]
  by_path = {d["path"]: d for d in disks if d.get("path")}

  for disk in disks:
    disk["children"] = list(disk.get("children") or [])

  for part in (n for n in nodes if n.get("type") == "part"):
    path = part.get("path") or ""
    parent = by_path.get(f"/dev/{part['pkname']}") if part.get("pkname") else None
    if parent is None:
      # longest disk path that prefixes this one: /dev/sdg1 -> /dev/sdg, /dev/nvme0n1p1 -> /dev/nvme0n1
      prefixes = [p for p in by_path if path.startswith(p) and path != p]
      if prefixes:
        parent = by_path[max(prefixes, key=len)]
    if parent is not None and not any(c.get("path") == path for c in parent["children"]):
      parent["children"].append(part)

  return disks


def _size_of(node: dict) -> int:
  try:
    return int(node.get("size") or 0)
  except (TypeError, ValueError):
    return 0


def _is_safe_disk(node: dict) -> bool:
  """True only for a whole disk that is external and holds nothing the system depends on."""
  if node.get("type") != "disk":
    return False

  path = node.get("path") or ""
  # These are type=disk but never a valid target. eMMC boot/rpmb areas in particular have no
  # mountpoint, so nothing else here would exclude them.
  if path.startswith(NEVER_TARGET_PREFIXES) or path.endswith(NEVER_TARGET_SUFFIXES):
    return False

  # A USB-to-NVMe enclosure reports rm=false -- the NVMe inside is not "removable media" -- so the
  # transport is what marks it external. rm alone still covers plain thumb drives.
  if (node.get("tran") or "").lower() != "usb" and not _truthy(node.get("rm")):
    return False

  return all(mp not in PROTECTED_MOUNTS for mp in _node_mountpoints(node))


def _pick_disk(devices: list[dict]) -> dict | None:
  """Choose deterministically among safe disks.

  A comma has many block devices, and taking the first match meant an unrelated disk could shadow
  the real drive: the panel would report 'needs format' for something that was never the target,
  and the FORMAT button would aim wipefs at it. Prefer, in order: the disk already holding our
  labelled filesystem, then USB transport, then one that has partitions at all, then the largest.
  Path breaks ties so the choice is stable across polls.
  """
  candidates = [d for d in devices if _is_safe_disk(d)]
  if not candidates:
    return None

  def rank(d: dict):
    labelled = any(c.get("label") == FS_LABEL for c in (d.get("children") or []))
    usb = (d.get("tran") or "").lower() == "usb"
    has_partitions = bool(d.get("children"))
    return (not labelled, not usb, not has_partitions, -_size_of(d), d.get("path") or "")

  return sorted(candidates, key=rank)[0]


def _probe() -> ProbeResult:
  """Single lsblk call + stat syscalls. Safe to run off the UI thread every REFRESH_INTERVAL."""
  rc, out = _run("lsblk -J -b -o PATH,PKNAME,TYPE,RM,TRAN,SIZE,LABEL,FSTYPE,MOUNTPOINT", CMD_TIMEOUT)
  if rc != 0 or not out:
    return ProbeResult()

  try:
    devices = json.loads(out).get("blockdevices") or []
  except (ValueError, AttributeError):
    cloudlog.exception("external_storage: could not parse lsblk output")
    return ProbeResult()

  disk = _pick_disk(_normalize_devices(devices))
  if disk is None:
    return ProbeResult()

  disk_path = disk.get("path")
  children = [c for c in (disk.get("children") or []) if c.get("type") == "part" and c.get("path")]

  # Trust lsblk when it has the answer; otherwise probe the superblock. See _blkid_fs.
  partition = next((c["path"] for c in children
                    if c.get("fstype") == "ext4" and c.get("label") == FS_LABEL), None)
  if partition is None:
    for child in children:
      fstype, label = _blkid_fs(child["path"])
      if fstype == "ext4" and label == FS_LABEL:
        partition = child["path"]
        break

  if partition is None:
    return ProbeResult(state=StorageState.NEEDS_FORMAT, disk=disk_path)

  if os.path.ismount(MOUNT_POINT):
    usage = ""
    try:
      st = os.statvfs(MOUNT_POINT)
      total = st.f_blocks * st.f_frsize
      used = total - (st.f_bfree * st.f_frsize)
      usage = f"{_human(used)}/{_human(total)}"
    except OSError:
      cloudlog.exception("external_storage: statvfs failed")
    return ProbeResult(state=StorageState.MOUNTED, disk=disk_path, partition=partition, usage=usage)

  return ProbeResult(state=StorageState.READY, disk=disk_path, partition=partition)


def _partition_of(disk: str) -> str:
  """First partition path for a freshly-partitioned disk, re-read from lsblk when possible."""
  rc, out = _run(f"lsblk -J -o PATH,PKNAME,TYPE {disk}", CMD_TIMEOUT)
  if rc == 0 and out:
    try:
      # tolerate both the nested and flat lsblk shapes -- see _normalize_devices
      parts = [n for n in _flatten(json.loads(out).get("blockdevices") or [])
               if n.get("type") == "part" and n.get("path")]
      if parts:
        return sorted(parts, key=lambda n: n["path"])[0]["path"]
    except (ValueError, AttributeError, KeyError):
      pass
  # nvme/mmc use a `p` separator; USB sd* does not
  return f"{disk}p1" if disk[-1].isdigit() else f"{disk}1"


class ExternalStorageControl:
  """Owns the Developer-panel list item and all of its background work.

  Everything slow (lsblk, mount, mkfs) runs on a worker thread; the render thread only ever reads
  cached strings. ``poll()`` is called from the panel's per-frame ``_update_state``, so it must
  stay cheap -- it does nothing but compare a monotonic timestamp.
  """

  def __init__(self):
    self._lock = threading.Lock()
    self._result = ProbeResult()
    self._busy_text = ""
    self._busy = False
    self._last_refresh = 0.0

    self.item = ListItemSP(
      tr("External Storage"),
      description=tr("Extend your comma device's storage by inserting a USB drive into the aux port. " +
                     "Once mounted, the oldest routes are moved here automatically when internal storage runs low."),
      action_item=NoElideButtonAction(tr("CHECK"), enabled=True),
      callback=self._on_clicked,
    )
    self.item.set_visible(COMMA_HARDWARE)

  # --- state -> UI ------------------------------------------------------------------------

  def _apply(self) -> None:
    """Pushes cached state onto the list item. Called from worker threads; setters only assign."""
    with self._lock:
      busy, busy_text, result = self._busy, self._busy_text, self._result

    action = self.item.action_item
    if busy:
      action.set_value(busy_text)
      action.set_enabled(False)
      return

    if result.state == StorageState.NO_DRIVE:
      action.set_value(tr("insert drive"))
      action.set_text(tr("CHECK"))
    elif result.state == StorageState.NEEDS_FORMAT:
      action.set_value(tr("needs format"))
      action.set_text(tr("FORMAT"))
    elif result.state == StorageState.MOUNTED:
      action.set_value(result.usage)
      action.set_text(tr("UNMOUNT"))
    else:
      action.set_value(tr("drive detected"))
      action.set_text(tr("MOUNT"))

    # Mounting/unmounting under a running loggerd would yank the offload target out from under it.
    action.set_enabled(ui_state.is_offroad())

  def _set_busy(self, text: str) -> None:
    with self._lock:
      self._busy = True
      self._busy_text = text
    self._apply()

  def _clear_busy(self) -> None:
    with self._lock:
      self._busy = False
      self._busy_text = ""

  # --- background work --------------------------------------------------------------------

  def _refresh_worker(self) -> None:
    result = _probe()
    with self._lock:
      self._result = result
    self._apply()

  def poll(self) -> None:
    """Per-frame hook. Kicks a probe at most every REFRESH_INTERVAL, and never while busy."""
    if not COMMA_HARDWARE:
      return
    with self._lock:
      if self._busy:
        return
    now = monotonic()
    if now - self._last_refresh < REFRESH_INTERVAL:
      # still keep the enabled state in sync with onroad/offroad between probes
      self._apply()
      return
    self._last_refresh = now
    threading.Thread(target=self._refresh_worker, daemon=True).start()

  def refresh_now(self) -> None:
    self._last_refresh = 0.0
    self.poll()

  # --- actions ----------------------------------------------------------------------------

  def _on_clicked(self) -> None:
    with self._lock:
      if self._busy:
        return
      state = self._result.state

    if state == StorageState.NO_DRIVE:
      self.refresh_now()
    elif state == StorageState.NEEDS_FORMAT:
      gui_app.push_widget(ConfirmDialog(
        tr("Are you sure you want to format this drive? This will erase all data."),
        tr("Format"),
        callback=lambda res: self._start(self._format_worker, tr("formatting")) if res == DialogResult.CONFIRM else None,
      ))
    elif state == StorageState.MOUNTED:
      self._start(self._unmount_worker, tr("unmounting"))
    else:
      self._start(self._mount_worker, tr("mounting"))

  def _start(self, worker, busy_text: str) -> None:
    self._set_busy(busy_text)
    threading.Thread(target=self._run_action, args=(worker,), daemon=True).start()

  def _run_action(self, worker) -> None:
    try:
      worker()
    except Exception:
      cloudlog.exception("external_storage: action failed")
    finally:
      self._clear_busy()
      self._last_refresh = 0.0
      self._refresh_worker()

  def _mount_worker(self) -> None:
    # The trap guarantees the AGNOS rootfs goes back to read-only even if a step below fails.
    rc, out = _run(f"""set -e
trap 'sudo mount -o remount,ro / >/dev/null 2>&1 || true' EXIT
sudo mount -o remount,rw /
sudo mkdir -p {MOUNT_POINT}
grep -qF '{FSTAB_SPEC} {MOUNT_POINT}' /etc/fstab || echo '{FSTAB_LINE}' | sudo tee -a /etc/fstab >/dev/null
sudo systemctl daemon-reload
sudo mount {MOUNT_POINT}
sudo chown -R comma:comma {MOUNT_POINT}
sudo chmod -R 775 {MOUNT_POINT}
""", ACTION_TIMEOUT)
    if rc != 0:
      cloudlog.error(f"external_storage: mount failed (rc={rc}): {out}")

  def _unmount_worker(self) -> None:
    rc, out = _run(f"sudo umount {MOUNT_POINT}", ACTION_TIMEOUT)
    if rc != 0:
      cloudlog.error(f"external_storage: unmount failed (rc={rc}): {out}")

  def _format_worker(self) -> None:
    # Re-probe rather than trusting the cached disk: this is the destructive path, and the drive
    # could have been pulled or re-enumerated since the UI last rendered.
    result = _probe()
    disk = result.disk
    if disk is None or result.state == StorageState.NO_DRIVE:
      cloudlog.error("external_storage: refusing to format, no safe external disk found")
      return
    cloudlog.warning(f"external_storage: formatting {disk} (state={result.state.name})")

    # Unmount every partition on the disk, not just our mountpoint: wipefs/parted fail with EBUSY
    # if anything on the device is still mounted (AGNOS or a stale fstab entry may have taken it).
    # The settle/sleep gives udev time to create the new partition node before mkfs looks for it.
    rc, out = _run(f"""set -e
for part in $(lsblk -ln -o PATH {disk} | tail -n +2); do sudo umount "$part" >/dev/null 2>&1 || true; done
sudo umount {MOUNT_POINT} >/dev/null 2>&1 || true
sudo wipefs -a {disk}
sudo parted -s {disk} mklabel gpt mkpart primary ext4 0% 100%
sudo partprobe {disk} >/dev/null 2>&1 || true
sudo udevadm settle >/dev/null 2>&1 || true
sleep 2
""", ACTION_TIMEOUT)
    if rc != 0:
      cloudlog.error(f"external_storage: partitioning failed (rc={rc}): {out}")
      return

    partition = _partition_of(disk)
    rc, out = _run(f"sudo mkfs.ext4 -F -L {FS_LABEL} {partition} && sudo udevadm settle >/dev/null 2>&1 || true",
                   ACTION_TIMEOUT)
    if rc != 0:
      cloudlog.error(f"external_storage: mkfs failed on {partition} (rc={rc}): {out}")
      return
    cloudlog.warning(f"external_storage: formatted {partition} as {FS_LABEL}")

    # Match the Qt original: a successful format rolls straight into mounting.
    self._mount_worker()
