"""BluePilot detection. Safe to import on any fork — returns False when not BluePilot."""
import os
from functools import cache

from openpilot.common.basedir import BASEDIR

@cache
def is_bluepilot() -> bool:
  # BPVERSION is at the repo root. This was dirname(__file__)/.. while this file was
  # common/bluepilot.py; under openpilot/common/ that resolves to openpilot/ instead.
  return os.path.isfile(os.path.join(BASEDIR, 'BPVERSION'))
