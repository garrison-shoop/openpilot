"""External storage control: safe disk selection, probe state machine, and format guards.

The destructive paths here (wipefs/parted/mkfs) are the reason most of these tests exist: the
control must never resolve to anything but an external disk holding no system mountpoint.
"""
import json
import os
from types import SimpleNamespace

from openpilot.selfdrive.ui.sunnypilot.widgets import external_storage as es


def lsblk(devices):
  return json.dumps({"blockdevices": devices})


USB_UNFORMATTED = {"path": "/dev/sdg", "type": "disk", "rm": True, "tran": "usb", "children": []}
USB_FORMATTED = {"path": "/dev/sdg", "type": "disk", "rm": True, "tran": "usb", "children": [
  {"path": "/dev/sdg1", "type": "part", "fstype": "ext4", "label": "openpilot", "mountpoint": None}]}
INTERNAL = {"path": "/dev/nvme0n1", "type": "disk", "rm": False, "tran": "nvme", "children": [
  {"path": "/dev/nvme0n1p1", "type": "part", "fstype": "ext4", "label": "data", "mountpoint": "/data"}]}
# A USB enclosure that somehow holds the rootfs -- must never be picked.
USB_HOLDING_ROOT = {"path": "/dev/sdb", "type": "disk", "rm": True, "tran": "usb", "children": [
  {"path": "/dev/sdb1", "type": "part", "fstype": "ext4", "label": "x", "mountpoint": "/"}]}


def probe_with(monkeypatch, devices, ismount=False, rc=0, blkid=None):
  """blkid: {partition_path: "TYPE=ext4\\nLABEL=openpilot"} for the superblock fallback."""
  def fake_run(cmd, timeout):
    if cmd.startswith("sudo blkid"):
      part = cmd.split()[-1]
      return (0, (blkid or {}).get(part, "")) if blkid and part in blkid else (2, "")
    return rc, lsblk(devices)
  monkeypatch.setattr(es, "_run", fake_run)
  monkeypatch.setattr(os.path, "ismount", lambda p: ismount)
  monkeypatch.setattr(os, "statvfs", lambda p: SimpleNamespace(f_blocks=1000, f_frsize=1024 ** 2, f_bfree=400))
  return es._probe()


class TestSafeDiskSelection:
  def test_internal_disk_never_selected(self):
    assert not es._is_safe_disk(INTERNAL)

  def test_usb_holding_root_never_selected(self):
    assert not es._is_safe_disk(USB_HOLDING_ROOT)

  def test_protected_mount_detected_via_mountpoints_list(self):
    # newer lsblk reports MOUNTPOINTS as a list rather than a scalar
    node = {"path": "/dev/sdb", "type": "disk", "rm": True, "tran": "usb",
            "children": [{"path": "/dev/sdb1", "type": "part", "mountpoints": ["/data"]}]}
    assert not es._is_safe_disk(node)

  def test_partition_node_never_selected(self):
    assert not es._is_safe_disk({"path": "/dev/sdg1", "type": "part", "rm": True, "tran": "usb"})

  def test_non_removable_non_usb_rejected(self):
    assert not es._is_safe_disk({"path": "/dev/sda", "type": "disk", "rm": False, "tran": "sata"})

  def test_plain_usb_disk_accepted(self):
    assert es._is_safe_disk(USB_UNFORMATTED)

  def test_removable_without_usb_transport_accepted(self):
    assert es._is_safe_disk({"path": "/dev/sdg", "type": "disk", "rm": True, "tran": None})


class TestProbe:
  def test_no_drive(self, monkeypatch):
    r = probe_with(monkeypatch, [INTERNAL])
    assert r.state == es.StorageState.NO_DRIVE
    assert r.disk is None

  def test_needs_format(self, monkeypatch):
    r = probe_with(monkeypatch, [INTERNAL, USB_UNFORMATTED])
    assert r.state == es.StorageState.NEEDS_FORMAT
    assert r.disk == "/dev/sdg"

  def test_wrong_label_needs_format(self, monkeypatch):
    dev = {"path": "/dev/sdg", "type": "disk", "rm": True, "tran": "usb", "children": [
      {"path": "/dev/sdg1", "type": "part", "fstype": "ext4", "label": "MYUSB"}]}
    assert probe_with(monkeypatch, [dev]).state == es.StorageState.NEEDS_FORMAT

  def test_wrong_fstype_needs_format(self, monkeypatch):
    dev = {"path": "/dev/sdg", "type": "disk", "rm": True, "tran": "usb", "children": [
      {"path": "/dev/sdg1", "type": "part", "fstype": "vfat", "label": "openpilot"}]}
    assert probe_with(monkeypatch, [dev]).state == es.StorageState.NEEDS_FORMAT

  def test_ready_when_formatted_but_not_mounted(self, monkeypatch):
    r = probe_with(monkeypatch, [USB_FORMATTED], ismount=False)
    assert r.state == es.StorageState.READY
    assert r.partition == "/dev/sdg1"

  def test_mounted_reports_usage(self, monkeypatch):
    r = probe_with(monkeypatch, [USB_FORMATTED], ismount=True)
    assert r.state == es.StorageState.MOUNTED
    # 1000 blocks * 1MiB, 400 free -> 600M used of 1000M
    assert r.usage == "600.0M/1000.0M"

  def test_lsblk_failure_degrades_to_no_drive(self, monkeypatch):
    assert probe_with(monkeypatch, [], rc=1).state == es.StorageState.NO_DRIVE

  def test_malformed_json_degrades_to_no_drive(self, monkeypatch):
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (0, "not json{"))
    assert es._probe().state == es.StorageState.NO_DRIVE


