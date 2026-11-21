"""Verifica residuos de WordPress/plugins e links/imagens quebrados no site gerado."""
import re, os, glob, posixpath
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
PRE = chr(92) * 2 + "?" + chr(92)
pat = re.compile(r'(?:href|src|poster)="([^"#?]+)')
files = glob.glob("index.html") + glob.glob("*/index.html")
files = [f for f in files if not f.startswith(("_build", "wp-content", "assets"))]
resid, bad = {}, set()
for f in files:
    h = open(f, encoding="utf-8").read()
    for k in ("woocommerce", "wp-includes/js", "googletagmanager", "complianz", "wpforms", "admin-ajax", "click-to-chat"):
        if k in h:
            resid[k] = resid.get(k, 0) + 1
    d = posixpath.dirname(f.replace(chr(92), "/"))
    for m in pat.finditer(h):
        u = m.group(1)
        if re.match(r"^(https?:|//|mailto:|tel:|data:|javascript:)", u):
            continue
        p = posixpath.normpath(posixpath.join(d, unquote(u)))
        if not (os.path.exists(p) or os.path.exists(PRE + os.path.abspath(p))):
            bad.add((f, u))
print(len(files), "paginas; residuos:", resid)
print("quebrados:", len(bad))
for b in sorted(bad)[:30]:
    print(b)
