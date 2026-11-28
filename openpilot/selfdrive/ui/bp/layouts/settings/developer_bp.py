"""BluePilot developer panel: sunnypilot's developer panel plus the external storage control.

Subclasses DeveloperLayoutSP instead of editing it. DeveloperLayoutSP.__init__ calls
_initialize_items() and then adds every entry of self.items to its scroller, so appending here
is enough. Wired in by the BluePilot block in sunnypilot/layouts/settings/settings.py.
"""
from openpilot.selfdrive.ui.sunnypilot.layouts.settings.developer import DeveloperLayoutSP
from openpilot.selfdrive.ui.bp.widgets.external_storage import ExternalStorageControl


class DeveloperLayoutBP(DeveloperLayoutSP):
  def _initialize_items(self):
    super()._initialize_items()
    self.external_storage = ExternalStorageControl()
    self.items.append(self.external_storage.item)

  def show_event(self):
    super().show_event()
    # probe the drive on open so the panel doesn't show a stale value
    self.external_storage.refresh_now()

  def _update_state(self):
    # cheap: only compares a timestamp; the probe/format/mount work runs on a worker thread
    self.external_storage.poll()
    super()._update_state()
