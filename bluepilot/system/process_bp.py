"""BluePilot additions to manager's process types (no edits to sunnypilot's process.py)."""
from openpilot.common.swaglog import cloudlog
from openpilot.system.manager.process import PythonProcess


class RestartOnExitPythonProcess(PythonProcess):
  """A PythonProcess that manager restarts if it exits while it should still be running.

  Stock start() returns early whenever self.proc is set, even when that process is dead, so a
  process that exits stays down until its gate goes false and true again. ensure_running()
  calls start() on every process that should run, each loop, so reaping a dead one here is
  enough. Used by cangpsd, which exits deliberately when its GPS-source arbiter switches, as the
  way it releases (or guarantees it does not hold) the GPS publisher before the other source
  takes over.
  """
  def start(self) -> None:
    if self.proc is not None and self.proc.exitcode is not None:
      cloudlog.warning(f"restarting {self.name} (exited with {self.proc.exitcode})")
      self.stop()  # reaps: an exited process is not signalled, self.proc is cleared
    super().start()
