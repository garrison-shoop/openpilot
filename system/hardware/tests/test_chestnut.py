"""Chestnut (external GPU) flash-decision logic and USB state mapping.

The flasher writes SPI firmware to an attached device, so the decision to run it matters more than
the flashing itself: it must only ever fire offroad, only for a chestnut whose firmware is actually
stale, and it must give up rather than retry forever.
"""
from openpilot.system.hardware.hardwared import Chestnut
from openpilot.system.hardware.usb import CHESTNUT_FW_VERSION, CHESTNUT_ROM_USB_IDS, CHESTNUT_USB_IDS

GOOD_PRODUCT = f"custom {CHESTNUT_FW_VERSION}-CLEAN"


def dev(vid, pid, product=GOOD_PRODUCT):
  return {"vendorId": vid, "productId": pid, "product": product}


CURRENT = dev(*CHESTNUT_USB_IDS[0])
STALE = dev(*CHESTNUT_USB_IDS[0], product="custom deadbeef-CLEAN")
IN_ROM = dev(*CHESTNUT_ROM_USB_IDS[0], product="USB 3.2 PCIe TinyEnclosure")
UNRELATED = dev(0x1D6B, 0x0002, product="xHCI Host Controller")


class FakeChestnut(Chestnut):
  """Records flash attempts instead of shelling out to the real flasher."""
  def __init__(self):
    super().__init__()
    self.flash_calls = 0

  def flash(self) -> None:
    self.flash_calls += 1
    self.flashed = True


def drive(chestnut, offroad, usb_state, ticks=1):
  for _ in range(ticks):
    chestnut.update(offroad, usb_state)
    if chestnut.thread is not None:
      chestnut.thread.join(timeout=5)


class TestFlashDecision:
  def test_no_device_never_flashes(self):
    c = FakeChestnut()
    drive(c, True, [UNRELATED])
    assert c.flash_calls == 0

  def test_empty_usb_state_never_flashes(self):
    c = FakeChestnut()
    drive(c, True, [])
    assert c.flash_calls == 0

  def test_current_firmware_never_flashes(self):
    c = FakeChestnut()
    drive(c, True, [CURRENT])
    assert c.flash_calls == 0

  def test_stale_firmware_flashes_offroad(self):
    c = FakeChestnut()
    drive(c, True, [STALE])
    assert c.flash_calls == 1

  def test_rom_bootloader_flashes_offroad(self):
    # a factory device enumerates under the ASMedia ROM ids and must still be recovered
    c = FakeChestnut()
    drive(c, True, [IN_ROM])
    assert c.flash_calls == 1

  def test_never_flashes_onroad(self):
    c = FakeChestnut()
    drive(c, False, [STALE], ticks=5)
    assert c.flash_calls == 0

  def test_flashes_once_until_state_changes(self):
    c = FakeChestnut()
    drive(c, True, [STALE], ticks=5)
    assert c.flash_calls == 1, "should not re-flash while the device still reports stale"

  def test_attempts_are_capped(self):
    c = FakeChestnut()
    for _ in range(Chestnut.MAX_ATTEMPTS + 3):
      c.flashed = False           # pretend each flash failed to take effect
      c.last_attempt = 0.         # and that the retry interval elapsed
      drive(c, True, [STALE])
    assert c.flash_calls == Chestnut.MAX_ATTEMPTS

  def test_retry_interval_is_respected(self):
    c = FakeChestnut()
    drive(c, True, [STALE])
    c.flashed = False  # flash "failed", but the interval has not elapsed
    drive(c, True, [STALE])
    assert c.flash_calls == 1

  def test_good_device_resets_flashed_latch(self):
    c = FakeChestnut()
    drive(c, True, [STALE])
    assert c.flashed
    drive(c, True, [CURRENT])
    assert not c.flashed, "latch must clear so a later hotplug can flash again"


class TestUsbIds:
  def test_rom_and_runtime_ids_are_disjoint(self):
    assert not set(CHESTNUT_USB_IDS) & set(CHESTNUT_ROM_USB_IDS)

  def test_known_chestnut_vendor_ids(self):
    # 0xADD1 is the original; 0x3801 is the later hardware revision
    assert (0xADD1, 0x0001) in CHESTNUT_USB_IDS
    assert (0x3801, 0x0001) in CHESTNUT_USB_IDS

  def test_rom_ids_are_asmedia(self):
    assert all(vid == 0x174C for vid, _ in CHESTNUT_ROM_USB_IDS)
