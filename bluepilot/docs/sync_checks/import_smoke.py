"""Runtime: import modules for real, stubbing only Params (here) and msgq (stubs/ dir).
Usage (from repo root): PYTHONPATH=.:opendbc_repo:bluepilot/docs/sync_checks/stubs \
  uv run --no-project --python 3.12.12 --with <deps> -- python bluepilot/docs/sync_checks/import_smoke.py <modules...>
See SYNCING.md 6 for the module list and deps."""
import sys, types, importlib, traceback
m = types.ModuleType("openpilot.common.params")
class UnknownKeyName(Exception): pass
class ParamKeyType:
  BOOL=STRING=INT=FLOAT=TIME=JSON=BYTES=0
class ParamKeyFlag:
  PERSISTENT=CLEAR_ON_MANAGER_START=CLEAR_ON_ONROAD_TRANSITION=CLEAR_ON_OFFROAD_TRANSITION=DONT_LOG=DEVELOPMENT_ONLY=CLEAR_ON_IGNITION_ON=ALL=BACKUP=0
class Params:
  _d = {}
  def __init__(self, *a, **k): pass
  def __getattr__(self, n): return lambda *a, **k: None
  def get(self, k, *a, **kw): return self._d.get(k)
  def get_bool(self, k, *a, **kw): return bool(self._d.get(k))
  def put(self, k, v, *a, **kw): self._d[k] = v
  def check_key(self, k): return True
  def all_keys(self, *a): return []
m.Params, m.UnknownKeyName, m.ParamKeyType, m.ParamKeyFlag = Params, UnknownKeyName, ParamKeyType, ParamKeyFlag
sys.modules["openpilot.common.params"] = m
fail = 0
for mod in sys.argv[1:]:
  try:
    importlib.import_module(mod); print(f"OK    {mod}")
  except Exception as e:
    fail += 1; tb = traceback.extract_tb(e.__traceback__)[-1]
    print(f"FAIL  {mod}\n      {type(e).__name__}: {e}\n      at {tb.filename.split('/bp-')[-1]}:{tb.lineno}")
sys.exit(1 if fail else 0)
