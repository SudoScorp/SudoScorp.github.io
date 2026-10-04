#!/usr/bin/env python3
"""
Standalone automated affiliate site engine. Python 3.8+, standard library only.

  python affiliate.py build     # generate the static site into ./site
  python affiliate.py serve     # serve site + /go/ click tracker + /admin dashboard + auto-rebuild

Everything is configured by config.json and products.json. No accounts, no fees.
Optional: a local Ollama model writes the review copy (free). Without it, a
template builds copy strictly from the facts you put in products.json.
"""
import html, json, os, re, sqlite3, sys, threading, time, urllib.request, hashlib, base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
SITE = ROOT / "site"
DB = ROOT / "clicks.db"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
for _k, _e in (("base_url", "BASE_URL"), ("site_name", "SITE_NAME"), ("tagline", "TAGLINE")):
    if os.environ.get(_e):
        CFG[_k] = os.environ[_e]
DB_LOCK = threading.Lock()


def esc(s):
    return html.escape(str(s), quote=True)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def db():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS clicks(ts TEXT, slug TEXT, src TEXT, ref TEXT, ip TEXT)")
    return c


def load_products():
    items = json.loads((ROOT / "products.json").read_text(encoding="utf-8"))
    for p in items:
        p["slug"] = p.get("slug") or slugify(p["name"])
        p.setdefault("category", "general")
        p.setdefault("features", [])
        p.setdefault("pros", [])
        p.setdefault("cons", [])
        p.setdefault("price", "")
    return items


