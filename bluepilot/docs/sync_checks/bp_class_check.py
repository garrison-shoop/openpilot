"""For BluePilot UI classes: flag self.X / super().X / CONST.X uses missing from the new parent chain,
and overridden methods whose positional-arg count differs from the parent's."""
import ast, os, sys
root = sys.argv[1]
def mpath(mod):
  parts = mod.split(".")
  if parts[0] != "openpilot": return None
  base = os.path.join(root, *parts)
  if parts[:2] == ["openpilot", "bluepilot"]: base = os.path.join(root, "bluepilot", *parts[2:])
  for c in (base + ".py", os.path.join(base, "__init__.py")):
    if os.path.exists(c): return c
  return None
trees = {}
def tree(p):
  if p not in trees: trees[p] = ast.parse(open(p).read())
  return trees[p]
def imports(p):
  m = {}
  for n in ast.walk(tree(p)):
    if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
      for a in n.names: m[a.asname or a.name] = (n.module, a.name)
  return m
def find_class(p, name, depth=0):
  if depth > 5 or p is None: return None
  for n in tree(p).body:
    if isinstance(n, ast.ClassDef) and n.name == name: return (p, n)
  imp = imports(p)
  if name in imp:
    mod, orig = imp[name]
    return find_class(mpath(mod), orig, depth + 1)
  return None
def class_info(p, c, seen=None):
  """attrs: name -> (argcount or None); walks bases recursively. unresolved -> '*'"""
  seen = seen or set()
  if (p, c.name) in seen: return {}, False
  seen.add((p, c.name))
  attrs, opaque = {}, False
  for b in c.bases:
    bname = b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else None)
    if bname in (None, "object", "ABC", "Generic"): continue
    r = find_class(p, bname)
    if r is None: opaque = True; continue
    a, o = class_info(*r, seen); opaque |= o
    for k, v in a.items(): attrs.setdefault(k, v)
  own = own_attrs(c)
  attrs.update(own)
  return attrs, opaque
def own_attrs(c):
  a = {}
  for n in c.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
      a[n.name] = len(n.args.args) + len(n.args.posonlyargs) if not (n.args.vararg) else None
    elif isinstance(n, ast.Assign):
      for t in n.targets:
        if isinstance(t, ast.Name): a[t.id] = "attr"
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name): a[n.target.id] = "attr"
  for n in ast.walk(c):
    if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
      for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
        for e in ast.walk(t):
          if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "self": a.setdefault(e.attr, "attr")
  return a
WIDGET_OK = set(dir(object))
issues = []
bpdir = os.path.join(root, "openpilot/selfdrive/ui/bp")
for dp, _, fn in os.walk(bpdir):
  for f in fn:
    if not f.endswith(".py"): continue
    p = os.path.join(dp, f)
    t = tree(p)
    imp = imports(p)
    # dataclass-config constants imported from upstream, e.g. UI_CONFIG
    for n in ast.walk(t):
      if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id.isupper() and n.value.id in imp:
        mod, orig = imp[n.value.id]; mp = mpath(mod)
        if not mp: continue
        for s in tree(mp).body:
          if isinstance(s, ast.Assign) and any(isinstance(x, ast.Name) and x.id == orig for x in s.targets) and isinstance(s.value, ast.Call):
            cname = getattr(s.value.func, "id", None); r = find_class(mp, cname) if cname else None
            if r:
              fields = own_attrs(r[1])
              if n.attr not in fields: issues.append(f"{os.path.relpath(p, root)}:{n.lineno}: {n.value.id}.{n.attr} no longer exists ({cname})")
    for c in [n for n in ast.walk(t) if isinstance(n, ast.ClassDef)]:
      if not c.bases: continue
      inherited, opaque = {}, False
      for b in c.bases:
        bname = b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else None)
        if not bname: continue
        r = find_class(p, bname)
        if r is None:
          if bname in imp and mpath(imp[bname][0]) and not find_class(mpath(imp[bname][0]), imp[bname][1]):
            issues.append(f"{os.path.relpath(p, root)}:{c.lineno}: {c.name} base {bname} not found in {imp[bname][0]}")
          opaque = True; continue
        a, o = class_info(*r); opaque |= o
        for k, v in a.items(): inherited.setdefault(k, v)
      own = own_attrs(c)
      if not inherited: continue
      for n in ast.walk(c):
        # super().X
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", None) == "super":
          if n.attr not in inherited and n.attr not in WIDGET_OK and not opaque:
            issues.append(f"{os.path.relpath(p, root)}:{n.lineno}: {c.name}: super().{n.attr} missing from parents")
        # self.X reads not defined anywhere
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and isinstance(n.ctx, ast.Load):
          if n.attr not in own and n.attr not in inherited and n.attr not in WIDGET_OK and not opaque:
            issues.append(f"{os.path.relpath(p, root)}:{n.lineno}: {c.name}: self.{n.attr} not defined in class or parents")
      # signature drift on overrides
      for m in c.body:
        if isinstance(m, ast.FunctionDef) and m.name in inherited and isinstance(inherited[m.name], int) and not m.args.vararg:
          mine = len(m.args.args) + len(m.args.posonlyargs)
          if mine != inherited[m.name] and not m.name.startswith("__"):
            issues.append(f"{os.path.relpath(p, root)}:{m.lineno}: {c.name}.{m.name} takes {mine} args, parent takes {inherited[m.name]}")
for i in sorted(set(issues)): print(i)
