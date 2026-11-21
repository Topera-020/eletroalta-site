"""Gera o site EletroAlta estatico (sem WordPress) a partir do site no ar.

Uso:  python _build/build.py [--fetch] [--limit N]
  --fetch  baixa as paginas do site no ar (cache em _build/cache)
Saida: raiz do repositorio (index.html, <slug>/index.html, wp-content/...).
"""
import re, sys, time, shutil, posixpath, urllib.request, urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_build" / "cache"
LOCAL_UPLOADS = Path(r"d:/Thales/Documentos/EletroaltaSite/public_html/wp-content/uploads")
HOST = "eletroalta.com.br"
LIVE = f"https://{HOST}"
PREVIEW = True  # noindex enquanto for apenas preview
SKIP_SLUGS = {"finalizar-compra"}  # resto do WooCommerce
WHATSAPP = "5516992077886"
UA = {"User-Agent": "Mozilla/5.0 (EletroAlta static migration)"}

DROP_SCRIPT = re.compile(
    r"wc_|woocommerce|wpforms|googlesitekit|complianz|ht_ctc|gtag|dataLayer|lintrk|"
    r"_linkedin|EA_WC_CHECKOUT|wc-ajax|sourcebuster|cmplz|speculationrules")
DROP_ID_CLASS = re.compile(r"cmplz|ht-ctc|ht_ctc|wc-block|woocommerce|wpcf7")
DROP_CSS = re.compile(r"woocommerce|complianz|click-to-chat|wpforms|wp-block|elementor")
DROP_STYLE_ID = re.compile(r"woocommerce|wpforms|complianz|ht-ctc|wp-img-auto|classic-theme")
KEEP_SRC = re.compile(r"/wp-content/themes/generatepress/assets/js/(menu|back-to-top)\.min\.js")

missing, unresolved, downloaded = [], set(), set()
DEAD = set()


def lp(p):
    """caminho longo do Windows (prefixo especial)"""
    p = Path(p)
    pre = chr(92) * 2 + "?" + chr(92)
    if sys.platform == "win32" and not str(p).startswith(pre):
        return Path(pre + str(p))
    return p


def http_get(url, binary=False, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as e:  # noqa
            err = e
            time.sleep(1.5)
    raise err


def slug_of(url):
    p = urllib.parse.urlparse(url).path.strip("/")
    return p


def fetch_pages(urls):
    CACHE.mkdir(parents=True, exist_ok=True)
    for u in urls:
        s = slug_of(u) or "_home"
        f = CACHE / f"{s}.html"
        if f.exists() and f.stat().st_size > 1000:
            continue
        print("GET", u)
        f.write_text(http_get(u), encoding="utf-8")
        time.sleep(0.3)


# ---------- reescrita de URLs ----------
ABS = re.compile(r"https?:(?:\\?/\\?/|//)(?:www\.)?" + re.escape(HOST) + r"(/[^\s\"'()<>\\,]*)?")


def rel_url(target_path, from_dir):
    """target_path: caminho absoluto no site ('/slug/', '/wp-content/..'); from_dir: pasta da pagina ('' = raiz)."""
    path, frag = target_path, ""
    if "#" in path:
        path, frag = path.split("#", 1)
        frag = "#" + frag
    path = path.split("?")[0]
    is_dir = path.endswith("/") or "." not in posixpath.basename(path)
    p = path.strip("/")
    start = from_dir or "."
    if not p:
        r = posixpath.relpath(".", start)
        return ("./" if r == "." else r + "/") + frag
    r = posixpath.relpath(p, start)
    return r + ("/" if is_dir else "") + frag


def note_target(path):
    p = path.split("?")[0].split("#")[0]
    if p.startswith("/wp-content/") or p.startswith("/wp-includes/"):
        return
    s = p.strip("/")
    if s and s not in PAGES:
        unresolved.add(p)


def relativize_text(text, from_dir):
    def sub(m):
        path = (m.group(1) or "/").replace("\\/", "/")
        _k = "/" + path.split("#")[0].split("?")[0].strip("/")
        if REDIR.get(_k) == "LIVE" or REDIR.get(_k + "/") == "LIVE":
            return m.group(0)
        note_target(path)
        return rel_url(path, from_dir)
    return ABS.sub(sub, text)


def relativize_attr(val, from_dir):
    if not val:
        return val
    return relativize_text(val, from_dir)


# ---------- ativos ----------
def want_asset(path):
    """garante que o arquivo (caminho absoluto no site) exista no repo."""
    path = urllib.parse.unquote(path.split("?")[0].split("#")[0])
    if path in DEAD:
        return None
    dest = lp(ROOT / path.lstrip("/"))
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.startswith("/wp-content/uploads/"):
        src = LOCAL_UPLOADS / path[len("/wp-content/uploads/"):]
        if src.exists():
            shutil.copy2(src, dest)
            return dest
    try:
        data = http_get(LIVE + urllib.parse.quote(path), binary=True)
        dest.write_bytes(data)
        downloaded.add(path)
    except Exception as e:  # noqa
        missing.append((path, str(e)))
        DEAD.add(path)
        return None
    return dest


def process_css_file(path):
    dest = want_asset(path)
    if not dest or dest.suffix != ".css":
        return
    css = dest.read_text(encoding="utf-8", errors="replace")
    base = posixpath.dirname(path)
    css = relativize_text(css, base.strip("/"))
    dest.write_text(css, encoding="utf-8")
    for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)", css):
        u = m.group(1)
        if u.startswith(("data:", "http", "#", "//")):
            continue
        ap = posixpath.normpath(posixpath.join(base, u.split("?")[0].split("#")[0]))
        if ap.startswith("/wp-content") or ap.startswith("/wp-includes"):
            want_asset(ap)


