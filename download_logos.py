#!/usr/bin/env python3
"""Scarica i loghi dei canali di film_stasera.py dalla guida di EPGItalia, in <canale>.png.

I loghi sono marchi di terzi (li ospita guidatv.sky.it e li indica la guida): per uso personale, in Home Assistant, e NON
vanno messi in un repository pubblico. Servono solo a chi li vuole nella dashboard (dashboard_card.yaml).

Uso:
  download_logos.py                          scarica in /config/www/tv-logos (la cartella di film_stasera.py)
  download_logos.py --dest ./logos           un'altra cartella
  download_logos.py --input guide.gzip       usa una guida gia' scaricata
  download_logos.py --dry-run                elenca cosa scaricherebbe, senza scaricare

Solo libreria standard. Un logo troppo grande, non PNG o non raggiungibile viene saltato e segnalato.
"""
import argparse
import gzip
import os
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import film_stasera as fs  # noqa: E402  (stessa cartella: CHANNELS, ALIAS, slug, download)

MAX_LOGO = 300_000
PNG = b"\x89PNG\r\n\x1a\n"


def logo_urls(path):
    """canale mostrato -> indirizzo del logo, il primo che la guida da' per un nome esatto del canale."""
    urls = {}
    with gzip.open(path, "rb") as raw:
        for _, el in ET.iterparse(fs.LimitedReader(raw, fs.MAX_XML), events=("end",)):
            if el.tag == "channel":
                shown = fs.ALIAS.get(fs.norm(el.findtext("display-name")))
                icon = el.find("icon")
                if shown and shown not in urls and icon is not None and icon.get("src"):
                    urls[shown] = icon.get("src")
                el.clear()
            elif el.tag == "programme":
                break
    return urls


def fetch(url):
    if not url.startswith("https://"):
        raise RuntimeError("solo https")
    req = urllib.request.Request(url, headers={"User-Agent": "film-stasera/1.0 (uso personale)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_LOGO + 1)
    if len(data) > MAX_LOGO:
        raise RuntimeError(f"oltre {MAX_LOGO} byte")
    if not data.startswith(PNG):
        raise RuntimeError("non e' un PNG")
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=fs.LOGOS_DIR, help="cartella di destinazione")
    ap.add_argument("--input", help="usa questo guide.gzip invece di scaricarlo")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory(prefix="film_logos_") as tmp:
        path = args.input
        if not path:
            path = os.path.join(tmp, "guide.gzip")
            fs.download(fs.SOURCE_URL, path)
        urls = logo_urls(path)

    os.makedirs(args.dest, exist_ok=True) if not args.dry_run else None
    total, missing = 0, []
    for name in fs.CHANNELS:
        url = urls.get(name)
        if not url:
            missing.append(name)
            continue
        if args.dry_run:
            print(f"{name:<10} {url[:100]}")
            continue
        try:
            data = fetch(url)
        except Exception as e:  # un logo che manca non ferma gli altri
            print(f"{name:<10} SALTATO: {e}", file=sys.stderr)
            missing.append(name)
            continue
        with open(os.path.join(args.dest, fs.slug(name) + ".png"), "wb") as f:
            f.write(data)
        total += len(data)
        print(f"{name:<10} {fs.slug(name)}.png {len(data)} byte")
    print(f"-- {len(fs.CHANNELS) - len(missing)} loghi, {total} byte in totale; senza logo: {', '.join(missing) or 'nessuno'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
