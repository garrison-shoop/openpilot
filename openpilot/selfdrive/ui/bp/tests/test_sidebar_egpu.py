"""Sidebar eGPU card: chestnutState formatting, validity handling, and hotspot colour bands.

The card replaces the integrated GPU card whenever a chestnut is attached. modeld only publishes
chestnutState once the big model is actually running, so 'attached but not reporting' has to read
as N/A rather than as zeroed metrics.
"""
from types import SimpleNamespace

import pytest

from bluepilot.ui.lib.colors import BPColors
from bluepilot.ui.widgets.sidebar import SidebarBP


def make_sidebar(monkeypatch, *, alive=True, valid=True, usage=42.0, temp=78.5, raises=False):
  """A SidebarBP with only the attributes the eGPU helpers touch -- __init__ builds raylib widgets."""
  sidebar = SidebarBP.__new__(SidebarBP)
  sidebar._egpu_usage = "unset"
  sidebar._egpu_temp = "unset"
  sidebar._egpu_reporting = False

  class _SM:
    def __init__(self):
      self.alive = {'chestnutState': alive}
      self.valid = {'chestnutState': valid}

    def __getitem__(self, key):
      if raises:
        raise RuntimeError("capnp read failed")
      return SimpleNamespace(gpuUsagePercent=usage, tempC=temp)

  import bluepilot.ui.widgets.sidebar as sb
  monkeypatch.setattr(sb, "ui_state", SimpleNamespace(sm=_SM(), usbgpu=True))
  return sidebar


class TestEgpuMetrics:
  def test_reports_usage_and_hotspot_temp(self, monkeypatch):
    s = make_sidebar(monkeypatch, usage=42.0, temp=78.5)
    s._update_egpu_metrics()
    assert s._egpu_usage == "42%"
    assert s._egpu_temp == "78.5°C"
    assert s._egpu_reporting

  def test_not_alive_reads_na(self, monkeypatch):
    # attached but big model not compiled -> modeld never publishes chestnutState
    s = make_sidebar(monkeypatch, alive=False)
    s._update_egpu_metrics()
    assert (s._egpu_usage, s._egpu_temp) == ("N/A", "N/A")
    assert not s._egpu_reporting

  def test_invalid_reads_na(self, monkeypatch):
    # msg.valid is false when the SMU read fails or the PCIe link is down
    s = make_sidebar(monkeypatch, valid=False)
    s._update_egpu_metrics()
    assert (s._egpu_usage, s._egpu_temp) == ("N/A", "N/A")
    assert not s._egpu_reporting

  def test_read_exception_degrades_to_na(self, monkeypatch):
    s = make_sidebar(monkeypatch, raises=True)
    s._update_egpu_metrics()
    assert (s._egpu_usage, s._egpu_temp) == ("N/A", "N/A")
    assert not s._egpu_reporting

  def test_zero_usage_is_not_confused_with_missing(self, monkeypatch):
    s = make_sidebar(monkeypatch, usage=0.0, temp=51.0)
    s._update_egpu_metrics()
    assert s._egpu_usage == "0%"
    assert s._egpu_reporting


class TestEgpuColour:
  @pytest.mark.parametrize(("temp", "expected"), [
    (51.0, BPColors.GOOD),      # idle
    (89.9, BPColors.GOOD),      # loaded but fine
    (90.1, BPColors.WARNING),
    (99.9, BPColors.WARNING),
    (100.1, BPColors.DANGER),
  ])
  def test_hotspot_bands(self, monkeypatch, temp, expected):
    s = make_sidebar(monkeypatch, temp=temp)
    s._update_egpu_metrics()
    assert s._egpu_color() == expected

  def test_not_reporting_is_disabled_colour(self, monkeypatch):
    s = make_sidebar(monkeypatch, alive=False)
    s._update_egpu_metrics()
    assert s._egpu_color() == BPColors.DISABLED

  def test_unparseable_temp_falls_back_to_good(self, monkeypatch):
    s = make_sidebar(monkeypatch)
    s._egpu_reporting = True
    s._egpu_temp = "N/A"
    assert s._egpu_color() == BPColors.GOOD