UPLOAD_RE = re.compile(r"/wp-content/(?:uploads|themes)/[^\s\"'()<>\\,]+?\.(?:png|jpe?g|webp|gif|svg|mp4|webm|pdf|ico|woff2?|ttf|css|js)", re.I)


def collect_assets(html):
    for m in UPLOAD_RE.finditer(html):
        want_asset(m.group(0))


# ---------- transformacao ----------
def transform(slug, raw):
    from_dir = slug
    soup = BeautifulSoup(raw, "html.parser")
    head, body = soup.head, soup.body

    # <link>
    for l in list(soup.find_all("link")):
        rel = " ".join(l.get("rel", []))
        href = l.get("href", "")
        if "stylesheet" in rel:
            if DROP_CSS.search(href):
                l.decompose(); continue
            if HOST in href:
                path = urllib.parse.urlparse(href).path
                process_css_file(path)
                l["href"] = rel_url(path, from_dir)
        elif rel in ("canonical",):
            continue
        elif rel in ("icon", "apple-touch-icon", "preload", "image_src"):
            if HOST in href:
                path = urllib.parse.urlparse(href).path
                want_asset(path)
                l["href"] = rel_url(path, from_dir)
        elif rel in ("alternate", "EditURI", "wlwmanifest", "shortlink", "pingback", "https://api.w.org/", "dns-prefetch", "prefetch", "profile") or "oembed" in str(l.get("type", "")):
            l.decompose()

    # <style>
    for st in list(soup.find_all("style")):
        if DROP_STYLE_ID.search(st.get("id", "") or ""):
            st.decompose(); continue
        if st.string:
            st.string = relativize_text(st.string, from_dir)

    # <script>
    for sc in list(soup.find_all("script")):
        src = sc.get("src")
        t = sc.get("type") or ""
        if src:
            if KEEP_SRC.search(src):
                path = urllib.parse.urlparse(src).path
                want_asset(path)
                sc["src"] = rel_url(path, from_dir)
            else:
                sc.decompose()
            continue
        code = sc.string or sc.get_text() or ""
        if "ld+json" in t:
            continue
        if DROP_SCRIPT.search(code) or "speculationrules" in t or "text/plain" in t:
            sc.decompose(); continue
        if "generatepressMenu" in code or "generatepressBackToTop" in code:
            code = re.sub(r"//# sourceURL=.*", "", code)
        sc.string = relativize_text(code, from_dir)
    for ns in soup.find_all("noscript"):
        if "facebook" in str(ns) or "linkedin" in str(ns) or "googletagmanager" in str(ns):
            ns.decompose()

    # elementos de plugins
    for el in list(soup.find_all(True)):
        if el.decomposed if hasattr(el, "decomposed") else False:
            continue
        ident = " ".join(filter(None, [el.get("id", ""), " ".join(el.get("class", []) or [])]))
        if ident and DROP_ID_CLASS.search(ident) and el.name not in ("html", "body", "head", "main", "article", "header", "footer"):
            el.decompose()
    for form in soup.find_all("form"):
        act = form.get("action", "")
        if "wp-comments" in act or "?s=" in act or form.get("role") == "search":
            form.decompose()

    if body is not None:
        body["class"] = [c for c in body.get("class", []) if not c.startswith("woocommerce")]
        for i in body.find_all("script"):
            pass

    from bs4 import Comment
    for c in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if re.search(r"Complianz|Click to Chat|wpforms|WooCommerce|Site Kit|Rank Math|This site is optimized", c, re.I):
            c.extract()
    for sc in soup.find_all("script", attrs={"type": ["importmap", "module"]}):
        sc.decompose()
    for l in soup.find_all("link", rel="modulepreload"):
        l.decompose()
    clean_forms(soup)
    fix_anchors(soup, from_dir)
    # atributos com URL
    for el in soup.find_all(True):
        for a in ("href", "src", "poster", "data-image", "data-src", "data-bg", "action", "data-href"):
            v = el.get(a)
            if v and isinstance(v, str):
                if el.name == "link" and el.get("rel") == ["canonical"]:
                    continue
                nv = relativize_attr(v, from_dir)
                if nv == v and v.startswith("/") and not v.startswith("//") and el.name != "form":
                    nv = rel_url(v, from_dir)
                if nv != v:
                    el[a] = nv
        for a in ("srcset", "data-srcset"):
            v = el.get(a)
            if v:
                el[a] = relativize_attr(v, from_dir)
        if el.get("style"):
            el["style"] = relativize_attr(el["style"], from_dir)
        # tags <meta content=...> mantem absoluto (og:image etc.)

    # rodape: remove creditos do tema
    for c in soup.select(".copyright-bar"):
        c.clear()
        c.append(BeautifulSoup('<span class="copyright">&copy; 2026 EletroAlta Engenharia</span>', "html.parser"))

    # preview: noindex
    if PREVIEW:
        # nao usar decompose: a tag vem sem fechamento e o parser aninha o resto do <head> nela
        robots = soup.find_all("meta", attrs={"name": "robots"})
        for m in robots:
            m["content"] = "noindex, nofollow"
        if not robots:
            head.insert(0, BeautifulSoup('<meta name="robots" content="noindex, nofollow">', "html.parser"))

    head.append(BeautifulSoup('<script defer src="%s"></script>' % rel_url("/assets/site-extra.js", from_dir), "html.parser"))
    # css/botao extra
    extra = BeautifulSoup(f'<link rel="stylesheet" href="{rel_url("/assets/site-extra.css", from_dir)}">', "html.parser")
    head.append(extra)
    wa = BeautifulSoup(
        f'<a class="ea-whatsapp" href="https://wa.me/{WHATSAPP}?text=Ol%C3%A1.%20Estou%20visitando%20o%20site%20da%20EletroAlta" '
        f'target="_blank" rel="noopener" aria-label="Falar no WhatsApp">WhatsApp</a>', "html.parser")
    body.append(wa)

    html = str(soup)
    collect_assets(html)
    return html


