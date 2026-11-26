"""Static: every ui_state.<attr> used by BluePilot UI code exists on UIState/UIStateSP.
Usage: python3 ui_state_check.py <repo root>. See SYNCING.md 6."""
import ast, os, re, sys
root = sys.argv[1]
attrs = set()
for rel in ("openpilot/selfdrive/ui/ui_state.py", "openpilot/selfdrive/ui/sunnypilot/ui_state.py"):
  t = ast.parse(open(os.path.join(root, rel)).read())
  for c in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
    for n in ast.walk(c):
      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)): attrs.add(n.name)
      if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and isinstance(n.ctx, ast.Store): attrs.add(n.attr)
      if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Attribute): attrs.add(n.target.attr)
    for n in c.body:
      if isinstance(n, ast.Assign):
        for tg in n.targets:
          if isinstance(tg, ast.Name): attrs.add(tg.id)
files = []
for d in ("openpilot/selfdrive/ui/bp", "bluepilot"):
  for dp, _, fn in os.walk(os.path.join(root, d)):
    files += [os.path.join(dp, f) for f in fn if f.endswith(".py")]
# BP-marked upstream UI files too
for dp, _, fn in os.walk(os.path.join(root, "openpilot/selfdrive/ui")):
  for f in fn:
    p = os.path.join(dp, f)
    if f.endswith(".py") and "BluePilot" in open(p, errors="ignore").read() and p not in files: files.append(p)
for p in sorted(files):
  try: t = ast.parse(open(p).read())
  except Exception: continue
  for n in ast.walk(t):
    if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ui_state" and n.attr not in attrs and not n.attr.startswith("__"):
      print(f"{os.path.relpath(p, root)}: ui_state.{n.attr} not defined on UIState/UIStateSP")
