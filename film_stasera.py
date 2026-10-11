#!/usr/bin/env python3
"""Film in TV stasera: scarica la guida XMLTV di EPGItalia e stampa un JSON con i film della prima serata.

Pensato per un sensore command_line di Home Assistant (e per il plugin Tessera che legge i suoi attributi):
  - stampa UNA riga di JSON su stdout, con liste parallele (titles, channels, starts, genres) invece di oggetti;
  - ricorda l'ultimo risultato buono in un file di cache: se il download fallisce (o il file e' anomalo) stampa quello,
    con "stale": true; se la cache e' fresca non riscarica nulla (serve all'avvio di HA);
  - tutti i messaggi vanno su stderr. Esce sempre con 0 tranne errori d'uso, cosi' il sensore non perde i dati.

Uso:
  film_stasera.py                         modalita' HA (cache accanto allo script)
  film_stasera.py --dry-run               elenco leggibile, non scrive la cache
  film_stasera.py --input guide.gzip ...  usa un file gia' scaricato (prove)
  film_stasera.py --date 2026-10-12       un altro giorno (default: oggi, ora di Roma)
  film_stasera.py --cache PERCORSO --max-age-hours 4

Solo libreria standard, nessun database dei fusi orari (l'ora legale e' calcolata qui).
Termini d'uso della fonte: uso personale e non commerciale (epgitalia.tv/condizioni-di-utilizzo).
"""
import argparse
import gzip
import json
import os
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

# Link ufficiale del sito: oggi riporta (301) a un file gzip su un altro server; lo seguiamo cosi' come fa il sito.
SOURCE_URL = "https://www.epgitalia.tv/gzip"
MAX_DOWNLOAD = 40_000_000     # byte compressi
MAX_XML = 400_000_000         # byte decompressi (il file di oggi e' ~100 MB)
TIMEOUT = 120
DEFAULT_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "film_stasera_cache.json")
DEFAULT_MAX_AGE_HOURS = 4.0

# Prima serata: i film che INIZIANO tra queste ore (ora di Roma) del giorno scelto.
FROM_HOUR, TO_HOUR = 20, 24
MAX_ITEMS = 20     # il tile riceve al massimo ~2,6 KB di dati; 20 film sono circa 1,3 KB
MAX_TITLE = 40
DUP_WINDOW = 900   # secondi: due voci uguali piu' vicine di cosi' sono la stessa

# Nome mostrato -> nomi come compaiono nel file (minuscolo, spazi singoli). Solo il canale base: niente HD/SD/+1/RAW.
CHANNELS = {
    "Rai 1": ["rai 1"],
    "Rai 2": ["rai 2"],
    "Rai 3": ["rai 3"],
    "Rete 4": ["rete 4"],
    "Canale 5": ["canale 5"],
    "Italia 1": ["italia 1"],
    "La7": ["la7"],
    "TV8": ["tv8"],
    "NOVE": ["nove"],
    "Iris": ["iris"],
    "Rai 4": ["rai 4"],
    "Rai Movie": ["rai movie"],
    "Cine34": ["cine34", "cine 34"],
    "Top Crime": ["top crime"],
    "Focus": ["focus"],
    "Discovery": ["discovery channel"],
    "Real Time": ["real time"],
    "DMAX": ["dmax"],
    "Italia 2": ["italia 2", "italia2"],
    "20": ["20 mediaset", "mediaset 20"],
}
ALIAS = {a: shown for shown, aliases in CHANNELS.items() for a in aliases}

# Un programma e' un film se ha una di queste categorie; i telefilm (episodi di serie) restano fuori.
FILM_CATEGORIES = {"film", "film animazione"}
# Categorie generiche che non dicono il genere: quando mostriamo il genere le saltiamo.
GENERIC = {"film", "film animazione", "cinema", "intrattenimento"}


# ---- Ora di Roma senza database dei fusi: UE, ora legale dall'ultima domenica di marzo alle 01:00 UTC
# ---- all'ultima domenica di ottobre alle 01:00 UTC. ----
def _last_sunday(year, month):
    d = date(year, month, 31)           # marzo e ottobre hanno 31 giorni
    return d - timedelta(days=(d.weekday() + 1) % 7)