def main():
    global PAGES
    urls = [u.strip() for u in (ROOT / "_build" / "urls.txt").read_text().splitlines() if u.strip()]
    PAGES = {slug_of(u) for u in urls} - SKIP_SLUGS
    if "--limit" in sys.argv:
        urls = urls[: int(sys.argv[sys.argv.index("--limit") + 1])]
    if "--fetch" in sys.argv:
        fetch_pages(urls)
    (ROOT / "assets").mkdir(exist_ok=True)
    (ROOT / "assets" / "site-extra.css").write_text(
        ".ea-whatsapp{position:fixed;right:18px;bottom:18px;z-index:9999;background:#25d366;color:#fff;"
        "font:600 15px/1 Inter,system-ui,sans-serif;padding:14px 18px;border-radius:999px;text-decoration:none;"
        "box-shadow:0 4px 14px rgba(0,0,0,.25)}.ea-whatsapp:hover{background:#1ebe5b;color:#fff}\n"
        "[data-ea-form] .wpforms-field{margin:0 0 16px}[data-ea-form] label{display:block;font-weight:600;margin-bottom:6px}"
        "[data-ea-form] input[type=text],[data-ea-form] input[type=email],[data-ea-form] input[type=number],"
        "[data-ea-form] input[type=tel],[data-ea-form] select,[data-ea-form] textarea{width:100%;max-width:100%;padding:12px 14px;"
        "border:1px solid #c5cbd3;border-radius:8px;font:inherit;box-sizing:border-box}"
        "[data-ea-form] .wpforms-field-row{display:flex;gap:12px;flex-wrap:wrap}[data-ea-form] .wpforms-field-row-block{flex:1 1 200px}"
        "[data-ea-form] button[type=submit]{background:#0b3d91;color:#fff;border:0;border-radius:8px;padding:14px 28px;font:600 16px Inter,system-ui,sans-serif;cursor:pointer}"
        "[data-ea-form] button[type=submit]:hover{background:#082d6b}.ea-form-note{font-size:13px;opacity:.75;margin-top:10px}"
        ".wpforms-required-label{color:#c0392b}\n",
        encoding="utf-8")
    ok = 0
    for u in urls:
        s = slug_of(u)
        if s in SKIP_SLUGS:
            continue
        f = CACHE / f"{s or '_home'}.html"
        if not f.exists():
            print("sem cache:", u); continue
        html = transform(s, f.read_text(encoding="utf-8"))
        out = ROOT / (f"{s}/index.html" if s else "index.html")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        ok += 1
    (ROOT / "robots.txt").write_text("User-agent: *\nDisallow: /\n" if PREVIEW else f"User-agent: *\nAllow: /\nSitemap: {LIVE}/sitemap.xml\n")
    rep = ["PAGINAS GERADAS: %d" % ok, "", "LINKS INTERNOS SEM DESTINO (%d):" % len(unresolved)] + sorted(unresolved)
    rep += ["", "ARQUIVOS NAO ENCONTRADOS (%d):" % len(missing)] + [f"{p}  {e}" for p, e in missing]
    rep += ["", "BAIXADOS DO SITE NO AR: %d" % len(downloaded)]
    (ROOT / "_build" / "report.txt").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep[:40]))


