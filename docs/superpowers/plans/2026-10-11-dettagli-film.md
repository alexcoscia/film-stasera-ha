# Dettagli film (TMDB) e loghi in riga: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nella dashboard `/film-stasera` ogni film ha orario, logo e titolo in riga; un clic apre un popup con locandina, trama e cast presi da TMDB in italiano.

**Architecture:** `film_stasera.py` arricchisce il JSON del sensore con cinque liste parallele (`tmdb_ids`, `posters`, `overviews`, `casts`, `years`) usando una cache propria per film. La dashboard è generata da `make_dashboard.py`: 20 `custom:button-card` (template `film_row`) con popup `browser_mod` che rilegge il sensore con un modello Jinja.

**Tech Stack:** Python 3 (solo libreria standard, `unittest`), Home Assistant (command_line, dashboard), button-card 8+ (HACS), browser_mod 3.3.0.

**Spec:** `docs/superpowers/specs/2026-10-11-dettagli-film-design.md`

## Global Constraints

- Solo libreria standard Python, nessun pacchetto da installare (come oggi).
- La chiave TMDB sta solo in `/config/film_stasera/tmdb.key` (una riga); mai nel repository, mai stampata su stdout/stderr, mai in chat. `tmdb.key` va in `.gitignore`.
- Lo script esce sempre con 0 e non perde mai i dati della guida per colpa di TMDB.
- Attributi del sensore sotto i 16 KB (limite di HA per il database): lo script li tiene sotto 15.500 byte di JSON.
- Dicitura obbligatoria nel popup: "This product uses the TMDB API but is not endorsed or certified by TMDB."
- Locandine: `https://image.tmdb.org/t/p/w342/...` (link, niente file scaricati). I loghi dei canali restano fuori dal repository.
- Il tile Tessera e `~/tessera-film-stasera` non si toccano.
- Messaggi, commenti e README in italiano. Commit con la riga `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Niente `git push` senza conferma dell'utente.

## Review Focus

- Titolo che non è un film su TMDB (es. "Stag. 2026 - Sul cammino di Francesco -"): nessun dettaglio, mai quello di un altro film (Task 1, test `test_nessuna_corrispondenza_sicura`).
- Titolo con anno tra parentesi ("Non siamo soli (2022)"): si cerca con l'anno e senza parentesi (Task 1, `test_anno_tra_parentesi`).
- TMDB giù, lento o chiave sbagliata: la guida esce comunque, e un errore non si ricorda come "film non trovato" (Task 1, `test_errore_di_rete_non_si_ricorda`, `test_budget_di_tempo`).
- File della chiave assente o vuoto: stesso risultato di oggi, con le liste nuove vuote ma della lunghezza giusta (Task 2, `test_senza_chiave`).
- Titolo o trama con `<`, `&`, `"` (la guida è un dato non fidato) e attributi troppo grandi: il testo è sempre escluso da HTML eseguibile e il JSON resta sotto 15.500 byte (Task 1 `test_taglia_per_stare_nei_limiti`, Task 3 `test_html_escape`).

---

## File Structure

- Modify: `film_stasera.py` — client TMDB, cache dei dettagli, `enrich()`, opzioni `--tmdb-key-file` e `--tmdb-cache`.
- Create: `tests/test_tmdb.py` — test dello script con TMDB simulato (nessuna rete).
- Create: `make_dashboard.py` — genera `dashboard.json` (template button-card + 20 righe).
- Create: `tests/test_dashboard.py` — test del generatore.
- Create: `dashboard.json` — risultato del generatore (si incolla nella dashboard).
- Modify: `film_stasera.yaml` — `json_attributes` con i cinque attributi nuovi.
- Modify: `.gitignore` — `tmdb.key`, `film_stasera_tmdb.json`.
- Modify: `README.md`, `docs/superpowers/specs/2026-10-11-dettagli-film-design.md` (trama: 600 al massimo, più corta se serve).
- Retire: `dashboard_card.yaml` (la scheda Markdown) resta come alternativa semplice senza popup; il README la cita.

---

### Task 1: Client TMDB, cache e arricchimento

**Files:**
- Modify: `film_stasera.py` (import, costanti dopo `DEFAULT_MAX_AGE_HOURS`, funzioni nuove prima di `main`)
- Create: `tests/test_tmdb.py`