def rome_offset(utc_dt):
    y = utc_dt.year
    s = datetime(y, 3, _last_sunday(y, 3).day, 1, tzinfo=timezone.utc)
    e = datetime(y, 10, _last_sunday(y, 10).day, 1, tzinfo=timezone.utc)
    return timedelta(hours=2) if s <= utc_dt < e else timedelta(hours=1)


def to_rome(dt):
    """Data/ora con fuso -> data/ora locale di Roma, senza fuso."""
    u = dt.astimezone(timezone.utc)
    return (u + rome_offset(u)).replace(tzinfo=None)


def today_rome():
    return to_rome(datetime.now(timezone.utc)).date()


def norm(name):
    return " ".join((name or "").lower().split())


def short(title):
    title = " ".join((title or "").split())
    return title[:MAX_TITLE].rstrip()   # il tile accorcia da solo con i puntini se manca lo spazio


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "film-stasera/1.0 (uso personale)"})
    size = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise RuntimeError(f"download oltre {MAX_DOWNLOAD} byte: interrotto")
            f.write(chunk)
    return size


class LimitedReader:
    """Legge un file e si ferma se i byte letti superano il tetto (difesa da file anomali o malevoli)."""

    def __init__(self, f, limit):
        self.f, self.limit, self.n = f, limit, 0

    def read(self, size=-1):
        data = self.f.read(size)
        self.n += len(data)
        if self.n > self.limit:
            raise RuntimeError(f"XML oltre {self.limit} byte: interrotto")
        return data


def parse_ts(ts):
    # formato XMLTV: 20261011205500 +0200
    return datetime.strptime(ts, "%Y%m%d%H%M%S %z")


def extract(path, day):
    """Ritorna (film, statistiche). film: lista di dict per il giorno 'day' (data di Roma)."""
    start_win = datetime(day.year, day.month, day.day, FROM_HOUR)
    end_win = datetime(day.year, day.month, day.day) + timedelta(hours=TO_HOUR)
    channels = {}   # id file -> nome mostrato (solo i canali che ci interessano)
    seen = {}       # nome mostrato -> voci grezze
    stats = {"channels_in_file": 0, "programmes": 0, "per_channel": {n: 0 for n in CHANNELS},
             "evening": {n: 0 for n in CHANNELS}}   # programmi di qualsiasi tipo nella fascia serale
    with gzip.open(path, "rb") as raw:
        for _, el in ET.iterparse(LimitedReader(raw, MAX_XML), events=("end",)):
            if el.tag == "channel":
                stats["channels_in_file"] += 1
                shown = ALIAS.get(norm(el.findtext("display-name")))
                if shown:
                    channels[el.get("id")] = shown
                el.clear()
            elif el.tag == "programme":
                stats["programmes"] += 1
                shown = channels.get(el.get("channel"))
                if shown:
                    start_aw = parse_ts(el.get("start"))
                    if start_win <= to_rome(start_aw) < end_win:
                        stats["evening"][shown] += 1
                        cats = [norm(c.text) for c in el.findall("category") if c.text]
                        if FILM_CATEGORIES.intersection(cats):
                            genre = next((c for c in cats if c not in GENERIC), "")
                            seen.setdefault(shown, []).append({
                                "title": short(el.findtext("title")),
                                "channel": shown,
                                "at": int(start_aw.timestamp()),
                                "genre": genre.capitalize(),
                            })
                el.clear()
    # Il file ripete lo stesso canale con id diversi e orari che differiscono di pochi secondi:
    # stesso canale + stesso titolo entro DUP_WINDOW secondi e' lo stesso film.
    films = []
    for shown, items in seen.items():
        last = {}
        for it in sorted(items, key=lambda x: x["at"]):
            prev = last.get(norm(it["title"]))
            if prev is not None and it["at"] - prev < DUP_WINDOW:
                continue
            last[norm(it["title"])] = it["at"]
            films.append(it)
            stats["per_channel"][shown] += 1
    films.sort(key=lambda x: (x["at"], x["channel"]))
    return films, stats


