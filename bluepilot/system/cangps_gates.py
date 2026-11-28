"""Manager gates for CAN GPS (cangpsd), kept out of sunnypilot's process_config.

process_config's BluePilot block registers cangpsd with `cangpsd()` below, and wraps the device GPS
daemons' gates with `yield_to_cangpsd()` so they stand down while cangpsd owns the GPS topic (msgq
allows only one publisher per topic). Logic ported from cgrin/bluepilot@can-gps-time (0a12fea2c1),
where it lived inline in process_config and edited the stock ublox()/qcomgps() gates.
"""
import functools
from collections.abc import Callable

import openpilot.cereal.messaging as messaging
from opendbc.car.structs import car
from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.bluepilot.system.cangps_fallback import can_gps_selected, vehicle_key

Gate = Callable[[bool, Params, car.CarParams], bool]


@functools.cache
def prev_route_car() -> tuple[str, str]:
  """The (brand, vehicle key) recorded on the previous drive, or ("", "") if there isn't one.

  manager evaluates process gates against the live `carParams` message, which card only
  publishes once it has fingerprinted the car -- about six seconds into a boot. Any gate
  that keys off the brand is therefore wrong for those six seconds, which is long enough
  for ubloxd/pigeond to start, claim gpsLocationExternal, and be killed again.
  CarParamsPersistent is written by card on every drive and survives reboots, so on any
  boot after the first in a given car it supplies the brand immediately.

  Cached for the life of the process: card is the only writer, and by the time it has run
  the live CP is available and takes precedence below anyway.
  """
  cp_bytes = Params().get("CarParamsPersistent")
  if cp_bytes is None:
    return "", ""
  try:
    CP = messaging.log_from_bytes(cp_bytes, car.CarParams)
  except Exception:
    cloudlog.exception("cangps_gates: failed to deserialize CarParamsPersistent")
    return "", ""
  return CP.brand, vehicle_key(CP)


def _car_identity(CP: car.CarParams) -> tuple[str, str]:
  # Prefer the live CP; fall back to the last drive's only while card is still
  # fingerprinting, so ubloxd never gets a head start on the topic cangpsd is about to own.
  prev_brand, prev_key = prev_route_car()
  return (CP.brand or prev_brand), (vehicle_key(CP) or prev_key)


def can_gps_capable(started: bool, params: Params, CP: car.CarParams) -> bool:
  """Could CAN GPS work here at all? Ford is the only brand whose DBC carries a fix.

  Not gated on ublox_available(): cangpsd resolves its topic through get_gps_location_service(),
  the same call the consumers make, so it is useful with either device GPS daemon; whichever
  one owns that topic yields via yield_to_cangpsd().
  """
  brand, _ = _car_identity(CP)
  return started and brand == "ford"


def cangpsd(started: bool, params: Params, CP: car.CarParams) -> bool:
  """Run the daemon -- as the publisher when it is the selected source, else as an observer.

  Two independent flags, so the automatic path can be trialled without disturbing anyone
  relying on the manual one. FordPrefUseVehicleGps forces CAN GPS on; FordPrefAutoVehicleGps
  hands the choice to cangps_fallback, which needs the daemon running even while the device
  receiver still owns the topic, so it has something to compare against.
  """
  if not can_gps_capable(started, params, CP):
    return False
  return params.get_bool("FordPrefUseVehicleGps") or params.get_bool("FordPrefAutoVehicleGps")


def can_gps_publishing(started: bool, params: Params, CP: car.CarParams) -> bool:
  """Does cangpsd own the GPS topic right now? If so the device GPS daemon stands down.

  Observer mode deliberately does not reach this -- an observer publishes nothing, so nothing
  has to yield to it.
  """
  if not can_gps_capable(started, params, CP):
    return False
  if params.get_bool("FordPrefUseVehicleGps"):
    return True
  if not params.get_bool("FordPrefAutoVehicleGps"):
    return False
  _, key = _car_identity(CP)
  return can_gps_selected(params, key)


def yield_to_cangpsd(gate: Gate) -> Gate:
  """Wrap a device GPS daemon's stock gate (ubloxd/pigeond/qcomgpsd) so it stands down while
  cangpsd publishes. The stock gate still runs first, so its side effects (ublox() keeping the
  UbloxAvailable param in sync with the hardware, which GPS routing reads) are unchanged."""
  @functools.wraps(gate)
  def wrapped(started: bool, params: Params, CP: car.CarParams) -> bool:
    return gate(started, params, CP) and not can_gps_publishing(started, params, CP)
  return wrapped
