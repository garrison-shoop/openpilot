"""Static: every openpilot./opendbc. import resolves, and each imported name exists in its module.
Usage: python3 import_check.py <repo root>. Expected noise: cereal log/custom/car (generated at
runtime), OFFROAD_ALERTS (defined in a with-block). Diff against the previous sync, see SYNCING.md 6."""
import ast, os, sys
root = sys.argv[1]
roots = {"openpilot": os.path.join(root, "openpilot"), "opendbc": os.path.join(root, "opendbc_repo", "opendbc")}
def mod_path(mod):
  parts = mod.split(".")
  if parts[0] not in roots: return None
  base = os.path.join(roots[parts[0]], *parts[1:])
  if parts[:2] == ["openpilot", "bluepilot"]: base = os.path.join(root, "bluepilot", *parts[2:])
  for c in (base + ".py", os.path.join(base, "__init__.py"), base + ".pyx", base + ".pyi"):
    if os.path.exists(c): return c
  if os.path.isdir(base): return base  # namespace pkg
  return False
cache = {}
def names(path):
  if path in cache: return cache[path]
  s = set()
  if path.endswith(".py"):
    try: t = ast.parse(open(path).read())
    except Exception: t = None
    if t:
      for n in ast.walk(t) if False else t.body:
        for x in ([n] + (n.body + n.orelse if isinstance(n, (ast.If, ast.Try)) else []) + ([h for hh in n.handlers for h in hh.body] if isinstance(n, ast.Try) else [])):
          if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): s.add(x.name)
          elif isinstance(x, (ast.Assign, ast.AnnAssign)):
            for tg in (x.targets if isinstance(x, ast.Assign) else [x.target]):
              for e in ast.walk(tg):
                if isinstance(e, ast.Name): s.add(e.id)
          elif isinstance(x, (ast.Import, ast.ImportFrom)):
            for a in x.names: s.add((a.asname or a.name).split(".")[0]); s.add("*") if a.name == "*" else None
      if any(isinstance(n, ast.FunctionDef) and n.name == "__getattr__" for n in t.body): s.add("*")
  else: s.add("*")
  cache[path] = s; return s
bad = []
for d in ("openpilot", "bluepilot", "opendbc_repo/opendbc"):
  for dp, dn, fn in os.walk(os.path.join(root, d), followlinks=False):
    if any(x in dp for x in ("/tests", "/test", "/tools", "/third_party", "/debug", "/scripts")): continue
    for f in fn:
      if not f.endswith(".py"): continue
      p = os.path.join(dp, f)
      try: t = ast.parse(open(p).read())
      except Exception as e: bad.append((p, 0, f"SYNTAX {e}")); continue
      for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
          mp = mod_path(n.module)
          if mp is False: bad.append((p, n.lineno, f"no module {n.module}")); continue
          if mp is None: continue
          for a in n.names:
            if a.name == "*": continue
            sub = mod_path(n.module + "." + a.name)
            if sub: continue
            ns = names(mp) if not os.path.isdir(mp) else {"*"}
            if "*" not in ns and a.name not in ns: bad.append((p, n.lineno, f"{n.module} has no {a.name}"))
        elif isinstance(n, ast.Import):
          for a in n.names:
            if mod_path(a.name) is False: bad.append((p, n.lineno, f"no module {a.name}"))
for p, l, m in bad: print(f"{os.path.relpath(p, root)}:{l}: {m}")
print(f"{len(bad)} issues", file=sys.stderr)
