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


class TestFlatLsblkShape:
  """AGNOS's lsblk -J emits every node flat in blockdevices instead of nesting partitions under
  'children'. That made every disk look partitionless: a formatted drive read as 'needs format'
  forever, and a disk holding / and /data looked like it held no protected mountpoint at all.
  """

  # exactly the shape reported from the device
  FLAT = [
    {"path": "/dev/sdg", "pkname": None, "type": "disk", "rm": False, "tran": "usb", "size": 1024 ** 4},
    {"path": "/dev/sdg1", "pkname": "sdg", "type": "part", "rm": False, "tran": None,
     "fstype": "ext4", "label": "openpilot", "mountpoint": "/mnt/external_realdata"},
  ]

  def test_flat_partitions_are_reattached(self):
    disks = es._normalize_devices(self.FLAT)
    assert len(disks) == 1
    assert [c["path"] for c in disks[0]["children"]] == ["/dev/sdg1"]

  def test_flat_formatted_drive_reports_mounted_not_needs_format(self, monkeypatch):
    r = probe_with(monkeypatch, self.FLAT, ismount=True)
    assert r.state == es.StorageState.MOUNTED, "the reported bug: formatted drive stuck on NEEDS_FORMAT"
    assert r.partition == "/dev/sdg1"

  def test_flat_reattaches_without_pkname_via_path_prefix(self):
    flat = [dict(n, pkname=None) for n in self.FLAT]
    disks = es._normalize_devices(flat)
    assert [c["path"] for c in disks[0]["children"]] == ["/dev/sdg1"]

  def test_flat_protected_mounts_still_seen(self):
    # without reattaching, mmcblk0 would look like it holds nothing and become a format candidate
    flat = [
      {"path": "/dev/mmcblk0", "pkname": None, "type": "disk", "rm": "1", "tran": None},
      {"path": "/dev/mmcblk0p1", "pkname": "mmcblk0", "type": "part", "mountpoint": "/data"},
    ]
    disks = es._normalize_devices(flat)
    assert not es._is_safe_disk(disks[0]), "a disk holding /data must never be a format target"

  def test_nested_shape_still_works(self):
    nested = [{"path": "/dev/sdg", "type": "disk", "rm": False, "tran": "usb", "children": [
      {"path": "/dev/sdg1", "type": "part", "fstype": "ext4", "label": "openpilot"}]}]
    disks = es._normalize_devices(nested)
    assert [c["path"] for c in disks[0]["children"]] == ["/dev/sdg1"]

  def test_nested_children_not_duplicated(self):
    nested = [{"path": "/dev/sdg", "type": "disk", "rm": False, "tran": "usb", "children": [
      {"path": "/dev/sdg1", "pkname": "sdg", "type": "part", "fstype": "ext4", "label": "openpilot"}]}]
    disks = es._normalize_devices(nested)
    assert len(disks[0]["children"]) == 1

  def test_nvme_style_prefix_matching(self):
    flat = [
      {"path": "/dev/nvme0n1", "pkname": None, "type": "disk", "rm": True, "tran": "usb"},
      {"path": "/dev/nvme0n1p1", "pkname": None, "type": "part", "fstype": "ext4", "label": "openpilot"},
    ]
    disks = es._normalize_devices(flat)
    assert [c["path"] for c in disks[0]["children"]] == ["/dev/nvme0n1p1"]


def comma_3x_topology():
  """The real block layout off a comma 3X: internal UFS LUNs sda-sdf (sde alone has 48 partitions),
  zram, and a 1TB NVMe-in-USB-enclosure at sdg. Flat, as this lsblk emits it."""
  nodes = []
  for disk, nparts in (("sda", 12), ("sdb", 2), ("sdc", 2), ("sdd", 3), ("sde", 48), ("sdf", 5)):
    # internal: no transport, not removable
    nodes.append({"path": f"/dev/{disk}", "pkname": None, "type": "disk", "rm": False,
                  "tran": None, "size": 64 * 1024 ** 3})
    for i in range(1, nparts + 1):
      nodes.append({"path": f"/dev/{disk}{i}", "pkname": disk, "type": "part", "rm": False,
                    "tran": None, "fstype": "ext4" if i % 3 == 0 else None, "label": None})
  nodes.append({"path": "/dev/sdg", "pkname": None, "type": "disk", "rm": False, "tran": "usb",
                "size": 1024 ** 4})
  nodes.append({"path": "/dev/sdg1", "pkname": "sdg", "type": "part", "rm": False, "tran": None,
                "fstype": "ext4", "label": "openpilot", "mountpoint": "/mnt/external_realdata"})
  nodes.append({"path": "/dev/zram0", "pkname": None, "type": "disk", "rm": False, "tran": None,
                "size": 2 * 1024 ** 3})
  return nodes


