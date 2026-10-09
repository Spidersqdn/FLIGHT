#!/usr/bin/env python3
"""Compare two AIRAC cycles of the Thailand eAIP (aip.caat.or.th).

Downloads the ENR 3, ENR 4, ENR 5.1, AD 2, AMDT, SUP and AIC pages of both
cycles, turns them into plain text and writes unified diffs.

  aip_diff.py find   --ref 2026-10-01           -> prints "<new> <prev>" of cycles to check
  aip_diff.py diff   --new 2026-10-29 --prev 2026-10-01 --out aip-out

Output (diff): aip-out/diff/<page>.diff, aip-out/all.diff,
aip-out/summary.md, aip-out/stats.json
"""
import argparse
import datetime as dt
import difflib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

SITE = os.environ.get("AIP_SITE", "https://aip.caat.or.th")
UA = "Mozilla/5.0 (AirNavFlow AIP watch; +https://github.com/Spidersqdn/FLIGHT)"
PAGE_RE = re.compile(r"VT-(?:ENR-(?:3\.\d|4\.\d|5\.1)|AD-2\.[A-Z]{4}|AMDT)-en-GB\.html")
EXTRA = ["eSUP/VT-eSUPs-en-GB.html", "eAIC/VT-eAICs-en-GB.html"]
FALLBACK = (["eAIP/VT-ENR-3.%d-en-GB.html" % i for i in range(1, 7)]
            + ["eAIP/VT-ENR-4.%d-en-GB.html" % i for i in range(1, 6)]
            + ["eAIP/VT-ENR-5.1-en-GB.html", "eAIP/VT-AMDT-en-GB.html"])
BLOCK = {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6",
         "table", "thead", "tbody", "ul", "ol", "dt", "dd"}


def base(cycle):
    return "%s/%s-AIRAC/html/" % (SITE, cycle)


def fetch(url, tries=3):
    """Return page text, or None on 404."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            err = e
        except Exception as e:  # network hiccup
            err = e
        time.sleep(2 ** (i + 1))
    raise RuntimeError("fetch failed: %s (%s)" % (url, err))


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("\n")
        elif tag in ("td", "th"):
            self.out.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


# eAIP pages carry hidden database tags such as "TFREQUENCY;VAL_FREQ_TRANS;188"
TAG_RE = re.compile(r"T[A-Z_]+;[A-Z_]+;\d+")


def to_text(src):
    p = Text()
    p.feed(src)
    text = TAG_RE.sub("", "".join(p.out))
    lines = (re.sub(r"[ \t\r\f\v\xa0]+", " ", l).strip(" |") for l in text.split("\n"))
    return [l for l in lines if l]


def pages(cycle):
    menu = fetch(base(cycle) + "eAIP/VT-menu-en-GB.html")
    found = sorted(set(PAGE_RE.findall(menu or "")))
    return (["eAIP/" + f for f in found] or FALLBACK) + EXTRA


def published(cycle):
    try:
        return fetch(base(cycle) + "eAIP/VT-menu-en-GB.html") is not None
    except RuntimeError:
        return False


def cmd_find(a):
    """Print the current and next AIRAC dates (with their previous cycle)."""
    ref = dt.date.fromisoformat(a.ref)
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    n = (today - ref).days // 28
    for k in (n, n + 1):
        new = ref + dt.timedelta(days=28 * k)
        prev = new - dt.timedelta(days=28)
        if published(new.isoformat()):
            print(new.isoformat(), prev.isoformat())


def cmd_diff(a):
    os.makedirs(os.path.join(a.out, "diff"), exist_ok=True)
    names = sorted(set(pages(a.new)) | set(pages(a.prev)))
    rows, chunks = [], []
    for name in names:
        old = fetch(base(a.prev) + name)
        new = fetch(base(a.new) + name)
        o, n = to_text(old or ""), to_text(new or "")
        d = list(difflib.unified_diff(o, n, "%s/%s" % (a.prev, name), "%s/%s" % (a.new, name),
                                      n=2, lineterm=""))
        if not d:
            continue
        add = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
        rem = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
        note = "new page" if old is None else ("removed" if new is None else "")
        page = os.path.basename(name).replace("-en-GB.html", "")
        text = "\n".join(d) + "\n"
        with open(os.path.join(a.out, "diff", page + ".diff"), "w") as f:
            f.write(text)
        chunks.append(text)
        rows.append((page, add, rem, note))
    allx = "".join(chunks)
    with open(os.path.join(a.out, "all.diff"), "w") as f:
        f.write(allx)
    stats = {"new": a.new, "prev": a.prev, "pages_checked": len(names),
             "pages_changed": len(rows), "chars": len(allx),
             # rough estimate: about 3.5 characters per token for English AIP text
             "est_tokens": math.ceil(len(allx) / 3.5)}
    with open(os.path.join(a.out, "stats.json"), "w") as f:
        json.dump(stats, f, indent=1)
    md = ["AIRAC **%s** vs **%s**: %d of %d pages changed, diff about %s tokens."
          % (a.new, a.prev, len(rows), len(names), format(stats["est_tokens"], ",")), "",
          "| Page | + lines | - lines | Note |", "|---|---:|---:|---|"]
    md += ["| %s | %d | %d | %s |" % r for r in rows]
    with open(os.path.join(a.out, "summary.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print(json.dumps(stats))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--ref", required=True, help="any known AIRAC date, YYYY-MM-DD")
    f.add_argument("--today")
    d = sub.add_parser("diff")
    d.add_argument("--new", required=True)
    d.add_argument("--prev", required=True)
    d.add_argument("--out", default="aip-out")
    a = ap.parse_args()
    {"find": cmd_find, "diff": cmd_diff}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