**Interfaces:**
- Produces (usate da Task 2):
  - `read_key(path: str) -> str`
  - `tmdb_get(path: str, key: str, params: dict, timeout: int = TMDB_TIMEOUT) -> dict`
  - `split_title(title: str) -> tuple[str, int]`
  - `norm_title(s: str) -> str`, `key_of(title: str) -> str`
  - `lookup(title: str, key: str, get=tmdb_get) -> dict` con chiavi `id, poster, overview, cast, year` (`{"id": 0}` se non c'è corrispondenza sicura)
  - `enrich(out: dict, key: str, cache_path: str, get=tmdb_get, clock=time.time, write=True) -> dict` ritorna una copia di `out` con `tmdb_ids, posters, overviews, casts, years` (liste lunghe come `titles`)
  - `fit_size(out: dict, limit: int = MAX_JSON) -> dict`

- [ ] **Step 1: Scrivi i test (falliscono)**

Crea `tests/test_tmdb.py`:

```python
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import film_stasera as fs  # noqa: E402


class FakeTmdb:
    """Finto TMDB: search per titolo cercato, movie per id. Registra le chiamate."""

    def __init__(self, search=None, movies=None, fail=None):
        self.search, self.movies, self.fail = search or {}, movies or {}, fail
        self.calls = []

    def __call__(self, path, key, params, timeout=10):
        self.calls.append((path, dict(params)))
        if self.fail:
            raise self.fail
        if path == "search/movie":
            return {"results": self.search.get(params["query"], [])}
        return self.movies[int(path.split("/")[1])]


JOB = {"results": [{"id": 1, "title": "The Italian Job", "original_title": "The Italian Job"}]}
JOB_MOVIE = {"id": 1, "overview": "Una   rapina\na Venezia.", "poster_path": "/p.jpg", "release_date": "2003-05-30",
             "credits": {"cast": [{"name": f"Attore {i}"} for i in range(10)]}}


def out_of(*titles):
    n = len(titles)
    return {"date": "2026-10-11", "updated": 1, "stale": False, "count": n, "titles": list(titles),
            "channels": ["Iris"] * n, "starts": [1791745200] * n, "genres": [""] * n, "groups": [2] * n,
            "logos": [""] * n}


class LookupTest(unittest.TestCase):
    def test_trova_il_film(self):
        d = fs.lookup("The Italian Job", "k", FakeTmdb({"The Italian Job": JOB["results"]}, {1: JOB_MOVIE}))
        self.assertEqual(d["id"], 1)
        self.assertEqual(d["poster"], "https://image.tmdb.org/t/p/w342/p.jpg")
        self.assertEqual(d["overview"], "Una rapina a Venezia.")
        self.assertEqual(d["cast"], "Attore 0, Attore 1, Attore 2, Attore 3, Attore 4, Attore 5")
        self.assertEqual(d["year"], "2003")

    def test_nessuna_corrispondenza_sicura(self):
        wrong = [{"id": 9, "title": "Francesco", "original_title": "Francesco"}]
        fake = FakeTmdb({"Stag. 2026 - Sul cammino di Francesco -": wrong})
        self.assertEqual(fs.lookup("Stag. 2026 - Sul cammino di Francesco -", "k", fake), {"id": 0})
        self.assertEqual(len(fake.calls), 1)   # nessuna richiesta di dettaglio per un film sbagliato

    def test_anno_tra_parentesi(self):
        fake = FakeTmdb({"Non siamo soli": [{"id": 1, "title": "Non siamo soli", "original_title": "x"}]}, {1: JOB_MOVIE})
        fs.lookup("Non siamo soli (2022)", "k", fake)
        self.assertEqual(fake.calls[0][1]["query"], "Non siamo soli")
        self.assertEqual(fake.calls[0][1]["year"], 2022)

    def test_senza_poster_e_trama_lunga(self):
        movie = dict(JOB_MOVIE, poster_path=None, overview="parola " * 200)
        d = fs.lookup("The Italian Job", "k", FakeTmdb({"The Italian Job": JOB["results"]}, {1: movie}))
        self.assertEqual(d["poster"], "")
        self.assertLessEqual(len(d["overview"]), fs.MAX_OVERVIEW)
        self.assertTrue(d["overview"].endswith("…"))

    def test_split_title(self):
        self.assertEqual(fs.split_title("Non siamo soli (2022)"), ("Non siamo soli", 2022))
        self.assertEqual(fs.split_title("La giuria"), ("La giuria", 0))


class TmdbGetTest(unittest.TestCase):
    def _headers_and_url(self, key):
        seen = {}

        class R:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def read(s, n=-1): return b"{}"

        def fake_urlopen(req, timeout=0):
            seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
            return R()

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            fs.tmdb_get("search/movie", key, {"query": "x"})
        return seen

    def test_chiave_v3_nel_parametro(self):
        s = self._headers_and_url("abc123")
        self.assertIn("api_key=abc123", s["url"])
        self.assertNotIn("Authorization", s["headers"])

    def test_token_v4_nell_intestazione(self):
        s = self._headers_and_url("eyJabc")
        self.assertNotIn("api_key", s["url"])
        self.assertEqual(s["headers"]["Authorization"], "Bearer eyJabc")


class EnrichTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "tmdb.json")
        self.fake = FakeTmdb({"The Italian Job": JOB["results"]}, {1: JOB_MOVIE})
        self.now = 1_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def clock(self):
        return self.now

    def test_liste_parallele(self):
        out = fs.enrich(out_of("The Italian Job", "Boh"), "k", self.cache, self.fake, self.clock)
        self.assertEqual(out["tmdb_ids"], [1, 0])
        self.assertEqual(out["years"], ["2003", ""])
        self.assertEqual(out["posters"][1], "")
        for name in ("tmdb_ids", "posters", "overviews", "casts", "years"):
            self.assertEqual(len(out[name]), 2)

    def test_la_cache_evita_le_richieste(self):
        fs.enrich(out_of("The Italian Job"), "k", self.cache, self.fake, self.clock)
        n = len(self.fake.calls)
        out = fs.enrich(out_of("The Italian Job"), "k", self.cache, self.fake, self.clock)
        self.assertEqual(len(self.fake.calls), n)
        self.assertEqual(out["tmdb_ids"], [1])

    def test_il_mancato_si_riprova_dopo_sette_giorni(self):
        fs.enrich(out_of("Boh"), "k", self.cache, self.fake, self.clock)
        n = len(self.fake.calls)
        self.now += 6 * 86400
        fs.enrich(out_of("Boh"), "k", self.cache, self.fake, self.clock)
        self.assertEqual(len(self.fake.calls), n)
        self.now += 2 * 86400
        fs.enrich(out_of("Boh"), "k", self.cache, self.fake, self.clock)
        self.assertGreater(len(self.fake.calls), n)

    def test_errore_di_rete_non_si_ricorda(self):
        down = FakeTmdb(fail=OSError("giu'"))
        out = fs.enrich(out_of("The Italian Job"), "k", self.cache, down, self.clock)
        self.assertEqual(out["tmdb_ids"], [0])
        out = fs.enrich(out_of("The Italian Job"), "k", self.cache, self.fake, self.clock)
        self.assertEqual(out["tmdb_ids"], [1])   # al giro dopo riprova subito

    def test_budget_di_tempo(self):
        ticks = iter(range(0, 10_000, 40))   # ogni lettura dell'orologio passano 40 s
        titles = [f"Film {i}" for i in range(10)]
        fake = FakeTmdb()
        fs.enrich(out_of(*titles), "k", self.cache, fake, lambda: next(ticks))
        self.assertLess(len(fake.calls), 10)

    def test_senza_chiave(self):
        out = fs.enrich(out_of("The Italian Job", "Boh"), "", self.cache, self.fake, self.clock)
        self.assertEqual(out["tmdb_ids"], [0, 0])
        self.assertEqual(self.fake.calls, [])

    def test_voci_non_viste_da_un_mese_si_tolgono(self):
        fs.enrich(out_of("The Italian Job"), "k", self.cache, self.fake, self.clock)
        self.now += 31 * 86400
        fs.enrich(out_of("Altro film"), "k", self.cache, self.fake, self.clock)
        with open(self.cache, encoding="utf-8") as f:
            self.assertNotIn(fs.key_of("The Italian Job"), json.load(f))

    def test_taglia_per_stare_nei_limiti(self):
        out = out_of(*[f"Film numero {i}" for i in range(20)])
        for name, val in (("tmdb_ids", 1), ("posters", "https://image.tmdb.org/t/p/w342/" + "a" * 30 + ".jpg"),
                          ("overviews", "x" * fs.MAX_OVERVIEW), ("casts", "Nome Cognome, " * 6), ("years", "2003")):
            out[name] = [val] * 20
        fitted = fs.fit_size(out)
        self.assertLess(len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":"))), fs.MAX_JSON)
        self.assertEqual(len(fitted["overviews"]), 20)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verifica che falliscano**

Run: `cd ~/film-stasera && python3 -I tests/test_tmdb.py 2>&1 | tail -5`
Expected: errore `AttributeError: module 'film_stasera' has no attribute 'lookup'` (o simile).

- [ ] **Step 3: Implementa**

In `film_stasera.py`, aggiungi agli import `import re` e `import urllib.parse`. Dopo la riga `DEFAULT_MAX_AGE_HOURS = 4.0` aggiungi:

```python
HERE = os.path.dirname(os.path.abspath(__file__))
# TMDB (themoviedb.org): locandina, trama e cast in italiano. Chiave in un file accanto allo script, mai nel repository.
TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
DEFAULT_TMDB_KEY = os.path.join(HERE, "tmdb.key")
DEFAULT_TMDB_CACHE = os.path.join(HERE, "film_stasera_tmdb.json")
TMDB_TIMEOUT = 10         # secondi per richiesta
TMDB_BUDGET = 60          # secondi in tutto per le ricerche di un'esecuzione (il sensore ha 240 s)
TMDB_MISS_DAYS = 7        # un film non trovato si riprova dopo una settimana
TMDB_KEEP_DAYS = 30       # voci non viste da un mese si tolgono dalla cache
MAX_OVERVIEW = 600
MAX_CAST = 6
MAX_JSON = 15500          # HA salva nel database gli attributi solo sotto i 16 KB
```

Prima di `def main():` aggiungi:

```python
def read_key(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def tmdb_get(path, key, params, timeout=TMDB_TIMEOUT):
    """GET su TMDB. La chiave v3 va nel parametro, il token v4 (inizia per eyJ) nell'intestazione. Non stampa mai l'URL."""
    q = dict(params)
    headers = {"User-Agent": "film-stasera/1.0 (uso personale)", "Accept": "application/json"}
    if key.startswith("eyJ"):
        headers["Authorization"] = "Bearer " + key
    else:
        q["api_key"] = key
    req = urllib.request.Request(f"{TMDB_API}/{path}?{urllib.parse.urlencode(q)}", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(2_000_000).decode("utf-8"))


def split_title(title):
    """'Non siamo soli (2022)' -> ('Non siamo soli', 2022); senza anno -> (titolo, 0)."""
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", title or "")
    return (m.group(1), int(m.group(2))) if m else ((title or "").strip(), 0)


def norm_title(s):
    return " ".join("".join(c if c.isalnum() else " " for c in (s or "").lower()).split())


def key_of(title):
    name, year = split_title(title)
    return f"{norm_title(name)}|{year or ''}"


def lookup(title, key, get=tmdb_get):
    """Cerca il film su TMDB. Prende un risultato solo se il titolo coincide (ignorando punteggiatura e maiuscole) con il
    titolo italiano o originale: meglio nessun dettaglio che quello di un altro film. {"id": 0} se non c'e'.
    Solleva l'errore di rete: chi chiama decide cosa ricordare."""
    name, year = split_title(title)
    params = {"query": name, "language": "it-IT", "include_adult": "false"}
    if year:
        params["year"] = year
    results = get("search/movie", key, params).get("results", [])[:5]
    want = norm_title(name)
    hit = next((r for r in results if want in (norm_title(r.get("title")), norm_title(r.get("original_title")))), None)
    if not hit:
        return {"id": 0}
    d = get(f"movie/{hit['id']}", key, {"language": "it-IT", "append_to_response": "credits"})
    cast = [p["name"] for p in (d.get("credits") or {}).get("cast", [])[:MAX_CAST] if p.get("name")]
    text = " ".join((d.get("overview") or "").split())
    if len(text) > MAX_OVERVIEW:
        text = text[:MAX_OVERVIEW - 1].rstrip() + "…"
    poster = d.get("poster_path") or ""
    return {"id": int(d["id"]), "poster": TMDB_IMG + poster if poster else "", "overview": text,
            "cast": ", ".join(cast), "year": (d.get("release_date") or "")[:4]}


def load_dict(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def fit_size(out, limit=MAX_JSON):
    """Accorcia le trame (le piu' lunghe per prime) finche' il JSON sta sotto il limite."""
    out = dict(out, overviews=list(out["overviews"]))
    while len(json.dumps(out, ensure_ascii=False, separators=(",", ":"))) > limit:
        i = max(range(len(out["overviews"])), key=lambda j: len(out["overviews"][j]), default=None)
        if i is None or len(out["overviews"][i]) <= 1:
            break
        out["overviews"][i] = out["overviews"][i][:max(1, len(out["overviews"][i]) - 50)].rstrip()
    return out


def enrich(out, key, cache_path, get=tmdb_get, clock=time.time, write=True):
    """Aggiunge a `out` le liste tmdb_ids, posters, overviews, casts, years (una voce per film). Non solleva mai:
    senza chiave, in caso di errori o finito il tempo a disposizione, i film senza dettaglio hanno id 0 e testi vuoti."""
    empty = {"id": 0, "poster": "", "overview": "", "cast": "", "year": ""}
    cache = load_dict(cache_path)
    started = clock()
    details = []
    for title in out["titles"]:
        k = key_of(title)
        hit = cache.get(k)
        known = isinstance(hit, dict) and (hit.get("id") or clock() - hit.get("checked", 0) < TMDB_MISS_DAYS * 86400)
        if not known and key and clock() - started < TMDB_BUDGET:
            try:
                hit = dict(lookup(title, key, get), checked=int(clock()))
                cache[k] = hit
            except Exception as e:   # rete, chiave, risposta strana: si riprova al prossimo giro
                print(f"TMDB: {title[:30]}: {type(e).__name__}", file=sys.stderr)
        if isinstance(hit, dict):
            hit["seen"] = int(clock())
        details.append(hit if isinstance(hit, dict) and hit.get("id") else empty)
    if write and key:
        limit = clock() - TMDB_KEEP_DAYS * 86400
        cache = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("seen", 0) >= limit}
        try:
            write_atomic(cache_path, json.dumps(cache, ensure_ascii=False, separators=(",", ":")))
        except OSError as e:
            print(f"TMDB: cache non scritta: {e}", file=sys.stderr)
    res = dict(out,
               tmdb_ids=[d["id"] for d in details], posters=[d["poster"] for d in details],
               overviews=[d["overview"] for d in details], casts=[d["cast"] for d in details],
               years=[d["year"] for d in details])
    return fit_size(res)
```

- [ ] **Step 4: Verifica che passino**

Run: `cd ~/film-stasera && python3 -I tests/test_tmdb.py -v 2>&1 | tail -25`
Expected: tutti i test `ok`, `OK` in fondo. Se `test_budget_di_tempo` o `test_voci_non_viste...` falliscono, correggi `enrich` (non i test): l'orologio finto è l'unica fonte di tempo.

- [ ] **Step 5: Commit**

```bash
cd ~/film-stasera && git add film_stasera.py tests/test_tmdb.py && git commit -m "Dettagli dei film da TMDB: ricerca, cache e arricchimento

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Collegare l'arricchimento allo script, al package e al repo

**Files:**
- Modify: `film_stasera.py` (`main`), `film_stasera.yaml:12`, `.gitignore`
- Modify: `tests/test_tmdb.py` (aggiungi la classe `CliTest`)

**Interfaces:**
- Consumes: `read_key`, `enrich`, `DEFAULT_TMDB_KEY`, `DEFAULT_TMDB_CACHE` (Task 1).
- Produces: opzioni `--tmdb-key-file`, `--tmdb-cache`; stdout con le cinque liste nuove.

- [ ] **Step 1: Test dello script da riga di comando (fallisce)**

Aggiungi in fondo a `tests/test_tmdb.py`, prima di `if __name__`:

```python
class CliTest(unittest.TestCase):
    def test_senza_chiave(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "c.json")
            with open(cache, "w", encoding="utf-8") as f:
                import time as _t
                json.dump(dict(out_of("La giuria", "Boh"), updated=int(_t.time())), f)
            r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(fs.__file__), "film_stasera.py"),
                                "--date", "2026-10-11", "--cache", cache, "--logos-dir", tmp,
                                "--tmdb-key-file", os.path.join(tmp, "manca.key"),
                                "--tmdb-cache", os.path.join(tmp, "t.json")],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tmdb_ids"], [0, 0])
        self.assertEqual(out["titles"], ["La giuria", "Boh"])
```

Run: `cd ~/film-stasera && python3 -I tests/test_tmdb.py CliTest 2>&1 | tail -5`
Expected: FAIL (`unrecognized arguments: --tmdb-key-file`).

- [ ] **Step 2: Implementa in `main`**

Nei `ap.add_argument` aggiungi:

```python
    ap.add_argument("--tmdb-key-file", default=DEFAULT_TMDB_KEY, help="file con la chiave TMDB (una riga)")
    ap.add_argument("--tmdb-cache", default=DEFAULT_TMDB_CACHE, help="cache dei dettagli dei film")
```

Subito prima del blocco `if args.dry_run:` finale aggiungi:

```python
    try:
        out = enrich(out, read_key(args.tmdb_key_file), args.tmdb_cache, write=not args.dry_run)
    except Exception as e:   # mai perdere la guida per colpa dei dettagli
        print(f"TMDB: saltato ({type(e).__name__})", file=sys.stderr)
```

Nel ramo `--dry-run`, sostituisci la riga `print(f"{local:%H:%M} ...")` con un ciclo che stampa anche l'anno quando c'è: usa `zip(out["titles"], out["channels"], out["starts"], out["genres"], out.get("years", [""] * out["count"]))` e aggiungi `{('(' + y + ') ') if y else ''}` prima del titolo. (Il parametro `y` è il quinto elemento del `zip`.)

In `film_stasera.yaml` riga 12 sostituisci con:

```yaml
      json_attributes: [date, updated, stale, titles, channels, starts, genres, groups, logos, tmdb_ids, posters, overviews, casts, years, error]
```

In `.gitignore` aggiungi le righe `tmdb.key` e `film_stasera_tmdb.json`.

- [ ] **Step 3: Verifica**

Run: `cd ~/film-stasera && python3 -I tests/test_tmdb.py 2>&1 | tail -4`
Expected: `OK` con tutti i test.
Run: `git status --short` — non deve comparire alcun file `tmdb.key`.

- [ ] **Step 4: Commit**

```bash
cd ~/film-stasera && git add film_stasera.py film_stasera.yaml .gitignore tests/test_tmdb.py && git commit -m "Script: attributi TMDB nel sensore, opzioni per chiave e cache

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Generatore della dashboard (righe button-card e popup)

**Files:**
- Create: `make_dashboard.py`, `tests/test_dashboard.py`, `dashboard.json` (generato)

**Interfaces:**
- Consumes: attributi del sensore `titles, channels, starts, genres, logos, posters, overviews, casts, years` e `sensor.film_stasera`.
- Produces: `build_config(slots: int = 20) -> dict` con le chiavi `button_card_templates` (un template `film_row`) e `cards` (lista di `slots` schede `custom:button-card`, la i-esima con `variables: {i: i}` e popup con il modello Jinja dell'i-esimo film non ancora finito).

- [ ] **Step 1: Scrivi i test (falliscono)**

Crea `tests/test_dashboard.py`:

```python
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import make_dashboard as md  # noqa: E402


class DashboardTest(unittest.TestCase):
    def setUp(self):
        self.cfg = md.build_config(20)

    def test_venti_righe(self):
        self.assertEqual(len(self.cfg["cards"]), 20)
        for i, c in enumerate(self.cfg["cards"]):
            self.assertEqual(c["type"], "custom:button-card")
            self.assertEqual(c["template"], "film_row")
            self.assertEqual(c["variables"], {"i": i})

    def test_popup_con_indice_letterale(self):
        for i, c in enumerate(self.cfg["cards"]):
            tap = c["tap_action"]
            self.assertEqual(tap["action"], "fire-dom-event")
            self.assertEqual(tap["browser_mod"]["service"], "browser_mod.popup")
            self.assertIn(f"ns.n == {i} ", tap["browser_mod"]["data"]["content"]["content"])

    def test_dicitura_tmdb(self):
        text = self.cfg["cards"][0]["tap_action"]["browser_mod"]["data"]["content"]["content"]
        self.assertIn("This product uses the TMDB API but is not endorsed or certified by TMDB.", text)

    def test_ordine_orario_logo_titolo(self):
        t = self.cfg["button_card_templates"]["film_row"]
        self.assertIn('"t l n"', t["styles"]["grid"][0]["grid-template-areas"])
        self.assertEqual(set(t["custom_fields"]), {"t", "l", "n"})

    def test_html_escape(self):
        # La guida e' un dato non fidato: ogni testo che finisce in innerHTML passa da esc().
        t = self.cfg["button_card_templates"]["film_row"]
        self.assertIn("esc(", t["custom_fields"]["n"])
        self.assertIn("esc(", t["custom_fields"]["l"])
        self.assertNotIn("${a.titles[k]}", json.dumps(t))   # mai il titolo grezzo

    def test_json_valido(self):
        json.loads(json.dumps(self.cfg))


if __name__ == "__main__":
    unittest.main()
```

Run: `cd ~/film-stasera && python3 -I tests/test_dashboard.py 2>&1 | tail -3`
Expected: `ModuleNotFoundError: No module named 'make_dashboard'`.

- [ ] **Step 2: Implementa `make_dashboard.py`**

```python
#!/usr/bin/env python3
"""Genera dashboard.json: 20 righe button-card (orario, logo, titolo) per i film di sensor.film_stasera, ognuna con un
popup browser_mod (locandina, trama, cast). Uso: make_dashboard.py > dashboard.json"""
import json
import sys

SENSOR = "sensor.film_stasera"
ONAIR_SECONDS = 9000   # un film iniziato da piu' di due ore e mezza sparisce (come nel tile)

# JS comune ai tre campi: k = indice del film mostrato da questa riga (l'i-esimo non ancora finito), '' se non c'e'.
JS_HEAD = (
    "const a = entity.attributes; const now = Date.now() / 1000; "
    "const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g, (c) => "
    "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'}[c])); "
    f"const ks = (a.titles || []).map((_, j) => j).filter((j) => a.starts[j] + {ONAIR_SECONDS} >= now); "
    "const k = ks[variables.i]; if (k === undefined) return ''; "
)

TMDB_CREDIT = "This product uses the TMDB API but is not endorsed or certified by TMDB."


def popup_template(i):
    """Modello Jinja del markdown nel popup: l'i-esimo film non ancora finito, con i dettagli che ci sono."""
    return (
        "{%- set a = states.sensor.film_stasera.attributes -%}\n"
        "{%- set ora = now().timestamp() -%}\n"
        "{%- set ns = namespace(k=-1, n=0) -%}\n"
        f"{{%- for j in range(a.titles | length) if a.starts[j] + {ONAIR_SECONDS} >= ora -%}}\n"
        f"{{%- if ns.n == {i} %}}{{% set ns.k = j %}}{{% endif -%}}\n"
        "{%- set ns.n = ns.n + 1 -%}\n"
        "{%- endfor -%}\n"
        "{%- set k = ns.k -%}\n"
        "{%- set P = a.posters | default([]) -%}{%- set O = a.overviews | default([]) -%}\n"
        "{%- set C = a.casts | default([]) -%}{%- set Y = a.years | default([]) -%}\n"
        "{%- if k >= 0 -%}\n"
        "{% if P | length > k and P[k] %}<img src=\"{{ P[k] }}\" width=\"150\" "
        "style=\"float:left;margin:0 16px 8px 0;border-radius:8px\">{% endif %}\n"
        "**{{ a.titles[k] }}**{% if Y | length > k and Y[k] %} ({{ Y[k] }}){% endif %}\n\n"
        "{{ a.channels[k] }} · {{ a.starts[k] | timestamp_custom('%H:%M') }}"
        "{% if a.genres[k] %} · {{ a.genres[k] }}{% endif %}\n\n"
        "{% if O | length > k and O[k] %}{{ O[k] }}{% else %}Nessuna trama disponibile.{% endif %}\n\n"
        "{% if C | length > k and C[k] %}**Cast:** {{ C[k] }}{% endif %}\n\n"
        f"<br style=\"clear:both\"><small>{TMDB_CREDIT}</small>\n"
        "{%- else -%}\nFilm non piu' in programma.\n{%- endif -%}"
    )


def film_row_template():
    return {
        "show_icon": False, "show_name": False, "show_state": False,
        "styles": {
            "card": [{"padding": "6px 12px"},
                     {"display": "[[[ " + JS_HEAD.replace("return ''", "return 'none'") + "return 'block'; ]]]"}],
            "grid": [{"grid-template-areas": '"t l n"'}, {"grid-template-columns": "52px 96px 1fr"},
                     {"align-items": "center"}, {"column-gap": "12px"}],
            "custom_fields": {
                "t": [{"font-weight": "bold"}],
                "l": [{"justify-self": "start"}],
                "n": [{"text-align": "left"}, {"overflow": "hidden"}],
            },
        },
        "custom_fields": {
            "t": "[[[ " + JS_HEAD + "return new Date(a.starts[k] * 1000).toLocaleTimeString('it-IT', "
                 "{hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome'}); ]]]",
            "l": "[[[ " + JS_HEAD + "const logo = (a.logos || [])[k]; "
                 "if (logo) return '<img src=\"' + esc(logo) + '\" height=\"30\" "
                 "style=\"background:#fff;border-radius:6px;padding:2px 8px\">'; "
                 "return '<span>' + esc(a.channels[k]) + '</span>'; ]]]",
            "n": "[[[ " + JS_HEAD + "const sub = [a.channels[k], a.genres[k]].filter(Boolean).map(esc).join(' · '); "
                 "return '<b>' + esc(a.titles[k]) + '</b><br><small>' + sub + '</small>'; ]]]",
        },
    }


def build_config(slots=20):
    cards = []
    for i in range(slots):
        cards.append({
            "type": "custom:button-card",
            "template": "film_row",
            "entity": SENSOR,
            "variables": {"i": i},
            "tap_action": {
                "action": "fire-dom-event",
                "browser_mod": {
                    "service": "browser_mod.popup",
                    "data": {"dismissable": True, "content": {"type": "markdown", "content": popup_template(i)}},
                },
            },
        })
    return {"button_card_templates": {"film_row": film_row_template()}, "cards": cards}


if __name__ == "__main__":
    json.dump(build_config(), sys.stdout, ensure_ascii=False, indent=1)
    print()
```

- [ ] **Step 3: Verifica e genera**

Run: `cd ~/film-stasera && python3 -I tests/test_dashboard.py -v 2>&1 | tail -12`
Expected: 6 test `ok`.
Run: `python3 -I make_dashboard.py > dashboard.json && python3 -I -c "import json;d=json.load(open('dashboard.json'));print(len(d['cards']), len(open('dashboard.json').read()))"`
Expected: `20` e una dimensione di qualche decina di KB (se supera 200 KB, spostare il Jinja in un template condiviso e dirlo all'utente).

- [ ] **Step 4: Commit**

```bash
cd ~/film-stasera && git add make_dashboard.py dashboard.json tests/test_dashboard.py && git commit -m "Dashboard: righe button-card con logo tra orario e titolo e popup del film

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Installare in HA, provare nel browser, documentare

**Files:**
- Modify: `README.md`, `docs/superpowers/specs/2026-10-11-dettagli-film-design.md`
- Deploy: `~/mnt_hass/homeassistant/film_stasera/film_stasera.py`, `~/mnt_hass/homeassistant/packages/film_stasera.yaml`, dashboard `film-stasera`

**Interfaces:**
- Consumes: tutto il resto; il file `/config/film_stasera/tmdb.key` messo dall'utente (una riga, solo la chiave).

- [ ] **Step 1: Copia in HA e ricarica**

```bash
cp ~/film-stasera/film_stasera.py ~/mnt_hass/homeassistant/film_stasera/film_stasera.py
cp ~/film-stasera/film_stasera.yaml ~/mnt_hass/homeassistant/packages/film_stasera.yaml
diff ~/film-stasera/film_stasera.py ~/mnt_hass/homeassistant/film_stasera/film_stasera.py && echo identici
ls ~/mnt_hass/homeassistant/film_stasera/
```

Poi `ha_reload_core` per `command_line` (domain `command_line`).
Se `tmdb.key` non c'è ancora nell'elenco, chiedi all'utente di crearlo (senza incollare la chiave in chat) e aspetta.

- [ ] **Step 2: Aggiorna il sensore e controlla gli attributi**

Chiama `homeassistant.update_entity` su `sensor.film_stasera` (con `ha_call_service`). Attendi ~60 s e leggi `ha_get_state`.
Expected: `tmdb_ids`, `posters`, `overviews`, `casts`, `years` presenti, lunghi come `titles`; la maggioranza dei film con `tmdb_ids` > 0. Controlla anche che "Stag. 2026 - Sul cammino di Francesco -" abbia id 0 (non è un film) e che la dimensione degli attributi sia sotto i 15.500 byte: `ha_eval_template` con `{{ states.sensor.film_stasera.attributes | tojson | length }}`.

- [ ] **Step 3: Dashboard**

Prima leggi la guida (`ha_get_skill_guide`, riferimento `dashboard-guide`) e prendi la `BestPracticeKey` come richiesto dalla policy; poi `ha_config_get_dashboard` su `film-stasera` per vedere la struttura attuale. Sostituisci la scheda Markdown con le 20 schede di `dashboard.json` (`cards`, dentro una `vertical-stack` o nella sezione esistente) e aggiungi il blocco `button_card_templates` alla radice della configurazione. Salva con `ha_config_set_dashboard`. Backup: copia prima la configurazione attuale in `~/film-stasera/backup-dashboard.json` (fuori da git, aggiungilo a `.gitignore`).

- [ ] **Step 4: Prova nel browser (Chrome)**

Carica gli strumenti Chrome con `ToolSearch`, apri una scheda nuova su `http://192.168.0.133:8123/film-stasera/stasera` (l'utente deve essere già collegato), Ctrl+Shift+R. Controlla:
1. Righe: orario, logo su riquadro bianco, titolo; nessun codice `[[[` visibile, nessun errore in console (`read_console_messages`, pattern `button-card|error`).
2. Clic su una riga: popup con locandina a sinistra, trama, cast e la dicitura TMDB.
3. Clic su una riga senza locandina (id 0): popup con "Nessuna trama disponibile.", senza errori.
4. Tema scuro: loghi leggibili.
Se `float:left` o `style` vengono tolti dal popup, usa una tabella HTML a due colonne al posto del float e rigenera.
Non cliccare nulla che apra finestre di conferma del browser.

- [ ] **Step 5: Documenta e chiudi**

In `README.md` (in italiano) aggiungi la sezione "Dettagli dei film (TMDB)": come creare la chiave su themoviedb.org, dove metterla (`/config/film_stasera/tmdb.key`, non nel repository), gli attributi nuovi, come generare e incollare `dashboard.json` (richiede button-card e browser_mod da HACS), la dicitura TMDB, il limite di 16 KB e cosa succede senza chiave. Nella specifica cambia la riga sulla trama in "troncata a 600 caratteri, e più corta quando serve per restare sotto i 15.500 byte di attributi". Poi:

```bash
cd ~/film-stasera && git add -A && git status --short   # niente tmdb.key, niente backup
git commit -m "README e specifica: dettagli dei film e dashboard con popup

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Aggiorna `~/.claude/projects/-home-alexcoscia-pannello/memory/project_film_stasera.md` (TMDB, button-card, `make_dashboard.py`, il vincolo dei 16 KB). Chiedi all'utente se fare il push dei commit (repo pubblico): senza conferma non si spinge.

---

## Self-Review

- **Copertura della specifica:** dati TMDB, cache 7 giorni, attributi e chiave in file (Task 1-2); limite 16 KB (Task 1 `fit_size`); righe a tre colonne e popup con dicitura (Task 3); verifica sul Pi e nel browser (Task 4); tile Tessera invariato (nessun task lo tocca).
- **Segnaposto:** nessuno; ogni codice è completo. L'unico passo non meccanico è l'inserimento delle schede nella dashboard (Task 4, Step 3), perché dipende dalla struttura attuale che si legge sul momento.
- **Coerenza dei nomi:** `enrich`, `lookup`, `fit_size`, `read_key`, `tmdb_get`, `key_of`, `MAX_JSON`, `MAX_OVERVIEW`, `DEFAULT_TMDB_KEY`, `DEFAULT_TMDB_CACHE`, `build_config`, `film_row`, `variables.i` sono gli stessi in codice e test.
- **Rischi noti, da verificare in Task 4:** `button-card` deve accettare `[[[ ]]]` nei `custom_fields` e il `display` dentro `styles.card`; `browser_mod` deve accettare un `markdown` come contenuto; HA deve lasciare passare `style` e `<img>` nel popup.