PAGES = set()


def clean_forms(soup):
    for fm in soup.select(".wpforms-container form"):
        for sel in ("input[type=hidden]", ".wpforms-field-hp", ".wpforms-recaptcha-container",
                    ".wpforms-error-container", ".wpforms-field-recaptcha", "noscript", ".wpforms-field-hidden"):
            for e in fm.select(sel):
                e.decompose()
        for a in list(fm.attrs):
            if a not in ("class", "id"):
                del fm.attrs[a]
        for im in fm.find_all("img"):
            if "wpforms" in (im.get("src") or ""):
                im.decompose()
        fm["data-ea-form"] = "1"
        for b in fm.select("button"):
            for a in list(b.attrs):
                if a not in ("class", "type"):
                    del b.attrs[a]
            b["type"] = "submit"
        fm.append(BeautifulSoup('<p class="ea-form-note">Ao enviar, abriremos o WhatsApp da EletroAlta com a sua mensagem preenchida.</p>', "html.parser"))


import json
REDIR = {}
_rf = Path(__file__).resolve().parent / "redirects_raw.json"
if _rf.exists():
    for k, (code, loc) in json.load(open(_rf)).items():
        if code in (301, 302) and loc and HOST in loc and "wp-login" not in loc:
            REDIR[k] = "/" + urllib.parse.urlparse(loc).path.lstrip("/")
            if REDIR[k] == "/": REDIR[k] = "/"
        elif code == 200 and not k.startswith(("/wp-json", "/wp-login")) and "/embed/" not in k:
            REDIR[k] = "LIVE"
UNWRAP = re.compile(r"^/(tag|category|author|wp-json|wp-admin|wp-login|embed|feed|comments)(/|\.|$)|/embed/?$|/feed/?$")


def fix_anchors(soup, from_dir):
    for a in soup.find_all("a", href=True):
        m = ABS.match(a["href"])
        path = (m.group(1) or "/") if m else (a["href"] if a["href"].startswith("/") else None)
        if path is None:
            continue
        pp = path.split("#")[0].split("?")[0]
        frag = ("#" + path.split("#", 1)[1]) if "#" in path else ""
        pp = "/" + pp.strip("/") + ("/" if pp.strip("/") else "")
        if pp.strip("/") in PAGES or pp == "/" or pp.startswith(("/wp-content", "/wp-includes")):
            continue
        if pp in REDIR or pp.rstrip("/") in REDIR:
            t = REDIR.get(pp) or REDIR.get(pp.rstrip("/"))
            if t == "LIVE":
                a["href"] = LIVE + pp + frag
            else:
                a["href"] = rel_url(t + frag, from_dir)
        elif UNWRAP.search(pp) or pp.strip("/") in SKIP_SLUGS or True:
            a.unwrap()


if __name__ == "__main__":
    main()
