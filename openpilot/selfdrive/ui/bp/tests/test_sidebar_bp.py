"""The 3X sidebar's chestnut status icon (no window: textures stubbed, child widgets and drawing mocked)."""
import math
import unittest
from unittest import mock

import pyray as rl

from openpilot.common.test import OpenpilotTestCase
from openpilot.system.ui.lib.application import gui_app

RECT = rl.Rectangle(0, 0, 460, 1080)  # BPConstants.SIDEBAR_WIDTH x the 3X height
CHILDREN = ("_network_card", "_cpu_card", "_gpu_card", "_memory_card", "_vehicle_card", "_connect_card", "_sunnylink_card",
            "_fan_widget", "_settings_btn", "_flag_btn", "_info_btn", "_debug_btn")


class TestSidebarChestnut(OpenpilotTestCase):
  def setUp(self):
    from openpilot.selfdrive.ui.ui_state import ui_state  # inside the test's params prefix: building it writes params
    self.ui_state = ui_state
    self.textures: dict[str, rl.Texture] = {}

    def texture(path, width=0, height=0, *args, **kwargs):
      return self.textures.setdefault(path, rl.Texture(0, width, height, 1, 7))

    for patch in (mock.patch.object(gui_app, "texture", side_effect=texture),
                  mock.patch.object(gui_app, "font", return_value=rl.Font())):
      patch.start()
      self.addCleanup(patch.stop)

  def _frame(self, state, started=False, time=0.0, egpu_link=None):
    """One sidebar frame; returns (chestnut draws as (icon path, position, scale, alpha), each child's render rect)."""
    from bluepilot.ui.widgets.sidebar import SidebarBP
    sidebar = SidebarBP()
    for name in CHILDREN:
      setattr(sidebar, name, mock.Mock())
    sidebar._egpu_link = egpu_link
    with (mock.patch.object(self.ui_state, "chestnut_state", state), mock.patch.object(self.ui_state, "started", started),
          mock.patch.object(rl, "get_time", return_value=time), mock.patch.object(rl, "draw_rectangle_rec"),
          mock.patch.object(rl, "draw_line"), mock.patch.object(rl, "draw_texture_ex") as draw):
      sidebar._render(RECT)
    paths = {id(tex): path for path, tex in self.textures.items() if "chestnut" in path}
    chestnut = [(paths[id(c.args[0])], c.args[1], c.args[3], c.args[4].a) for c in draw.call_args_list if id(c.args[0]) in paths]
    rects = {name: tuple((r.x, r.y, r.width, r.height) for (r,), _ in getattr(sidebar, name).render.call_args_list) for name in CHILDREN}
    return chestnut, rects

  def test_icon_for_each_connected_state(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for state, icon in ((ChestnutState.READY, "icons_mici/chestnut_green.png"), (ChestnutState.ACTIVE, "icons_mici/chestnut_green.png"),
                        (ChestnutState.UNCOMPILED, "icons_mici/chestnut_orange.png"), (ChestnutState.FAILED, "icons_mici/chestnut_orange.png"),
                        (ChestnutState.LOADING, "icons_mici/chestnut.png")):
      with self.subTest(state=state):
        (drawn,), _ = self._frame(state, time=math.pi / 6)  # LOADING pulses: full opacity at this time
        self.assertEqual((drawn[0], drawn[3]), (icon, 255))

  def test_loading_pulses(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    (drawn,), _ = self._frame(ChestnutState.LOADING, time=0.0)
    self.assertEqual(drawn[3], int(255 * 0.35))  # sunnypilot's dimmest point of the pulse

  def test_icon_sits_in_the_button_column_above_the_buttons(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for started, slot_y in ((False, 715), (True, 475)):  # next 100 px slot above info (offroad) or debug (onroad)
      with self.subTest(started=started):
        ((_, pos, scale, _),), _ = self._frame(ChestnutState.READY, started=started)
        width, height = 180 * scale, 133 * scale  # sunnypilot loads it at 180 x 133
        self.assertLessEqual(width, 100)
        self.assertAlmostEqual(pos.x + width / 2, 335 + 50, places=3)  # button column: x 335, 100 px wide
        self.assertAlmostEqual(pos.y + height / 2, slot_y + 50, places=3)  # rl.Vector2 is float32

  def test_no_icon_without_a_chestnut(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for started in (False, True):
      with self.subTest(started=started):
        chestnut, _ = self._frame(ChestnutState.DISCONNECTED, started=started)
        self.assertEqual(chestnut, [])

  def test_chestnut_moves_nothing_else(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for started in (False, True):
      with self.subTest(started=started):
        self.assertEqual(self._frame(ChestnutState.READY, started=started)[1], self._frame(ChestnutState.DISCONNECTED, started=started)[1])

  def test_icon_dims_when_no_gpu_is_linked(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    from bluepilot.ui.widgets.sidebar import EGPU_DIM_OPACITY
    (drawn,), _ = self._frame(ChestnutState.READY, egpu_link=False)
    self.assertEqual(drawn[3], int(255 * EGPU_DIM_OPACITY))

  def test_icon_not_dimmed_when_linked_unknown_or_failed(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for state, link in ((ChestnutState.READY, True), (ChestnutState.READY, None), (ChestnutState.FAILED, False)):
      with self.subTest(state=state, link=link):
        (drawn,), _ = self._frame(state, egpu_link=link)
        self.assertEqual(drawn[3], 255)


class _FakeSM:
  def __init__(self, state=None, alive=True, valid=True):
    self._state, self.alive, self.valid = state, {'chestnutState': alive}, {'chestnutState': valid}

  def update(self, timeout=0):
    pass

  def __getitem__(self, name):
    return self._state


class TestSidebarEgpuCard(OpenpilotTestCase):
  """The GPU card shows the eGPU from upstream's chestnutState while a dock is connected."""
  def setUp(self):
    from openpilot.selfdrive.ui.ui_state import ui_state
    self.ui_state = ui_state
    for patch in (mock.patch.object(gui_app, "texture", return_value=rl.Texture(0, 1, 1, 1, 7)),
                  mock.patch.object(gui_app, "font", return_value=rl.Font())):
      patch.start()
      self.addCleanup(patch.stop)

  def _sidebar(self, sm):
    from bluepilot.ui.widgets.sidebar import SidebarBP
    sidebar = SidebarBP()
    for name in CHILDREN:
      setattr(sidebar, name, mock.Mock())
    sidebar._egpu_sm = sm
    sidebar._update_egpu_metrics()
    return sidebar

  def _card(self, sidebar, state):
    with mock.patch.object(self.ui_state, "chestnut_state", state):
      sidebar._update_metric_cards()
    return sidebar._gpu_card.set_data.call_args.args[0]

  @staticmethod
  def _state(ltssm=0x78, temp=0.0, usage=0):
    return mock.Mock(pcieLtssm=ltssm, tempC=temp, gpuUsagePercent=usage)

  def test_running_gpu_reports_usage_and_hotspot_bands(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    from bluepilot.ui.lib.colors import BPColors
    for temp, color in ((85.0, BPColors.GOOD), (95.0, BPColors.WARNING), (105.0, BPColors.DANGER)):
      with self.subTest(temp=temp):
        sidebar = self._sidebar(_FakeSM(self._state(temp=temp, usage=40)))
        self.assertIs(sidebar._egpu_link, True)
        card = self._card(sidebar, ChestnutState.ACTIVE)
        self.assertEqual((card.label, card.left_value, card.right_value, card.color), ("EGPU", "40%", f"{temp:.1f}\u00b0C", color))

  def test_seated_gpu_without_the_big_model_reads_na(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    from bluepilot.ui.lib.colors import BPColors
    sidebar = self._sidebar(_FakeSM(self._state(temp=0.0)))  # no chestnutGpuState merged in: GPU fields are zero
    self.assertIs(sidebar._egpu_link, True)
    card = self._card(sidebar, ChestnutState.READY)
    self.assertEqual((card.left_value, card.right_value, card.color), ("N/A", "N/A", BPColors.DISABLED))

  def test_empty_dock_reads_no_gpu(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    sidebar = self._sidebar(_FakeSM(self._state(ltssm=0x11)))
    self.assertIs(sidebar._egpu_link, False)
    self.assertEqual(self._card(sidebar, ChestnutState.READY).right_value, "NO GPU")

  def test_no_telemetry_is_unknown_not_no_gpu(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    for sm in (_FakeSM(alive=False), _FakeSM(self._state(), valid=False)):
      with self.subTest(alive=sm.alive, valid=sm.valid):
        sidebar = self._sidebar(sm)
        self.assertIsNone(sidebar._egpu_link)
        self.assertNotEqual(self._card(sidebar, ChestnutState.UNCOMPILED).right_value, "NO GPU")

  def test_integrated_gpu_card_without_a_dock(self):
    from openpilot.selfdrive.ui.ui_state import ChestnutState
    sidebar = self._sidebar(_FakeSM(self._state(temp=85.0, usage=40)))
    self.assertEqual(self._card(sidebar, ChestnutState.DISCONNECTED).label, "GPU")

  def test_subscriber_errors_degrade_to_unknown(self):
    sm = _FakeSM(self._state(temp=85.0))
    sm.update = mock.Mock(side_effect=RuntimeError("boom"))
    sidebar = self._sidebar(sm)
    self.assertIsNone(sidebar._egpu_link)
    self.assertEqual((sidebar._egpu_usage, sidebar._egpu_temp), ("N/A", "N/A"))


if __name__ == "__main__":
  unittest.main()
