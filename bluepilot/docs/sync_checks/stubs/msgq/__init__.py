class MultiplePublishersError(Exception): pass
class IpcError(Exception): pass
def __getattr__(name):
  if name.startswith("__"): raise AttributeError(name)
  return type(name, (), {"__init__": lambda self, *a, **k: None})