# ---------- copy generation ----------
def llm_copy(p):
    """Ask a local Ollama model for copy; return None on any failure."""
    if not CFG.get("ollama_model"):
        return None
    cache = ROOT / "cache"
    cache.mkdir(exist_ok=True)
    key = hashlib.sha1(json.dumps(p, sort_keys=True).encode()).hexdigest()
    cf = cache / f"{key}.txt"
    if cf.exists():
        return cf.read_text(encoding="utf-8")
    prompt = (
        "Write a 150-200 word honest, neutral review intro for the product below. "
        "Use ONLY the facts given. Do not invent statistics, awards, testimonials, "
        "prices, guarantees or income claims. Plain text, no markdown.\n\n"
        + json.dumps({k: p[k] for k in ("name", "description", "features", "pros", "cons", "price") if k in p})
    )
    try:
        req = urllib.request.Request(
            CFG.get("ollama_url", "http://localhost:11434") + "/api/generate",
            data=json.dumps({"model": CFG["ollama_model"], "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
        )
        txt = json.loads(urllib.request.urlopen(req, timeout=180).read())["response"].strip()
        if len(txt) > 80:
            cf.write_text(txt, encoding="utf-8")
            return txt
    except Exception as e:
        print("ollama unavailable, using template:", e)
    return None


def template_copy(p):
    out = p.get("description", "")
    if p["features"]:
        out += " Key features include " + ", ".join(p["features"][:-1]) + (" and " if len(p["features"]) > 1 else "") + p["features"][-1] + "."
    return out


# ---------- html ----------
CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--mut:#666;--ac:#2563eb;--card:#f6f7f9;--bd:#e3e5e8}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#999;--ac:#6ea0ff;--card:#1b1b1d;--bd:#2c2c2f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.6 system-ui,sans-serif}
main,header,footer{max-width:760px;margin:auto;padding:16px}a{color:var(--ac)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:16px;margin:14px 0}
.btn{display:inline-block;background:var(--ac);color:#fff!important;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600}
.disc{font-size:14px;color:var(--mut);border-left:3px solid var(--ac);padding-left:10px}
.pros li::marker{content:"+ "}.cons li::marker{content:"- "}footer{color:var(--mut);font-size:14px}
"""


def page(title, desc, body, canonical_path):
    base = CFG["base_url"].rstrip("/")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{base}{canonical_path}"><style>{CSS}</style></head><body>
<header><a href="/"><b>{esc(CFG['site_name'])}</b></a></header><main>{body}</main>
<footer><p class="disc">{esc(CFG['disclosure'])}</p><p class="disc">{esc(CFG.get('notice',''))}</p>
<p><a href="/disclosure.html">Disclosure</a> · &copy; {datetime.now().year} {esc(CFG['site_name'])}</p></footer></body></html>"""


def cta(p, src):
    return f'<a class="btn" rel="sponsored nofollow noopener" href="/go/{esc(p["slug"])}?src={esc(src)}">Check price / visit {esc(p["name"])}</a>'


def product_page(p, siblings):
    copy = llm_copy(p) or template_copy(p)
    li = lambda xs: "".join(f"<li>{esc(x)}</li>" for x in xs)
    body = f'<p class="disc">{esc(CFG["disclosure"])}</p><h1>{esc(p["name"])} Review</h1>'
    body += "".join(f"<p>{esc(par)}</p>" for par in copy.split("\n") if par.strip())
    if p["price"]:
        body += f'<p><b>Listed price:</b> {esc(p["price"])} <small>(may change; verify on the seller site)</small></p>'
    if p["features"]:
        body += f"<h2>Features</h2><ul>{li(p['features'])}</ul>"
    if p["pros"]:
        body += f"<h2>Pros</h2><ul class=pros>{li(p['pros'])}</ul>"
    if p["cons"]:
        body += f"<h2>Cons</h2><ul class=cons>{li(p['cons'])}</ul>"
    body += f"<p>{cta(p, 'review')}</p>"
    others = [s for s in siblings if s["slug"] != p["slug"]][:4]
    if others:
        body += "<h2>Alternatives</h2><ul>" + "".join(f'<li><a href="/reviews/{s["slug"]}.html">{esc(s["name"])}</a></li>' for s in others) + "</ul>"
    return page(f'{p["name"]} Review', p.get("description", "")[:155], body, f'/reviews/{p["slug"]}.html')


def category_page(cat, items):
    body = f'<p class="disc">{esc(CFG["disclosure"])}</p><h1>Best {esc(cat.title())} Tools Compared</h1>'
    body += "<p>Listed in the order added; this is not a paid ranking.</p>"
    for p in items:
        body += f'<div class="card"><h2><a href="/reviews/{p["slug"]}.html">{esc(p["name"])}</a></h2><p>{esc(p.get("description",""))}</p>'
        if p["pros"]:
            body += f"<p><b>Pros:</b> {esc('; '.join(p['pros'][:3]))}</p>"
        body += f"<p>{cta(p, 'compare')}</p></div>"
    return page(f"Best {cat.title()} Tools Compared", f"Compare {cat} options.", body, f"/best/{slugify(cat)}.html")


def build():
    products = load_products()
    SITE.mkdir(exist_ok=True)
    (SITE / "reviews").mkdir(exist_ok=True)
    (SITE / "best").mkdir(exist_ok=True)
    urls = ["/"]
    for p in products:
        (SITE / "reviews" / f'{p["slug"]}.html').write_text(product_page(p, [x for x in products if x["category"] == p["category"]]), encoding="utf-8")
        urls.append(f'/reviews/{p["slug"]}.html')
    # static redirect pages so /go/<slug> works on free static hosts (no server needed)
    for p in products:
        d = SITE / "go" / p["slug"]
        d.mkdir(parents=True, exist_ok=True)
        t = esc(p["affiliate_url"])
        (d / "index.html").write_text(f'<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex,nofollow"><meta http-equiv="refresh" content="0;url={t}"><link rel="canonical" href="{t}"><title>Redirecting…</title><a href="{t}">Continue to {esc(p["name"])}</a><script>location.replace({json.dumps(p["affiliate_url"])})</script>', encoding="utf-8")
    guides = json.loads((ROOT / "guides.json").read_text(encoding="utf-8")) if (ROOT / "guides.json").exists() else []
    (SITE / "guides").mkdir(exist_ok=True)
    for g in guides:
        u = f"/guides/{g['slug']}.html"
        gb = f'<p class="disc">{esc(CFG["disclosure"])}</p><h1>{esc(g["title"])}</h1>' + "".join(f"<p>{esc(x)}</p>" for x in g["body"])
        (SITE / u.lstrip("/")).write_text(page(g["title"], g["desc"], gb, u), encoding="utf-8")
        urls.append(u)
    cats = {}
    for p in products:
        cats.setdefault(p["category"], []).append(p)
    for c, items in cats.items():
        (SITE / "best" / f"{slugify(c)}.html").write_text(category_page(c, items), encoding="utf-8")
        urls.append(f"/best/{slugify(c)}.html")
    # auto "A vs B" comparison pages (capped), built only from supplied facts
    (SITE / "vs").mkdir(exist_ok=True)
    n = 0
    for c, items in cats.items():
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if n >= CFG.get("max_vs_pages", 200):
                    break
                u = f"/vs/{a['slug']}-vs-{b['slug']}.html"
                col = lambda p: f'<div class="card"><h2>{esc(p["name"])}</h2><p>{esc(p.get("description",""))}</p><p><b>Price:</b> {esc(p["price"] or "see site")}</p><p><b>Pros:</b> {esc("; ".join(p["pros"]) or "n/a")}</p><p><b>Cons:</b> {esc("; ".join(p["cons"]) or "n/a")}</p><p>{cta(p, "vs")}</p></div>'
                body = f'<p class="disc">{esc(CFG["disclosure"])}</p><h1>{esc(a["name"])} vs {esc(b["name"])}</h1>{col(a)}{col(b)}'
                (SITE / u.lstrip("/")).write_text(page(f'{a["name"]} vs {b["name"]}', f'Compare {a["name"]} and {b["name"]}.', body, u), encoding="utf-8")
                urls.append(u)
                n += 1
    idx = f'<p class="disc">{esc(CFG["disclosure"])}</p><h1>{esc(CFG["site_name"])}</h1><p>{esc(CFG["tagline"])}</p>'
    idx += "".join(f'<div class="card"><a href="/best/{slugify(c)}.html"><b>Best {esc(c.title())} Tools</b></a> ({len(i)})</div>' for c, i in cats.items())
    idx += "<h2>Guides</h2><ul>" + "".join(f'<li><a href="/guides/{g["slug"]}.html">{esc(g["title"])}</a></li>' for g in guides) + "</ul>"
    idx += "<h2>All reviews</h2><ul>" + "".join(f'<li><a href="/reviews/{p["slug"]}.html">{esc(p["name"])}</a></li>' for p in products) + "</ul>"
    (SITE / "index.html").write_text(page(CFG["site_name"], CFG["tagline"], idx, "/"), encoding="utf-8")
    (SITE / "disclosure.html").write_text(page("Affiliate Disclosure", "How we earn money", f"<h1>Affiliate Disclosure</h1><p>{esc(CFG['disclosure'])}</p><p>We only describe products using information supplied by the vendors or our own testing notes, and we list drawbacks where known.</p>", "/disclosure.html"), encoding="utf-8")
    base = CFG["base_url"].rstrip("/")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (SITE / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{base}{u}</loc><lastmod>{now}</lastmod></url>" for u in urls + ["/disclosure.html"]) + "</urlset>", encoding="utf-8")
    (SITE / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /go/\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
    # RSS feed (newest 20) so free tools like IFTTT/Buffer/Zapier can auto-post to social
    rfc = lambda: datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items_xml = "".join(f"<item><title>{esc(p['name'])} Review</title><link>{base}/reviews/{p['slug']}.html</link><guid>{base}/reviews/{p['slug']}.html</guid><description>{esc(p.get('description',''))}</description><pubDate>{rfc()}</pubDate></item>" for p in products[-20:][::-1])
    (SITE / "feed.xml").write_text(f'<?xml version="1.0"?><rss version="2.0"><channel><title>{esc(CFG["site_name"])}</title><link>{base}</link><description>{esc(CFG["tagline"])}</description>{items_xml}</channel></rss>', encoding="utf-8")
    # IndexNow key file (free instant indexing for Bing/Yandex)
    key = hashlib.sha1((CFG.get("salt", "") + base).encode()).hexdigest()[:32]
    (SITE / f"{key}.txt").write_text(key, encoding="utf-8")
    (SITE / "urls.json").write_text(json.dumps([base + u for u in urls]), encoding="utf-8")
    print(f"built {len(products)} reviews, {len(cats)} category pages, {n} comparisons -> {SITE}")


# ---------- server ----------
def dashboard():
    with DB_LOCK, db() as c:
        total = c.execute("SELECT COUNT(*) FROM clicks").fetchone()[0]
        per = c.execute("SELECT slug,COUNT(*),SUM(ts>=date('now','-7 day')) FROM clicks GROUP BY slug ORDER BY 2 DESC").fetchall()
        src = c.execute("SELECT src,COUNT(*) FROM clicks GROUP BY src ORDER BY 2 DESC").fetchall()
    rows = "".join(f"<tr><td>{esc(s)}</td><td>{n}</td><td>{w or 0}</td></tr>" for s, n, w in per)
    srows = "".join(f"<tr><td>{esc(s)}</td><td>{n}</td></tr>" for s, n in src)
    return page("Dashboard", "", f"<h1>Dashboard</h1><p>Total outbound clicks: <b>{total}</b></p><table border=1 cellpadding=6><tr><th>Product<th>All<th>7d</tr>{rows}</table><h2>By page type</h2><table border=1 cellpadding=6>{srows}</table><p>Revenue is reported in your affiliate networks; this counts clicks only.</p>", "/admin")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/go/"):
            slug = u.path[4:]
            prod = next((p for p in load_products() if p["slug"] == slug), None)
            if not prod:
                return self.send(404, "Not found")
            q = parse_qs(u.query)
            with DB_LOCK, db() as c:
                c.execute("INSERT INTO clicks VALUES(?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), slug, q.get("src", [""])[0][:30], self.headers.get("Referer", "")[:200], hashlib.sha1((self.client_address[0] + CFG.get("salt", "")).encode()).hexdigest()[:10]))
            return self.send(302, extra={"Location": prod["affiliate_url"], "X-Robots-Tag": "noindex"})
        if u.path == "/admin":
            pw = os.environ.get("ADMIN_PASSWORD") or CFG.get("admin_password", "")
            auth = self.headers.get("Authorization", "")
            ok = pw and auth.startswith("Basic ") and base64.b64decode(auth[6:]).decode(errors="ignore").split(":", 1)[-1] == pw
            if not ok:
                return self.send(401, "Auth required", extra={"WWW-Authenticate": 'Basic realm="admin"'})
            return self.send(200, dashboard())
        path = SITE / (u.path.lstrip("/") or "index.html")
        try:
            path = path.resolve()
            path.relative_to(SITE.resolve())
        except Exception:
            return self.send(403, "Forbidden")
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            return self.send(404, "Not found")
        types = {".html": "text/html; charset=utf-8", ".xml": "application/xml", ".txt": "text/plain"}
        self.send(200, path.read_bytes(), types.get(path.suffix, "application/octet-stream"))


def auto_loop():
    last = None
    while True:
        try:
            mtime = (ROOT / "products.json").stat().st_mtime
            if mtime != last:
                build()
                last = mtime
        except Exception as e:
            print("rebuild failed:", e)
        time.sleep(CFG.get("rebuild_check_seconds", 60))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "build":
        build()
    else:
        threading.Thread(target=auto_loop, daemon=True).start()
        time.sleep(1)
        port = int(os.environ.get("PORT", CFG.get("port", 8080)))
        print(f"serving on http://localhost:{port}  (admin: /admin)")
        ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