class TestRealCommaTopology:
  def test_only_the_usb_drive_is_a_candidate(self):
    disks = es._normalize_devices(comma_3x_topology())
    safe = [d["path"] for d in disks if es._is_safe_disk(d)]
    assert safe == ["/dev/sdg"], "internal UFS LUNs must never be format candidates"

  def test_picks_the_usb_drive(self):
    assert es._pick_disk(es._normalize_devices(comma_3x_topology()))["path"] == "/dev/sdg"

  def test_formatted_drive_reports_mounted(self, monkeypatch):
    r = probe_with(monkeypatch, comma_3x_topology(), ismount=True)
    assert r.state == es.StorageState.MOUNTED
    assert r.disk == "/dev/sdg"
    assert r.partition == "/dev/sdg1"

  def test_partitions_attach_to_the_right_disks(self):
    disks = {d["path"]: d for d in es._normalize_devices(comma_3x_topology())}
    assert len(disks["/dev/sde"]["children"]) == 48
    assert len(disks["/dev/sdg"]["children"]) == 1
    # sdg1 must not be swept up by a shorter prefix match
    assert disks["/dev/sdg"]["children"][0]["path"] == "/dev/sdg1"


class TestDiskSelection:
  """A comma exposes many block devices. Selection must be deterministic and must not let an
  unrelated disk shadow the real drive -- the chosen disk is what FORMAT runs wipefs against."""

  # USB-to-NVMe enclosure: rm is false because the NVMe inside is not removable media
  NVME_ENCLOSURE = {"path": "/dev/sdg", "type": "disk", "rm": False, "tran": "usb",
                    "size": 1024 ** 4, "children": [
                      {"path": "/dev/sdg1", "type": "part", "fstype": "ext4", "label": "openpilot",
                       "mountpoint": "/mnt/external_realdata"}]}
  EMMC_BOOT0 = {"path": "/dev/mmcblk0boot0", "type": "disk", "rm": "0", "tran": None, "size": 4 * 1024 ** 2}
  EMMC_BOOT1 = {"path": "/dev/mmcblk0boot1", "type": "disk", "rm": "0", "tran": None, "size": 4 * 1024 ** 2}
  EMMC_RPMB = {"path": "/dev/mmcblk0rpmb", "type": "disk", "rm": "0", "tran": None, "size": 4 * 1024 ** 2}
  LOOP0 = {"path": "/dev/loop0", "type": "disk", "rm": "0", "tran": None, "size": 1024 ** 2}

  def test_usb_nvme_enclosure_is_detected_despite_rm_false(self):
    assert es._is_safe_disk(self.NVME_ENCLOSURE)

  def test_emmc_boot_and_rpmb_never_targeted(self):
    for node in (self.EMMC_BOOT0, self.EMMC_BOOT1, self.EMMC_RPMB):
      assert not es._is_safe_disk(node), f"{node['path']} must never be a format target"

  def test_loop_devices_never_targeted(self):
    assert not es._is_safe_disk(self.LOOP0)

  def test_real_drive_wins_over_clutter(self):
    # emmc/loop nodes enumerate before sdg; the real drive must still be chosen
    devices = [self.EMMC_BOOT0, self.EMMC_BOOT1, self.EMMC_RPMB, self.LOOP0, self.NVME_ENCLOSURE]
    assert es._pick_disk(devices)["path"] == "/dev/sdg"

  def test_labelled_disk_preferred_over_blank_usb_disk(self):
    blank = {"path": "/dev/sda", "type": "disk", "rm": True, "tran": "usb", "size": 8 * 1024 ** 3}
    assert es._pick_disk([blank, self.NVME_ENCLOSURE])["path"] == "/dev/sdg"

  def test_usb_preferred_over_removable_non_usb(self):
    other = {"path": "/dev/sdb", "type": "disk", "rm": True, "tran": "sata", "size": 2 * 1024 ** 4}
    usb = {"path": "/dev/sdg", "type": "disk", "rm": False, "tran": "usb", "size": 8 * 1024 ** 3}
    assert es._pick_disk([other, usb])["path"] == "/dev/sdg"

  def test_selection_is_stable_across_ordering(self):
    devices = [self.EMMC_BOOT0, self.NVME_ENCLOSURE, self.LOOP0]
    assert es._pick_disk(devices)["path"] == es._pick_disk(list(reversed(devices)))["path"]

  def test_no_candidates_returns_none(self):
    assert es._pick_disk([self.EMMC_BOOT0, self.LOOP0]) is None

  def test_end_to_end_mounted_nvme_enclosure(self, monkeypatch):
    # the reported hardware: 1TB NVMe in a USB enclosure, formatted and mounted
    devices = [self.EMMC_BOOT0, self.EMMC_RPMB, self.LOOP0, self.NVME_ENCLOSURE]
    r = probe_with(monkeypatch, devices, ismount=True)
    assert r.state == es.StorageState.MOUNTED
    assert r.disk == "/dev/sdg"
    assert r.partition == "/dev/sdg1"


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