def build(day, films, stale=False, error=""):
    films = films[:MAX_ITEMS]
    out = {
        "date": day.isoformat(),
        "updated": int(time.time()),
        "stale": stale,
        "count": len(films),
        "titles": [f["title"] for f in films],
        "channels": [f["channel"] for f in films],
        "starts": [f["at"] for f in films],
        "genres": [f["genre"] for f in films],
    }
    if error:
        out["error"] = error[:120]
    return out


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        n = len(c["titles"])
        if not (isinstance(c["date"], str) and isinstance(c["updated"], (int, float))
                and len(c["channels"]) == n == len(c["starts"]) == len(c["genres"])):
            return None
        return c
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_atomic(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".film_stasera_", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def fetch_today(day, input_path):
    """Scarica (o legge il file dato), estrae e controlla. Solleva un'eccezione se qualcosa non torna."""
    with tempfile.TemporaryDirectory(prefix="film_stasera_") as tmp:
        path = input_path
        if not path:
            path = os.path.join(tmp, "guide.gzip")
            size = download(SOURCE_URL, path)
            print(f"scaricati {size} byte", file=sys.stderr)
        films, stats = extract(path, day)
    if stats["channels_in_file"] < 100 or stats["programmes"] < 10_000:
        raise RuntimeError(f"file anomalo ({stats['channels_in_file']} canali, {stats['programmes']} programmi)")
    print(f"{stats['channels_in_file']} canali, {stats['programmes']} programmi; film trovati: {len(films)}",
          file=sys.stderr)
    print("film per canale:", {n: c for n, c in stats["per_channel"].items() if c}, file=sys.stderr)
    no_film = [n for n, c in stats["per_channel"].items() if c == 0 and stats["evening"][n] > 0]
    no_data = [n for n, c in stats["evening"].items() if c == 0]
    if no_film:
        print("canali senza film in serata:", ", ".join(no_film), file=sys.stderr)
    if no_data:
        print("ATTENZIONE, nessun programma in serata per:", ", ".join(no_data), file=sys.stderr)
    return films


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="file con l'ultimo risultato buono")
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                    help="se la cache di oggi e' piu' recente di cosi' non riscarica (0 = riscarica sempre)")
    ap.add_argument("--input", help="usa questo guide.gzip invece di scaricarlo")
    ap.add_argument("--date", help="giorno AAAA-MM-GG (default: oggi a Roma)")
    ap.add_argument("--dry-run", action="store_true", help="elenco leggibile, non scrive la cache")
    args = ap.parse_args()

    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else today_rome()
    cache = load_cache(args.cache)
    out = None

    fresh = (cache and cache["date"] == day.isoformat() and not cache.get("stale")
             and args.max_age_hours > 0 and not args.input
             and time.time() - cache["updated"] < args.max_age_hours * 3600)
    if fresh:
        print("cache fresca: nessun download", file=sys.stderr)
        out = cache
    else:
        try:
            out = build(day, fetch_today(day, args.input))
            if not args.dry_run:
                write_atomic(args.cache, json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:  # rete, file strano, disco: qualunque cosa, non perdere i dati buoni
            print(f"ERRORE: {e}", file=sys.stderr)
            if cache:
                out = dict(cache, stale=True, error=str(e)[:120])   # tiene la data originale: il tile sa che e' vecchio
            else:
                out = build(day, [], stale=True, error=str(e))

    if args.dry_run:
        for t, c, s, g in zip(out["titles"], out["channels"], out["starts"], out["genres"]):
            local = to_rome(datetime.fromtimestamp(s, timezone.utc))
            print(f"{local:%H:%M} {c:<10} {t} {('| ' + g) if g else ''}")
        print(f"-- {out['count']} film, data {out['date']}, stale={out['stale']}", file=sys.stderr)
    else:
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
