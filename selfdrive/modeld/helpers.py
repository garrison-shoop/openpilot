import json
from pathlib import Path

from openpilot.system.hardware.usb import CHESTNUT_FW_VERSION, CHESTNUT_USB_IDS, USB_DEVICES_PATH

MODELS_DIR = Path(__file__).resolve().parent / 'models'
TG_INPUT_DEVICES_PATH = MODELS_DIR / 'tg_input_devices.json'


def get_tg_input_devices(process_name: str, usbgpu: bool):
  with open(TG_INPUT_DEVICES_PATH) as f:
    return json.load(f)[process_name]['default' if not usbgpu else 'usbgpu']

def modeld_pkl_path(usbgpu: bool):
  prefix = 'big_' if usbgpu else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def usbgpu_present() -> bool:
  # Only a chestnut running our own firmware is usable; hardwared flashes any that mismatch.
  for d in USB_DEVICES_PATH.glob("*"):
    try:
      usb_id = (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16))
      product = (d / "product").read_text().strip()
      if usb_id in CHESTNUT_USB_IDS and product == f"custom {CHESTNUT_FW_VERSION}-CLEAN":
        return True
    except Exception:
      pass
  return False
