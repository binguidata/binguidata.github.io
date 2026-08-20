#!/usr/bin/env python3
"""Sync shared regions and data values into the static pages.

This is NOT a build step. The committed .html files are always complete and
valid on their own; this script only rewrites regions that are already there,
in place. If it is never run, the site still works exactly as committed.

  ./sync.py           rewrite pages from _partials/
  ./sync.py --check   report drift, change nothing (exit 1 if any)

Two mechanisms:

  1. Shared regions.  Anything between
         <!-- @shared:nav -->  ...  <!-- @end:nav -->
     is replaced by _partials/nav.html. Same for `head` and `footer`.

  2. Data values.  Any element carrying data-sync="path.to.key" has its text
     replaced by that value from _partials/data.json, so numbers that appear on
     more than one page are edited in exactly one place.

Placeholders of the form {{path.to.key}} inside a partial are filled from
data.json before insertion.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTIALS = ROOT / "_partials"
REGIONS = ("head", "nav", "footer")
PAGES = sorted(p for p in ROOT.glob("*.html"))


def lookup(data, dotted):
    node = data
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f"{dotted!r} is not in _partials/data.json")
        node = node[key]
    return str(node)


def fill(text, data):
    return re.sub(
        r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}",
        lambda m: lookup(data, m.group(1)),
        text,
    )


def apply_region(html, name, body):
    """Replace the content between the markers for one region."""
    pattern = re.compile(
        rf"(<!--\s*@shared:{name}\s*-->\n)(.*?)(^[ \t]*<!--\s*@end:{name}\s*-->)",
        re.DOTALL | re.MULTILINE,
    )
    if not pattern.search(html):
        return html, False
    return pattern.sub(lambda m: m.group(1) + body + m.group(3), html), True


def set_current_page(html, filename):
    """Mark the nav link for this page, and only this page."""
    html = re.sub(r'\s+aria-current="page"', "", html)
    return re.sub(
        rf'(<a href="{re.escape(filename)}")(>)',
        r'\1 aria-current="page"\2',
        html,
        count=1,
    )


def apply_data(html, data):
    """Rewrite the text of every element carrying data-sync."""
    def swap(m):
        return m.group(1) + lookup(data, m.group(2)) + m.group(3)

    return re.sub(
        r'(<(?P<tag>[a-z]+)[^>]*\sdata-sync="([a-zA-Z0-9_.]+)"[^>]*>)(?:.*?)(</(?P=tag)>)',
        lambda m: m.group(1) + lookup(data, m.group(3)) + m.group(4),
        html,
        flags=re.DOTALL,
    )


def main():
    check = "--check" in sys.argv
    data = json.loads((PARTIALS / "data.json").read_text())

    bodies = {}
    for name in REGIONS:
        bodies[name] = fill((PARTIALS / f"{name}.html").read_text(), data)

    drifted = []
    for page in PAGES:
        original = page.read_text()
        html = original
        found = []
        for name in REGIONS:
            html, hit = apply_region(html, name, bodies[name])
            if hit:
                found.append(name)

        if "nav" in found:
            html = set_current_page(html, page.name)
        html = apply_data(html, data)
        # cache-bust stamps live outside the shared regions too (script.js)
        html = re.sub(r"\?v=[0-9A-Za-z.\-]+", "?v=" + data["version"], html)

        missing = set(REGIONS) - set(found)
        if missing:
            print(f"  ! {page.name}: no markers for {', '.join(sorted(missing))}")

        if html != original:
            drifted.append(page.name)
            if not check:
                page.write_text(html)
                print(f"  ~ {page.name} updated")
        elif not check:
            print(f"  = {page.name} already current")

    if check:
        if drifted:
            print(f"drift in: {', '.join(drifted)}")
            return 1
        print("all pages current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
