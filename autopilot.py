#!/usr/bin/env python3
"""
Autopilot: run unattended on a schedule.
  python autopilot.py run        # ingest feeds -> build -> publish -> ping search engines
  python autopilot.py install    # register a daily Windows scheduled task (or prints a cron line)

feeds.json example (product feeds you get from your affiliate networks):
[{"name":"net1","url":"https://.../feed.csv","format":"csv",
  "link_template":"{url}?aff=YOURID", "default_category":"software"}]
CSV columns: name,description,url,category,price,features,pros,cons   (lists separated by |)
JSON feeds: a list of objects with those same keys.
"""
import csv, io, json, os, subprocess, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import affiliate as A  # noqa: E402

CFG = A.CFG


def fetch(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "affiliate-autopilot"}), timeout=60).read().decode("utf-8", "replace")


def rows(feed):
    raw = fetch(feed["url"])
    if feed.get("format", "csv") == "json":
        return json.loads(raw)
    return list(csv.DictReader(io.StringIO(raw)))


def ingest():
    fp = ROOT / "feeds.json"
    if not fp.exists():
        print("no feeds.json; skipping ingest")
        return
    pf = ROOT / "products.json"
    products = json.loads(pf.read_text(encoding="utf-8"))
    have = {A.slugify(p["name"]) for p in products}
    cap = CFG.get("max_new_per_run", 10)
    added = 0
    for feed in json.loads(fp.read_text(encoding="utf-8")):
        try:
            data = rows(feed)
        except Exception as e:
            print("feed failed", feed.get("name"), e)
            continue
        for r in data:
            if added >= cap:
                break
            name = (r.get("name") or "").strip()
            url = (r.get("url") or "").strip()
            if not name or not url.startswith("http") or A.slugify(name) in have:
                continue
            lst = lambda k: [x.strip() for x in str(r.get(k) or "").split("|") if x.strip()]
            products.append({
                "name": name,
                "category": (r.get("category") or feed.get("default_category") or "general").strip().lower(),
                "description": (r.get("description") or "").strip()[:600],
                "features": lst("features"), "pros": lst("pros"), "cons": lst("cons"),
                "price": (r.get("price") or "").strip(),
                "affiliate_url": feed.get("link_template", "{url}").format(url=url, **{k: v for k, v in os.environ.items() if k.startswith("AFF_")}),
            })
            have.add(A.slugify(name))
            added += 1
    pf.write_text(json.dumps(products, indent=2), encoding="utf-8")
    print(f"ingested {added} new products")


def publish():
    cmd = CFG.get("publish_cmd", "")
    if not cmd:
        print("no publish_cmd set; site left in ./site")
        return
    r = subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True)
    print("publish:", r.returncode, (r.stdout + r.stderr)[-300:])


def indexnow():
    host = CFG["base_url"].replace("https://", "").replace("http://", "").rstrip("/")
    if host.startswith("localhost"):
        return
    key = (next((ROOT / "site").glob("*.txt"), None))
    keys = [p for p in (ROOT / "site").glob("*.txt") if len(p.stem) == 32]
    if not keys:
        return
    k = keys[0].stem
    urls = json.loads((ROOT / "site" / "urls.json").read_text())[:10000]
    body = json.dumps({"host": host, "key": k, "keyLocation": f"{CFG['base_url'].rstrip('/')}/{k}.txt", "urlList": urls}).encode()
    try:
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, headers={"Content-Type": "application/json"})
        print("indexnow:", urllib.request.urlopen(req, timeout=30).status)
    except Exception as e:
        print("indexnow failed:", e)


def install():
    py, me = sys.executable, str(ROOT / "autopilot.py")
    if sys.platform == "win32":
        subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", "06:00", "/TN", "AffiliateAutopilot", "/TR", f'"{py}" "{me}" run'])
    else:
        print(f'Add to crontab:  0 6 * * * {py} {me} run')


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "install":
        install()
    else:
        ingest()
        A.build()
        publish()
        indexnow()
