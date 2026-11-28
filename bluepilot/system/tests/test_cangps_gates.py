"""CAN GPS manager wiring: the gates in cangps_gates, the device-GPS yield wrappers that
process_config's BluePilot block applies, and the restart-on-exit process type."""
import unittest
from unittest import mock

from openpilot.bluepilot.system import cangps_gates as gates
from openpilot.bluepilot.system.process_bp import RestartOnExitPythonProcess


class FakeParams:
  def __init__(self, **flags):
    self._flags = flags

  def get_bool(self, key, *args, **kwargs):
    return bool(self._flags.get(key, False))


def ford(**kw):
  return mock.Mock(brand="ford", carVin=kw.get("vin", "1FTVIN"), carFingerprint="FORD_F_150_MK14")


def other():
  return mock.Mock(brand="toyota", carVin="JTVIN", carFingerprint="TOYOTA_RAV4")


def no_car():
  return mock.Mock(brand="", carVin="", carFingerprint="")


class TestGates(unittest.TestCase):
  def setUp(self):
    patch = mock.patch.object(gates, "prev_route_car", return_value=("", ""))
    patch.start()
    self.addCleanup(patch.stop)

  def test_cangpsd_runs_only_on_ford_onroad_with_a_flag(self):
    for started, CP, flags, expected in (
      (True, ford(), {"FordPrefUseVehicleGps": True}, True),
      (True, ford(), {"FordPrefAutoVehicleGps": True}, True),
      (True, ford(), {}, False),
      (False, ford(), {"FordPrefUseVehicleGps": True}, False),
      (True, other(), {"FordPrefUseVehicleGps": True}, False),
    ):
      with self.subTest(started=started, brand=CP.brand, flags=flags):
        self.assertIs(gates.cangpsd(started, FakeParams(**flags), CP), expected)

  def test_publishing_manual_auto_and_observer(self):
    with mock.patch.object(gates, "can_gps_selected", return_value=False):
      self.assertTrue(gates.can_gps_publishing(True, FakeParams(FordPrefUseVehicleGps=True), ford()))
      self.assertFalse(gates.can_gps_publishing(True, FakeParams(FordPrefAutoVehicleGps=True), ford()))  # observer
      self.assertFalse(gates.can_gps_publishing(True, FakeParams(), ford()))
    with mock.patch.object(gates, "can_gps_selected", return_value=True) as selected:
      self.assertTrue(gates.can_gps_publishing(True, FakeParams(FordPrefAutoVehicleGps=True), ford(vin="VIN9")))
      selected.assert_called_with(mock.ANY, "VIN9")

  def test_previous_drive_supplies_the_brand_while_fingerprinting(self):
    with mock.patch.object(gates, "prev_route_car", return_value=("ford", "VINPREV")):
      self.assertTrue(gates.can_gps_publishing(True, FakeParams(FordPrefUseVehicleGps=True), no_car()))
    self.assertFalse(gates.can_gps_publishing(True, FakeParams(FordPrefUseVehicleGps=True), no_car()))


class TestYieldToCangpsd(unittest.TestCase):
  def setUp(self):
    patch = mock.patch.object(gates, "prev_route_car", return_value=("", ""))
    patch.start()
    self.addCleanup(patch.stop)

  def test_device_gps_stands_down_only_while_cangpsd_publishes(self):
    stock = mock.Mock(return_value=True)
    gate = gates.yield_to_cangpsd(stock)
    self.assertFalse(gate(True, FakeParams(FordPrefUseVehicleGps=True), ford()))
    self.assertTrue(gate(True, FakeParams(), ford()))
    self.assertTrue(gate(True, FakeParams(FordPrefUseVehicleGps=True), other()))

  def test_stock_gate_still_runs_and_still_wins_when_false(self):
    stock = mock.Mock(return_value=False)
    gate = gates.yield_to_cangpsd(stock)
    self.assertFalse(gate(True, FakeParams(), ford()))
    stock.assert_called_once()  # ublox() keeps UbloxAvailable in sync as a side effect


class TestRestartOnExit(unittest.TestCase):
  def _proc(self, exitcode):
    p = RestartOnExitPythonProcess("cangpsd", "bluepilot.system.cangpsd", lambda *a: True)
    p.proc = mock.Mock(exitcode=exitcode) if exitcode != "none" else None
    return p

  def test_exited_process_is_reaped_and_started_again(self):
    p = self._proc(0)
    with mock.patch("openpilot.system.manager.process.PythonProcess.start") as start, \
         mock.patch.object(RestartOnExitPythonProcess, "stop", autospec=True) as stop:
      p.start()
    stop.assert_called_once_with(p)
    start.assert_called_once()

  def test_running_or_unstarted_process_is_left_to_stock_start(self):
    for exitcode in (None, "none"):
      with self.subTest(exitcode=exitcode):
        p = self._proc(exitcode)
        with mock.patch("openpilot.system.manager.process.PythonProcess.start") as start, \
             mock.patch.object(RestartOnExitPythonProcess, "stop", autospec=True) as stop:
          p.start()
        stop.assert_not_called()
        start.assert_called_once()


class TestProcessConfigWiring(unittest.TestCase):
  def test_cangpsd_registered_and_device_gps_wrapped(self):
    from openpilot.system.manager import process_config as pc
    procs = pc.managed_processes
    self.assertIsInstance(procs["cangpsd"], RestartOnExitPythonProcess)
    self.assertIs(procs["cangpsd"].should_run, gates.cangpsd)
    for name, stock in (("ubloxd", pc.ublox), ("pigeond", pc.ublox), ("qcomgpsd", pc.qcomgps)):
      with self.subTest(name=name):
        self.assertIs(procs[name].should_run.__wrapped__, stock)


if __name__ == "__main__":
  unittest.main()