class TestBlkidFallback:
  """AGNOS often leaves lsblk's LABEL/FSTYPE blank for hot-plugged USB, which made a successfully
  formatted drive keep reporting 'needs format'. blkid probes the superblock directly."""

  # lsblk sees the partition but reports no fs metadata at all
  BLANK_LSBLK = {"path": "/dev/sdg", "type": "disk", "rm": True, "tran": "usb", "children": [
    {"path": "/dev/sdg1", "type": "part", "fstype": None, "label": None}]}

  def test_blank_lsblk_falls_back_to_blkid(self, monkeypatch):
    r = probe_with(monkeypatch, [self.BLANK_LSBLK],
                   blkid={"/dev/sdg1": "TYPE=ext4\nLABEL=openpilot\nUUID=abc"})
    assert r.state == es.StorageState.READY
    assert r.partition == "/dev/sdg1"

  def test_blkid_mounted_reports_usage(self, monkeypatch):
    r = probe_with(monkeypatch, [self.BLANK_LSBLK], ismount=True,
                   blkid={"/dev/sdg1": "TYPE=ext4\nLABEL=openpilot"})
    assert r.state == es.StorageState.MOUNTED

  def test_blkid_wrong_label_still_needs_format(self, monkeypatch):
    r = probe_with(monkeypatch, [self.BLANK_LSBLK],
                   blkid={"/dev/sdg1": "TYPE=ext4\nLABEL=SANDISK"})
    assert r.state == es.StorageState.NEEDS_FORMAT

  def test_blkid_unavailable_still_needs_format(self, monkeypatch):
    r = probe_with(monkeypatch, [self.BLANK_LSBLK], blkid=None)
    assert r.state == es.StorageState.NEEDS_FORMAT

  def test_blkid_parses_export_format(self, monkeypatch):
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (0, "DEVNAME=/dev/sdg1\nLABEL=openpilot\nTYPE=ext4"))
    assert es._blkid_fs("/dev/sdg1") == ("ext4", "openpilot")

  def test_blkid_failure_returns_empty(self, monkeypatch):
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (2, ""))
    assert es._blkid_fs("/dev/sdg1") == ("", "")


class TestTruthy:
  """lsblk -J emits rm/hotplug as real bools on new util-linux, "0"/"1" strings on old."""

  def test_string_zero_is_false(self):
    # bool("0") is True in Python -- the whole reason this helper exists
    assert not es._truthy("0")

  def test_string_one_is_true(self):
    assert es._truthy("1")

  def test_bools_pass_through(self):
    assert es._truthy(True)
    assert not es._truthy(False)

  def test_none_is_false(self):
    assert not es._truthy(None)

  def test_string_rm_zero_disk_not_selected_without_usb(self):
    # old lsblk reporting rm="0" must not make an internal disk look removable
    node = {"path": "/dev/mmcblk0", "type": "disk", "rm": "0", "tran": "mmc"}
    assert not es._is_safe_disk(node)

  def test_string_rm_one_disk_selected(self):
    assert es._is_safe_disk({"path": "/dev/sdg", "type": "disk", "rm": "1", "tran": None})


class TestHelpers:
  def test_human_readable_sizes(self):
    assert es._human(0) == "0B"
    assert es._human(512) == "512B"
    assert es._human(2048) == "2K"
    assert es._human(5 * 1024 ** 3) == "5.0G"

  def test_partition_of_sd_fallback(self, monkeypatch):
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (1, ""))
    assert es._partition_of("/dev/sdg") == "/dev/sdg1"

  def test_partition_of_nvme_fallback(self, monkeypatch):
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (1, ""))
    assert es._partition_of("/dev/nvme0n1") == "/dev/nvme0n1p1"

  def test_partition_of_prefers_lsblk(self, monkeypatch):
    out = lsblk([{"path": "/dev/sdg", "type": "disk",
                  "children": [{"path": "/dev/sdg1", "type": "part"}]}])
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: (0, out))
    assert es._partition_of("/dev/sdg") == "/dev/sdg1"

  def test_fstab_uses_label_not_device_node(self):
    # kernel names are not stable across boots; the label is what mkfs writes
    assert "LABEL=openpilot" in es.FSTAB_LINE
    assert "/dev/sd" not in es.FSTAB_LINE
    assert "nofail" in es.FSTAB_LINE

  def test_mount_point_matches_deleter_offload_target(self):
    from openpilot.system.hardware.hw import Paths
    assert es.MOUNT_POINT == Paths.log_root_external().rstrip("/")


class TestFormatGuard:
  def test_format_refuses_when_no_safe_disk(self, monkeypatch):
    """The destructive path re-probes and bails rather than trusting cached UI state."""
    ctl = es.ExternalStorageControl.__new__(es.ExternalStorageControl)
    calls = []
    monkeypatch.setattr(es, "_probe", lambda: es.ProbeResult())
    monkeypatch.setattr(es, "_run", lambda cmd, timeout: calls.append(cmd) or (0, ""))
    ctl._format_worker()
    assert calls == [], "no shell command may run when no safe external disk is found"
