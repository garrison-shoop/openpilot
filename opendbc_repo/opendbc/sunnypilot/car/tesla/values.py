"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from enum import IntFlag


class TeslaFlagsSP(IntFlag):
  HAS_VEHICLE_BUS = 1  # 3-finger infotainment press signal is present on the VEHICLE bus with the deprecated Tesla harness installed
  COOP_STEERING = 2  # Coop steering


# Backported from the opendbc revision upstream pins (3b8f263). The synced UI imports this
# (selfdrive/ui/sunnypilot/layouts/settings/steering_sub_layouts/mads_settings.py) but the vendored
# opendbc predates it, so the whole UI failed to import.
class MadsScreenButtonType:
  OFF = 0
  THREE_FINGER = 1
  FOUR_FINGER = 2
  FIVE_FINGER = 3


class TeslaSafetyFlagsSP:
  HAS_VEHICLE_BUS = 1
