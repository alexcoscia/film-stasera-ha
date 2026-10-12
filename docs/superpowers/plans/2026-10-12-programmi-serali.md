# Film stasera: modalità Programmi — piano di implementazione

> **Per chi esegue:** REQUIRED SUB-SKILL: usare superpowers:subagent-driven-development (consigliato) oppure superpowers:executing-plans per eseguire il piano task per task. I passi usano caselle `- [ ]` da spuntare.

**Goal:** aggiungere al tile Tessera "Film stasera" una seconda modalità (prima e seconda serata di ogni canale, in ordine di telecomando), un tocco che alterna le modalità e un pulsante Aggiorna quando mancano i dati.

**Architecture:** lo script `film_stasera.py` raccoglie nello stesso passaggio sulla guida anche i programmi di prima e seconda serata e li aggiunge come sei liste nuove allo stesso `sensor.film_stasera`. Il plugin 0.3.0 riusa lo stesso tile: due modalità sullo stesso insieme di widget, scelta dello stato (`resolve_view`) in un header C++ puro provato sul PC, pulsante Aggiorna che chiama `homeassistant.update_entity` sul sensore.

**Tech Stack:** Python 3.12 (solo libreria standard, `unittest`), C++17 per il firmware Tessera (ESPHome 2026.9 / LVGL), bench di Tessera (`tools/preview.py`), Home Assistant (`command_line`, MCP `ha_*`).

**Spec:** `docs/superpowers/specs/2026-10-12-programmi-serali-design.md` (in questa cartella, repository `film-stasera-ha`).

**Repository coinvolti:** `~/film-stasera` (script, package HA, test Python, spec e piano) e `~/tessera-film-stasera` (plugin). Gli attributi, i test e il C++ che seguono sono stati provati prima di scrivere il piano: 55 test Python verdi, `logic_test` verde, bench di Tessera con 0 avvisi su 4 schermi.

## Vincoli globali

- Fasce (ora di Roma, minuti dalla mezzanotte del giorno): prima serata `PRIME = (21*60, 22*60+30)`, seconda `LATE = (23*60, 26*60)` (le 02:00 del giorno dopo, esclusa), `MIN_MINUTES = 30`, durata sconosciuta va bene, titolo vuoto si salta.
- Ordine canali `CHANNEL_ORDER` per numero di telecomando; un canale fuori lista va in fondo; solo i canali con almeno una fascia vengono elencati; al massimo `MAX_SHOWS = 20`.
- Nuovi attributi del sensore (liste parallele): `prog_channels`, `prog_groups`, `prog1_titles`, `prog1_starts`, `prog2_titles`, `prog2_starts`. Fascia mancante: titolo `""` e inizio `0`. Titoli dei programmi al massimo `MAX_PROG_TITLE = 30` caratteri.
- Budget dei dati del tile: l'app manda **al massimo 2600 byte** tra film e programmi (`X_BUDGET`); oggi film 793 + programmi 1569 = 2258. Limite database di HA `MAX_JSON = 15500` invariato; `fit_size` taglia solo trame e cast.
- Un attributo il cui nome finisce per `date` arriva al tile come secondi dal 1970 (mezzanotte del giorno): il tile lo legge come numero.
- Tile: `PAGE_SECONDS = 8`, `BUSY_SECONDS = 90`, `DENIED_SECONDS = 5`; permesso `permissions.home_assistant_actions: [homeassistant.update_entity]`; `memory: 11000`; versione 0.3.0.
- Dopo una modifica allo script/package HA si rilegge con `command_line.reload`, **mai `rest.reload`** (ricarica anche i sensori REST del bar e li lascia `unavailable`).
- Nessun `git push`, nessuna release e nessun OTA sul 7B senza il via esplicito dell'utente. Tutti i commit restano locali fino ad allora.
- Ogni commit finisce con la riga `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Punti di attenzione (Review Focus)

1. Una cache di oggi scritta dalla versione vecchia (senza `prog_*`) non deve bloccare il nuovo script per 4 ore: Task 3 (`test_senza_programmi_non_e_mai_fresca` e la cache di prova del test CLI).
2. Programma che inizia dopo mezzanotte (00:08 vale come seconda serata) e programma che inizia alle 02:30 (fuori): Task 1 e Task 2.
3. Lo stesso canale ripetuto nel file con id diversi e orari a pochi secondi: Task 2 (`DropRepeatsTest`, canale 5 con due id).
4. Serate con molti film: se film e programmi superano 2600 byte l'app taglia tutte le liste alla stessa lunghezza; i programmi restano sotto 1700 byte con 16 canali: Task 3 (`test_sedici_canali_pesano_poco`) e controllo reale nel Task 9.
5. Tile senza dati: sensore `unavailable`, senza `date`, guida di ieri e orologio non impostato; senza orologio niente pulsante; stato e data hanno la precedenza giusta: Task 5 (`logic_test`) e Task 7 (bench).

---

### Task 1: Fasce serali e ordine dei canali (script)

**Files:**
- Modify: `~/film-stasera/film_stasera.py` (costanti prima di `# Loghi: file <slug>.png`; funzioni prima di `def logo_of`)
- Create: `~/film-stasera/tests/test_programmi.py`

**Interfaces:**
- Produces: costanti `PRIME`, `LATE`, `MIN_MINUTES`, `MAX_SHOWS`, `MAX_PROG_TITLE`, `PROG_KEYS`, `CHANNEL_ORDER`; `channel_rank(name) -> int`; `pick_slot(items, lo, hi, min_minutes=MIN_MINUTES) -> dict | None` con `items` ordinati per `at`, ognuno `{"title", "at" (epoch), "min" (minuti dalla mezzanotte), "dur" (minuti o None)}`; `build_programmes(per_channel) -> list[dict]` con righe `{"channel", "group", "prime", "late"}` (prime/late sono l'item o `None`), in ordine di telecomando, al massimo `MAX_SHOWS`.

- [ ] **Step 1: scrivi il test** — crea `tests/test_programmi.py` (gli import in testa servono anche ai task 2 e 3):

```python
import gzip
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import film_stasera as fs  # noqa: E402


def prog(title, minutes, dur=60, at=None):
    """Un programma che inizia a `minutes` minuti dalla mezzanotte del giorno scelto."""
    return {"title": title, "at": 1_000_000 + minutes * 60 if at is None else at, "min": minutes, "dur": dur}


class PickSlotTest(unittest.TestCase):
    def test_estremi_della_prima_serata(self):
        self.assertEqual(fs.pick_slot([prog("a", 21 * 60)], *fs.PRIME)["title"], "a")           # 21:00 incluso
        self.assertIsNone(fs.pick_slot([prog("a", 22 * 60 + 30)], *fs.PRIME))                   # 22:30 escluso
        self.assertIsNone(fs.pick_slot([prog("a", 21 * 60 - 1)], *fs.PRIME))                    # 20:59 fuori

    def test_estremi_della_seconda_serata(self):
        self.assertEqual(fs.pick_slot([prog("a", 23 * 60)], *fs.LATE)["title"], "a")            # 23:00 incluso
        self.assertEqual(fs.pick_slot([prog("a", 25 * 60 + 59)], *fs.LATE)["title"], "a")       # 01:59 incluso
        self.assertIsNone(fs.pick_slot([prog("a", 26 * 60)], *fs.LATE))                         # 02:00 escluso

    def test_dopo_mezzanotte_conta_come_seconda_serata(self):
        self.assertEqual(fs.pick_slot([prog("Cose Nostre", 24 * 60 + 8)], *fs.LATE)["title"], "Cose Nostre")

    def test_durata_minima(self):
        items = [prog("TG2 Post", 21 * 60, dur=20), prog("Formidabile", 21 * 60 + 20, dur=150)]
        self.assertEqual(fs.pick_slot(items, *fs.PRIME)["title"], "Formidabile")
        self.assertEqual(fs.pick_slot([prog("x", 21 * 60, dur=30)], *fs.PRIME)["title"], "x")   # 30 minuti bastano
        self.assertIsNone(fs.pick_slot([prog("x", 21 * 60, dur=29)], *fs.PRIME))

    def test_durata_sconosciuta_va_bene(self):
        self.assertEqual(fs.pick_slot([prog("x", 21 * 60, dur=None)], *fs.PRIME)["title"], "x")

    def test_titolo_vuoto_si_salta(self):
        items = [prog("", 21 * 60), prog("Vero", 21 * 60 + 10)]
        self.assertEqual(fs.pick_slot(items, *fs.PRIME)["title"], "Vero")

    def test_il_primo_della_fascia(self):
        items = [prog("primo", 21 * 60 + 5), prog("secondo", 21 * 60 + 40)]
        self.assertEqual(fs.pick_slot(items, *fs.PRIME)["title"], "primo")


class BuildProgrammesTest(unittest.TestCase):
    def test_ordine_di_telecomando(self):
        per = {"Canale 5": [prog("a", 21 * 60 + 20)], "Rai 1": [prog("b", 21 * 60 + 30)], "Rete 4": [prog("c", 21 * 60 + 34)]}
        self.assertEqual([r["channel"] for r in fs.build_programmes(per)], ["Rai 1", "Rete 4", "Canale 5"])

    def test_canale_fuori_lista_in_fondo(self):
        per = {"Boh TV": [prog("a", 21 * 60 + 20)], "Rai 1": [prog("b", 21 * 60 + 30)]}
        self.assertEqual([r["channel"] for r in fs.build_programmes(per)], ["Rai 1", "Boh TV"])

    def test_canale_senza_fasce_non_compare(self):
        per = {"NOVE": [prog("tg", 20 * 60)], "Rai 1": [prog("b", 21 * 60 + 30)]}
        self.assertEqual([r["channel"] for r in fs.build_programmes(per)], ["Rai 1"])

    def test_una_fascia_sola(self):
        rows = fs.build_programmes({"Rai 1": [prog("b", 21 * 60 + 30)]})
        self.assertEqual(rows[0]["prime"]["title"], "b")
        self.assertIsNone(rows[0]["late"])
        self.assertEqual(rows[0]["group"], 1)

    def test_due_fasce(self):
        rows = fs.build_programmes({"Rai 1": [prog("sera", 21 * 60 + 30), prog("notte", 24 * 60 + 8)]})
        self.assertEqual((rows[0]["prime"]["title"], rows[0]["late"]["title"]), ("sera", "notte"))

    def test_al_massimo_venti_canali(self):
        per = {f"C{i}": [prog("a", 21 * 60 + 30)] for i in range(30)}
        self.assertEqual(len(fs.build_programmes(per)), fs.MAX_SHOWS)
```

- [ ] **Step 2: verifica che fallisca**

Run: `cd ~/film-stasera && python3 -m unittest tests.test_programmi -v 2>&1 | tail -6`
Expected: errori `AttributeError: module 'film_stasera' has no attribute 'PRIME'` (o `pick_slot`).

- [ ] **Step 3: costanti** — in `film_stasera.py` inserisci questo blocco subito prima della riga `# Loghi: file <slug>.png`:

```python
# Modalita' Programmi: prima e seconda serata. Minuti dalla mezzanotte del giorno scelto (ora di Roma): 26*60 sono le 02:00
# del giorno dopo. Un programma conta solo se dura almeno MIN_MINUTES (niente TG, meteo, riempitivi).
PRIME = (21 * 60, 22 * 60 + 30)    # prima serata: inizia tra le 21:00 e le 22:30
LATE = (23 * 60, 26 * 60)          # seconda serata: inizia tra le 23:00 e le 02:00
MIN_MINUTES = 30
MAX_SHOWS = 20
MAX_PROG_TITLE = 30   # il tile riceve al massimo 2600 byte tra film e programmi: i titoli dei programmi sono piu' corti
PROG_KEYS = ["prog_channels", "prog_groups", "prog1_titles", "prog1_starts", "prog2_titles", "prog2_starts"]
# Ordine per numero di telecomando (la numerazione piu' comune del digitale terrestre). Un canale che non e' qui va in fondo.
CHANNEL_ORDER = ["Rai 1", "Rai 2", "Rai 3", "Rete 4", "Canale 5", "Italia 1", "La7", "TV8", "NOVE", "20", "Rai 4", "Iris",
                 "Rai Movie", "Real Time", "Cine34", "Focus", "Top Crime", "DMAX", "Italia 2", "Discovery"]
```

- [ ] **Step 4: funzioni** — inserisci subito prima di `def logo_of(channel, logos_dir):`:

```python
def channel_rank(name):
    return CHANNEL_ORDER.index(name) if name in CHANNEL_ORDER else len(CHANNEL_ORDER)


def pick_slot(items, lo, hi, min_minutes=MIN_MINUTES):
    """Il primo programma (items e' ordinato per 'at') che inizia tra lo e hi minuti dalla mezzanotte e dura abbastanza.
    Durata sconosciuta (None) va bene; un titolo vuoto no."""
    for it in items:
        if not it["title"]:
            continue
        if lo <= it["min"] < hi and (it["dur"] is None or it["dur"] >= min_minutes):
            return it
    return None


def build_programmes(per_channel):
    """per_channel: nome -> programmi (dict con title, at, min, dur). Ritorna, in ordine di telecomando, una riga per canale
    che ha almeno una fascia: {"channel", "group", "prime", "late"} (prime/late sono il programma o None)."""
    rows = []
    for name in sorted(per_channel, key=lambda n: (channel_rank(n), n)):
        items = sorted(per_channel[name], key=lambda x: x["at"])
        prime, late = pick_slot(items, *PRIME), pick_slot(items, *LATE)
        if prime or late:
            rows.append({"channel": name, "group": GROUP.get(name, 0), "prime": prime, "late": late})
    return rows[:MAX_SHOWS]
```

- [ ] **Step 5: verifica che passi**

Run: `cd ~/film-stasera && python3 -m unittest tests.test_programmi -v 2>&1 | tail -4`
Expected: `Ran 13 tests ... OK`

- [ ] **Step 6: commit**

```bash
cd ~/film-stasera && git add film_stasera.py tests/test_programmi.py && git commit -q -F - <<'EOF'
Script: fasce serali (prima e seconda serata) e ordine dei canali

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Estrazione dei programmi dalla guida (script)

**Files:**
- Modify: `~/film-stasera/film_stasera.py` (`drop_repeats` e `duration_minutes` prima di `def extract`; sostituisci `extract` e `fetch_today` per intero)
- Modify: `~/film-stasera/tests/test_programmi.py` (aggiungi in fondo)

**Interfaces:**
- Consumes: `build_programmes`, `PRIME`, `LATE`, `short`, `norm`, `to_rome`, `parse_ts`, `DUP_WINDOW` (task 1 e codice esistente).
- Produces: `drop_repeats(items) -> list[dict]`; `duration_minutes(el, start_aw) -> float | None`; **`extract(path, day) -> (films, programmes, stats)`** (prima restituiva `(films, stats)`); **`fetch_today(day, input_path) -> (films, programmes)`** (prima restituiva solo i film).

- [ ] **Step 1: scrivi i test** — aggiungi in fondo a `tests/test_programmi.py`:

```python
def write_guide(path, channels, programmes):
    """Una guida XMLTV minima. channels: {id: nome}; programmes: [(id, inizio, fine, titolo, categorie)] con gli orari
    come AAAAMMGGhhmm (ora di Roma, +0200: il 12 ottobre 2026 c'e' ancora l'ora legale)."""
    xml = ['<?xml version="1.0" encoding="UTF-8"?><tv>']
    for cid, name in channels.items():
        xml.append(f'<channel id="{cid}"><display-name>{escape(name)}</display-name></channel>')
    for cid, start, stop, title, cats in programmes:
        stop_attr = f' stop="{stop}00 +0200"' if stop else ""
        cat_xml = "".join(f"<category>{escape(c)}</category>" for c in cats)
        xml.append(f'<programme channel="{cid}" start="{start}00 +0200"{stop_attr}>'
                   f"<title>{escape(title)}</title>{cat_xml}</programme>")
    xml.append("</tv>")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("".join(xml))


CHANNELS = {"r1": "Rai 1", "r2": "Rai 2", "c5a": "Canale 5", "c5b": "Canale 5", "i1": "Italia 1", "n9": "NOVE"}
PROGRAMMES = [
    ("r1", "202610122000", "202610122130", "Tg1", ["Informazione"]),
    ("r1", "202610122130", "202610122235", "I casi di Teresa Battaglia", ["Intrattenimento"]),
    ("r1", "202610122345", "202610130000", "Cose Nostre breve", ["Reportage"]),
    ("r1", "202610130008", "202610130110", "Cose Nostre", ["Reportage"]),
    ("r2", "202610122100", "202610122120", "TG2 Post", ["Intrattenimento"]),
    ("r2", "202610122120", "202610122350", "Formidabile! 2026", ["Intrattenimento"]),
    ("r2", "202610122350", "202610130120", "Il Processo del Lunedi", ["Intrattenimento"]),
    ("r2", "202610130230", "202610130450", "Fuori fascia", ["Film"]),            # 02:30: dopo le 02:00
    ("c5a", "202610122120", "202610130140", "Grande Fratello", ["Show"]),
    ("c5b", "202610122120", "202610130140", "Grande Fratello", ["Show"]),         # lo stesso, con un altro id
    ("i1", "202610122128", "202610122321", "Retribution", ["Film", "Azione"]),
    ("i1", "202610122321", "202610130012", "Cold Case", ["Fiction"]),
    ("n9", "202610122000", "202610122030", "Tg", ["Informazione"]),
]


class DropRepeatsTest(unittest.TestCase):
    def test_stesso_titolo_a_pochi_secondi(self):
        items = [prog("a", 100, at=1000), prog("a", 100, at=1003), prog("b", 100, at=1003)]
        self.assertEqual([i["title"] for i in fs.drop_repeats(items)], ["a", "b"])

    def test_stesso_titolo_ore_dopo_e_un_altro_programma(self):
        items = [prog("a", 100, at=1000), prog("a", 100, at=1000 + fs.DUP_WINDOW)]
        self.assertEqual(len(fs.drop_repeats(items)), 2)


class ExtractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "guide.gzip")
        write_guide(self.path, CHANNELS, PROGRAMMES)
        self.films, self.rows, self.stats = fs.extract(self.path, date(2026, 10, 12))
        self.by = {r["channel"]: r for r in self.rows}

    def tearDown(self):
        self.tmp.cleanup()

    def test_ordine_e_canali(self):
        self.assertEqual([r["channel"] for r in self.rows], ["Rai 1", "Rai 2", "Canale 5", "Italia 1"])   # NOVE: nessuna fascia

    def test_rai1(self):
        self.assertEqual(self.by["Rai 1"]["prime"]["title"], "I casi di Teresa Battaglia")
        self.assertEqual(self.by["Rai 1"]["late"]["title"], "Cose Nostre")            # salta quello da 15 minuti

    def test_rai2_salta_il_tg_breve_e_il_fuori_fascia(self):
        self.assertEqual(self.by["Rai 2"]["prime"]["title"], "Formidabile! 2026")
        self.assertEqual(self.by["Rai 2"]["late"]["title"], "Il Processo del Lunedi")

    def test_canale_con_una_fascia_sola(self):
        self.assertEqual(self.by["Canale 5"]["prime"]["title"], "Grande Fratello")
        self.assertIsNone(self.by["Canale 5"]["late"])

    def test_orari_in_secondi(self):
        # 23:21 ora di Roma (+0200) del 12 ottobre 2026 = 21:21 UTC
        self.assertEqual(self.by["Italia 1"]["late"]["at"] % 86400, 21 * 3600 + 21 * 60)

    def test_i_film_restano_come_prima(self):
        self.assertEqual([(f["channel"], f["title"]) for f in self.films], [("Italia 1", "Retribution")])
```

- [ ] **Step 2: verifica che falliscano**

Run: `cd ~/film-stasera && python3 -m unittest tests.test_programmi 2>&1 | tail -5`
Expected: `AttributeError: module 'film_stasera' has no attribute 'drop_repeats'` e, per `ExtractTest`, `ValueError: not enough values to unpack`.

- [ ] **Step 3: implementa** — inserisci prima di `def extract(path, day):` queste due funzioni:

```python
def drop_repeats(items):
    """Il file ripete lo stesso canale con id diversi e orari che differiscono di pochi secondi: stesso titolo entro
    DUP_WINDOW secondi e' lo stesso programma."""
    out, last = [], {}
    for it in sorted(items, key=lambda x: x["at"]):
        prev = last.get(norm(it["title"]))
        if prev is not None and it["at"] - prev < DUP_WINDOW:
            continue
        last[norm(it["title"])] = it["at"]
        out.append(it)
    return out


def duration_minutes(el, start_aw):
    """Durata di un <programme> in minuti, None se la fine manca o non si legge."""
    stop = el.get("stop")
    try:
        return (parse_ts(stop) - start_aw).total_seconds() / 60 if stop else None
    except ValueError:
        return None
```

Poi **sostituisci per intero** la funzione `extract` esistente con:

```python
def extract(path, day):
    """Ritorna (film, programmi, statistiche) per il giorno 'day' (data di Roma). film: lista di dict dei film della
    prima serata. programmi: le righe di build_programmes (prima e seconda serata di ogni canale)."""
    midnight = datetime(day.year, day.month, day.day)
    start_win = midnight + timedelta(hours=FROM_HOUR)
    end_win = midnight + timedelta(hours=TO_HOUR)
    progs = {}      # nome mostrato -> programmi tra PRIME[0] e LATE[1] (per la modalita' Programmi)
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
                    local = to_rome(start_aw)
                    minutes = (local - midnight).total_seconds() / 60
                    if PRIME[0] <= minutes < LATE[1]:
                        progs.setdefault(shown, []).append({
                            "title": short(el.findtext("title")), "at": int(start_aw.timestamp()),
                            "min": minutes, "dur": duration_minutes(el, start_aw)})
                    if start_win <= local < end_win:
                        stats["evening"][shown] += 1
                        cats = [norm(c.text) for c in el.findall("category") if c.text]
                        if FILM_CATEGORIES.intersection(cats):
                            genre = next((c for c in cats if c not in GENERIC), "")
                            seen.setdefault(shown, []).append({
                                "title": short(el.findtext("title")),
                                "channel": shown,
                                "at": int(start_aw.timestamp()),
                                "genre": genre.capitalize(),
                                "group": GROUP.get(shown, 0),
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
    programmes = build_programmes({name: drop_repeats(items) for name, items in progs.items()})
    return films, programmes, stats
```

e **sostituisci per intero** `fetch_today` con:

```python
def fetch_today(day, input_path):
    """Scarica (o legge il file dato), estrae e controlla. Solleva un'eccezione se qualcosa non torna."""
    with tempfile.TemporaryDirectory(prefix="film_stasera_") as tmp:
        path = input_path
        if not path:
            path = os.path.join(tmp, "guide.gzip")
            size = download(SOURCE_URL, path)
            print(f"scaricati {size} byte", file=sys.stderr)
        films, programmes, stats = extract(path, day)
    if stats["channels_in_file"] < 100 or stats["programmes"] < 10_000:
        raise RuntimeError(f"file anomalo ({stats['channels_in_file']} canali, {stats['programmes']} programmi)")
    print(f"{stats['channels_in_file']} canali, {stats['programmes']} programmi; film trovati: {len(films)}",
          file=sys.stderr)
    print("film per canale:", {n: c for n, c in stats["per_channel"].items() if c}, file=sys.stderr)
    print(f"programmi: {len(programmes)} canali con almeno una fascia serale", file=sys.stderr)
    no_film = [n for n, c in stats["per_channel"].items() if c == 0 and stats["evening"][n] > 0]
    no_data = [n for n, c in stats["evening"].items() if c == 0]
    if no_film:
        print("canali senza film in serata:", ", ".join(no_film), file=sys.stderr)
    if no_data:
        print("ATTENZIONE, nessun programma in serata per:", ", ".join(no_data), file=sys.stderr)
    return films, programmes
```

(`main` usa ancora la vecchia firma di `fetch_today` fino al task 3: non lanciare lo script a mano tra i due task.)

- [ ] **Step 4: verifica che passino**

Run: `cd ~/film-stasera && python3 -m unittest tests.test_programmi -v 2>&1 | tail -4`
Expected: `Ran 21 tests ... OK`

- [ ] **Step 5: commit**

```bash
cd ~/film-stasera && git add film_stasera.py tests/test_programmi.py && git commit -q -F - <<'EOF'
Script: estrae i programmi di prima e seconda serata dalla guida

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Attributi del sensore, cache e dimensione (script)

**Files:**
- Modify: `~/film-stasera/film_stasera.py` (`build`, `load_cache`, `main` sostituite per intero; `cache_is_fresh` e `programmes_lines` prima di `def write_atomic`)
- Modify: `~/film-stasera/tests/test_tmdb.py` (la cache di prova del test CLI)
- Modify: `~/film-stasera/tests/test_programmi.py` (aggiungi in fondo)

**Interfaces:**
- Consumes: `extract`/`fetch_today` del task 2, `build_programmes` del task 1, `PROG_KEYS`, `MAX_PROG_TITLE`.
- Produces: `build(day, films, stale=False, error="", logos_dir=None, programmes=None) -> dict` con i sei attributi `prog_*` sempre presenti (liste vuote senza programmi); `cache_is_fresh(cache, day, max_age_hours, now, use_input=False) -> bool`; `programmes_lines(out) -> list[str]`; `load_cache` accetta cache senza `prog_*` ma scarta quelle con liste di lunghezza diversa.

- [ ] **Step 1: scrivi i test** — aggiungi in fondo a `tests/test_programmi.py`:

```python
def rows_of(n):
    return [{"channel": f"Canale {i}", "group": 2, "prime": prog(f"Prima serata {i} " + "x" * 30, 21 * 60 + 30, at=1000 + i),
             "late": prog(f"Seconda serata {i} " + "y" * 30, 24 * 60 + 8, at=2000 + i)} for i in range(n)]


class BuildOutputTest(unittest.TestCase):
    day = date(2026, 10, 12)

    def test_sei_liste_della_stessa_lunghezza(self):
        out = fs.build(self.day, [], programmes=rows_of(3))
        self.assertEqual({len(out[k]) for k in fs.PROG_KEYS}, {3})
        self.assertEqual(out["prog_channels"], ["Canale 0", "Canale 1", "Canale 2"])
        self.assertEqual(out["prog1_starts"], [1000, 1001, 1002])
        self.assertEqual(out["prog2_starts"], [2000, 2001, 2002])

    def test_fascia_mancante(self):
        rows = [{"channel": "Rai 1", "group": 1, "prime": prog("Sera", 21 * 60 + 30, at=5), "late": None}]
        out = fs.build(self.day, [], programmes=rows)
        self.assertEqual((out["prog2_titles"], out["prog2_starts"]), ([""], [0]))

    def test_senza_programmi_liste_vuote(self):
        out = fs.build(self.day, [])
        self.assertEqual([out[k] for k in fs.PROG_KEYS], [[], [], [], [], [], []])

    def test_titoli_dei_programmi_accorciati(self):
        out = fs.build(self.day, [], programmes=rows_of(2))
        self.assertTrue(all(len(x) <= fs.MAX_PROG_TITLE for x in out["prog1_titles"] + out["prog2_titles"]))
        self.assertTrue(out["prog1_titles"][0].startswith("Prima serata 0"))

    def test_i_campi_di_prima_non_cambiano(self):
        out = fs.build(self.day, [], programmes=rows_of(1))
        for k in ("date", "updated", "stale", "count", "titles", "channels", "starts", "genres", "groups", "logos"):
            self.assertIn(k, out)


class SizeTest(unittest.TestCase):
    def test_sedici_canali_pesano_poco(self):
        # Il tile riceve al massimo 2600 byte tra film e programmi (X_BUDGET dell'app): con i titoli a 30 caratteri
        # sedici canali pesano meno di 1700 byte, e oggi i film ne pesano ~800.
        out = fs.build(date(2026, 10, 12), [], programmes=rows_of(16))
        part = {k: out[k] for k in fs.PROG_KEYS}
        self.assertLess(len(json.dumps(part, ensure_ascii=False, separators=(",", ":"))), 1700)

    def test_fit_size_taglia_le_trame_e_mai_i_programmi(self):
        out = dict(fs.build(date(2026, 10, 12), [], programmes=rows_of(20)), overviews=["z" * 600] * 20)
        before = {k: list(out[k]) for k in fs.PROG_KEYS}
        res = fs.fit_size(out)
        self.assertLessEqual(len(json.dumps(res, ensure_ascii=False, separators=(",", ":"))), fs.MAX_JSON)
        self.assertEqual({k: res[k] for k in fs.PROG_KEYS}, before)


class CacheTest(unittest.TestCase):
    day = date(2026, 10, 12)

    def cache(self, **kw):
        c = dict(fs.build(self.day, [], programmes=rows_of(2)), updated=1000)
        c.update(kw)
        return c

    def test_fresca(self):
        self.assertTrue(fs.cache_is_fresh(self.cache(), self.day, 4, now=1000 + 3600))

    def test_senza_programmi_non_e_mai_fresca(self):
        old = {k: v for k, v in self.cache().items() if k not in fs.PROG_KEYS}
        self.assertFalse(fs.cache_is_fresh(old, self.day, 4, now=1000 + 60))

    def test_altri_motivi_per_riscaricare(self):
        c = self.cache()
        self.assertFalse(fs.cache_is_fresh(c, self.day, 4, now=1000 + 5 * 3600))                 # troppo vecchia
        self.assertFalse(fs.cache_is_fresh(self.cache(stale=True), self.day, 4, now=1001))       # servita da cache
        self.assertFalse(fs.cache_is_fresh(c, date(2026, 10, 13), 4, now=1001))                  # altro giorno
        self.assertFalse(fs.cache_is_fresh(c, self.day, 0, now=1001))                            # sempre
        self.assertFalse(fs.cache_is_fresh(c, self.day, 4, now=1001, use_input=True))            # file dato
        self.assertFalse(fs.cache_is_fresh(None, self.day, 4, now=1001))

    def test_load_cache_vecchia_e_incoerente(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.json")
            old = {k: v for k, v in self.cache().items() if k not in fs.PROG_KEYS}
            with open(path, "w") as f:
                json.dump(old, f)
            self.assertIsNotNone(fs.load_cache(path))                  # una cache di prima si legge ancora
            bad = self.cache()
            bad["prog1_titles"] = bad["prog1_titles"][:1]
            with open(path, "w") as f:
                json.dump(bad, f)
            self.assertIsNone(fs.load_cache(path))                     # liste di lunghezza diversa: si scarta
            with open(path, "w") as f:
                json.dump(self.cache(), f)
            self.assertIsNotNone(fs.load_cache(path))


class DryRunTest(unittest.TestCase):
    def test_righe_leggibili(self):
        out = fs.build(date(2026, 10, 12), [], programmes=[
            {"channel": "Rai 1", "group": 1, "prime": prog("Sera", 21 * 60 + 30, at=1791833400), "late": None}])
        line = fs.programmes_lines(out)[0]
        self.assertIn("Rai 1", line)
        self.assertIn("21:30 Sera", line)                              # 1791833400 = 19:30 UTC = 21:30 ora di Roma
        self.assertTrue(line.rstrip().endswith("-"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: verifica che falliscano**

Run: `cd ~/film-stasera && python3 -m unittest tests.test_programmi 2>&1 | tail -4`
Expected: `FAILED` con `AttributeError` su `cache_is_fresh` / `programmes_lines` e `TypeError` su `build(... programmes=...)`.

- [ ] **Step 3: implementa** — **sostituisci per intero** `build`:

```python
def build(day, films, stale=False, error="", logos_dir=None, programmes=None):
    films = films[:MAX_ITEMS]
    rows = programmes or []
    out = {
        "date": day.isoformat(),
        "updated": int(time.time()),
        "stale": stale,
        "count": len(films),
        "titles": [f["title"] for f in films],
        "channels": [f["channel"] for f in films],
        "starts": [f["at"] for f in films],
        "genres": [f["genre"] for f in films],
        "groups": [f["group"] for f in films],
        "logos": [logo_of(f["channel"], logos_dir) for f in films],
        # Modalita' Programmi: una voce per canale (prima e seconda serata); fascia mancante: titolo "" e inizio 0.
        "prog_channels": [r["channel"] for r in rows],
        "prog_groups": [r["group"] for r in rows],
        "prog1_titles": [r["prime"]["title"][:MAX_PROG_TITLE].rstrip() if r["prime"] else "" for r in rows],
        "prog1_starts": [r["prime"]["at"] if r["prime"] else 0 for r in rows],
        "prog2_titles": [r["late"]["title"][:MAX_PROG_TITLE].rstrip() if r["late"] else "" for r in rows],
        "prog2_starts": [r["late"]["at"] if r["late"] else 0 for r in rows],
    }
    if error:
        out["error"] = error[:120]
    return out
```

**sostituisci per intero** `load_cache`:

```python
def load_cache(path):
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
        n = len(c["titles"])
        if not (isinstance(c["date"], str) and isinstance(c["updated"], (int, float))
                and len(c["channels"]) == n == len(c["starts"]) == len(c["genres"])):
            return None
        # I programmi sono facoltativi (una cache di una versione precedente non li ha), ma se ci sono devono tornare.
        if "prog_channels" in c and len({len(c.get(k, ())) for k in PROG_KEYS}) != 1:
            return None
        return c
    except (OSError, ValueError, KeyError, TypeError):
        return None
```

inserisci prima di `def write_atomic(path, text):`:

```python
def cache_is_fresh(cache, day, max_age_hours, now, use_input=False):
    """La cache di oggi, buona e abbastanza recente: niente nuovo download. Una cache senza i programmi (scritta da una
    versione precedente dello script) non e' mai fresca."""
    return bool(cache and cache["date"] == day.isoformat() and not cache.get("stale")
                and "prog_channels" in cache and max_age_hours > 0 and not use_input
                and now - cache["updated"] < max_age_hours * 3600)


def programmes_lines(out):
    """Righe leggibili per --dry-run: canale, prima serata, seconda serata."""
    def show(title, start):
        return f"{to_rome(datetime.fromtimestamp(start, timezone.utc)):%H:%M} {title}" if start else "-"
    return [f"{ch:<10} {show(out['prog1_titles'][i], out['prog1_starts'][i]):<48} "
            f"{show(out['prog2_titles'][i], out['prog2_starts'][i])}" for i, ch in enumerate(out.get("prog_channels", []))]
```

e **sostituisci per intero** `main`:

```python
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="file con l'ultimo risultato buono")
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                    help="se la cache di oggi e' piu' recente di cosi' non riscarica (0 = riscarica sempre)")
    ap.add_argument("--logos-dir", default=LOGOS_DIR, help="cartella dei loghi <canale>.png (default: /config/www/tv-logos)")
    ap.add_argument("--input", help="usa questo guide.gzip invece di scaricarlo")
    ap.add_argument("--date", help="giorno AAAA-MM-GG (default: oggi a Roma)")
    ap.add_argument("--tmdb-key-file", default=DEFAULT_TMDB_KEY, help="file con la chiave TMDB (una riga)")
    ap.add_argument("--tmdb-cache", default=DEFAULT_TMDB_CACHE, help="cache dei dettagli dei film")
    ap.add_argument("--dry-run", action="store_true", help="elenco leggibile, non scrive la cache")
    args = ap.parse_args()

    day = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else today_rome()
    cache = load_cache(args.cache)
    out = None

    fresh = cache_is_fresh(cache, day, args.max_age_hours, time.time(), bool(args.input))
    if fresh:
        print("cache fresca: nessun download", file=sys.stderr)
        out = cache
    else:
        try:
            films, programmes = fetch_today(day, args.input)
            out = build(day, films, logos_dir=args.logos_dir, programmes=programmes)
            if not args.dry_run:
                write_atomic(args.cache, json.dumps(out, ensure_ascii=False, separators=(",", ":")))
        except Exception as e:  # rete, file strano, disco: qualunque cosa, non perdere i dati buoni
            print(f"ERRORE: {e}", file=sys.stderr)
            if cache:
                out = dict(cache, stale=True, error=str(e)[:120])   # tiene la data originale: il tile sa che e' vecchio
            else:
                out = build(day, [], stale=True, error=str(e), logos_dir=args.logos_dir)

    try:
        out = enrich(out, read_key(args.tmdb_key_file), args.tmdb_cache, write=not args.dry_run)
    except Exception as e:   # mai perdere la guida per colpa dei dettagli
        print(f"TMDB: saltato ({type(e).__name__})", file=sys.stderr)

    if args.dry_run:
        years = out.get("years") or [""] * len(out["titles"])
        for t, c, s, g, y in zip(out["titles"], out["channels"], out["starts"], out["genres"], years):
            local = to_rome(datetime.fromtimestamp(s, timezone.utc))
            print(f"{local:%H:%M} {c:<10} {('(' + y + ') ') if y else ''}{t} {('| ' + g) if g else ''}")
        print("-- programmi (canale, prima serata, seconda serata):")
        for line in programmes_lines(out) if "prog_channels" in out else []:
            print(line)
        print(f"-- {out['count']} film, data {out['date']}, stale={out['stale']}", file=sys.stderr)
    else:
        print(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0
```

- [ ] **Step 4: aggiorna la cache di prova del test CLI** — in `tests/test_tmdb.py`, dentro `CliTest.test_senza_chiave`, la cache scritta non ha i programmi e con la nuova regola non è più "fresca" (lo script proverebbe a scaricare). Sostituisci

```python
                json.dump(dict(out_of("La giuria", "Boh"), updated=int(_t.time())), f)
```

con

```python
                # una cache buona e di oggi: ha anche i programmi, altrimenti lo script la ritiene da rifare
                json.dump(dict(out_of("La giuria", "Boh"), updated=int(_t.time()), **{k: [] for k in fs.PROG_KEYS}), f)
```

- [ ] **Step 5: verifica tutta la suite**

Run: `cd ~/film-stasera && python3 -m unittest discover -s tests 2>&1 | tail -4`
Expected: `Ran 55 tests ... OK` (la riga `TMDB: The Italian Job: OSError` che compare prima è un messaggio atteso di un test, non un errore).

- [ ] **Step 6: commit**

```bash
cd ~/film-stasera && git add film_stasera.py tests/test_programmi.py tests/test_tmdb.py && git commit -q -F - <<'EOF'
Script: attributi prog_* nel sensore, cache senza programmi sempre da rifare, titoli corti

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Prova sulla guida vera e messa in opera dello script

**Files:**
- Modify: `~/film-stasera/film_stasera.yaml` (copia del package nel repository: `json_attributes`)
- Modify: `~/film-stasera/README.md` (sezione nuova)
- Modify su HA (root@100.116.129.24): `/homeassistant/film_stasera/film_stasera.py` e `/homeassistant/packages/film_stasera.yaml`, con backup

**Interfaces:**
- Consumes: lo script dei task 1–3.
- Produces: `sensor.film_stasera` con i sei attributi `prog_*` valorizzati.

- [ ] **Step 1: prova sui dati veri di oggi (nessun file di HA toccato)**

```bash
mkdir -p /tmp/guida && curl -sL -m 180 -o /tmp/guida/guide.gz https://www.epgitalia.tv/gzip
cd ~/film-stasera && python3 film_stasera.py --dry-run --input /tmp/guida/guide.gz --cache /tmp/guida/c.json \
  --logos-dir /tmp/guida --tmdb-key-file /tmp/guida/none.key --tmdb-cache /tmp/guida/t.json 2>&1 | sed -n '/programmi (canale/,$p'
```

Expected: una riga per canale con prima e seconda serata, circa 16 canali (il 12/10: Rai 1 `21:30 I casi di Teresa Battaglia…` / `00:08 Cose Nostre…`, Rai 2 `21:20 Formidabile! 2026` / `23:50 Il Processo del Lunedi'…`, Rete 4 `21:34 Quarta Repubblica…` / `00:56 Achille lauro…`, Italia 2 con la seconda serata `-`). NOVE, Discovery, Real Time e DMAX non compaiono. **Fermati e mostra l'elenco all'utente**: l'ordine dei canali e le fasce si correggono qui.

- [ ] **Step 2: package nel repository** — in `film_stasera.yaml` aggiungi i sei attributi a `json_attributes`:

```bash
cd ~/film-stasera && python3 - <<'EOF'
p = "film_stasera.yaml"
t = open(p).read()
old = "years, error]"
new = "years, prog_channels, prog_groups, prog1_titles, prog1_starts, prog2_titles, prog2_starts, error]"
assert t.count(old) == 1
open(p, "w").write(t.replace(old, new))
EOF
grep -n json_attributes film_stasera.yaml
```

- [ ] **Step 3: README** — aggiungi in fondo a `README.md`:

```bash
cd ~/film-stasera && cat >> README.md <<'EOF'

## Programmi di prima e seconda serata

Lo stesso sensore ha sei attributi in più, una voce per canale in ordine di numero del telecomando (liste della stessa
lunghezza): `prog_channels`, `prog_groups` (il gruppo 1-4 del pallino), `prog1_titles` e `prog1_starts` (prima serata),
`prog2_titles` e `prog2_starts` (seconda serata). Un inizio vale secondi dal 1970; una fascia mancante ha titolo vuoto e
inizio 0. Un canale senza nessuna fascia non compare.

- Prima serata: il primo programma di almeno 30 minuti che inizia tra le 21:00 e le 22:30. Seconda serata: il primo di
  almeno 30 minuti che inizia tra le 23:00 e le 02:00 (del giorno dopo). Le costanti sono in testa allo script (`PRIME`,
  `LATE`, `MIN_MINUTES`); l'ordine dei canali è `CHANNEL_ORDER`.
- I titoli dei programmi sono al massimo 30 caratteri: l'app manda a ogni tile al massimo 2600 byte tra film e programmi.
- Una cache scritta da una versione precedente (senza questi attributi) non è mai "fresca": al primo giro lo script
  riscarica la guida.
EOF
```

- [ ] **Step 4: backup su HA e copia dello script** (l'HA di casa, `root@100.116.129.24`; la shell remota è zsh: tieni le virgolette)

```bash
ssh -o BatchMode=yes root@100.116.129.24 "cp -p /homeassistant/film_stasera/film_stasera.py /homeassistant/film_stasera/film_stasera.py.bak-2026-10-12-programmi && cp -p /homeassistant/packages/film_stasera.yaml /homeassistant/packages/film_stasera.yaml.bak-2026-10-12-programmi"
ssh -o BatchMode=yes root@100.116.129.24 "cat > /homeassistant/film_stasera/film_stasera.py" < ~/film-stasera/film_stasera.py
ssh -o BatchMode=yes root@100.116.129.24 "python3 -c 'import ast,sys; ast.parse(open(\"/homeassistant/film_stasera/film_stasera.py\").read()); print(\"sintassi ok\")'"
```

Expected: `sintassi ok`.

- [ ] **Step 5: package su HA** — il package di HA non ha più il blocco `automation:` (migrato in interfaccia): si cambia solo la riga `json_attributes`:

```bash
ssh -o BatchMode=yes root@100.116.129.24 "python3 - <<'EOF'
p = '/homeassistant/packages/film_stasera.yaml'
t = open(p).read()
old = 'years, error]'
new = 'years, prog_channels, prog_groups, prog1_titles, prog1_starts, prog2_titles, prog2_starts, error]'
assert t.count(old) == 1
open(p, 'w').write(t.replace(old, new))
EOF
grep -n json_attributes /homeassistant/packages/film_stasera.yaml"
```

- [ ] **Step 6: ricarica e aggiorna il sensore** (strumenti MCP di Home Assistant)

1. `ha_call_service(domain="homeassistant", service="check_config")` → deve riuscire.
2. `ha_call_service(domain="command_line", service="reload")` (non `rest.reload`).
3. `ha_call_service(domain="homeassistant", service="update_entity", entity_id="sensor.film_stasera")` e attendi qualche secondo.
4. `ha_get_state("sensor.film_stasera", fields=["state","attributes"], attribute_keys=["date","updated","prog_channels","prog1_starts","prog2_starts"])`.

Expected: `prog_channels` con ~16 canali, `prog1_starts`/`prog2_starts` della stessa lunghezza, `date` di oggi, `updated` di pochi secondi fa; lo stato (numero di film) e gli attributi di prima invariati.

- [ ] **Step 7: commit**

```bash
cd ~/film-stasera && git add film_stasera.yaml README.md && git commit -q -F - <<'EOF'
Package e README: attributi prog_* del sensore

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Logica del tile provata sul PC (plugin)

**Files:**
- Create: `~/tessera-film-stasera/components/film_stasera/logic.h`
- Create: `~/tessera-film-stasera/tests/logic_test.cpp`

**Interfaces:**
- Produces (namespace `esphome::film_stasera`): `enum class Mode { FILMS, PROGRAMMES }`; `enum class View { CHOOSE_SENSOR, WAITING, NO_DATA, OLD_GUIDE, EMPTY, LIST }`; `enum class Button { IDLE, BUSY, DENIED }`; `int page_count(int items, int per_page)`; `int page_for(uint32_t epoch, int pages, int seconds_per_page)`; `struct Situation { has_entity, wrong_entity, waiting, no_value, clock_set, day_offset, shown }`; `View resolve_view(const Situation&)`; `struct Refresh { busy_until, denied_until, updated_at_tap }`; `Button button_state(const Refresh&, uint32_t now, uint32_t updated_now)`.

- [ ] **Step 1: scrivi il test** — crea `tests/logic_test.cpp`:

```cpp
// Run on a computer: g++ -std=c++17 -Wall -Werror -I components/film_stasera tests/logic_test.cpp -o /tmp/logic_test && /tmp/logic_test
#include <cstdio>
#include <cstdlib>
#include "logic.h"

using namespace esphome::film_stasera;

static int failures = 0;
#define CHECK(cond)                                                  \
  do {                                                               \
    if (!(cond)) {                                                   \
      std::printf("FAIL line %d: %s\n", __LINE__, #cond);            \
      ++failures;                                                    \
    }                                                                \
  } while (0)

static Situation good() {
  Situation s;
  s.has_entity = true;
  s.clock_set = true;
  s.day_offset = 0;
  s.shown = 3;
  return s;
}

int main() {
  // pages
  CHECK(page_count(0, 8) == 0);
  CHECK(page_count(8, 8) == 1);
  CHECK(page_count(9, 8) == 2);
  CHECK(page_count(16, 8) == 2);
  CHECK(page_count(5, 0) == 0);
  CHECK(page_for(123456, 1, 8) == 0);
  CHECK(page_for(0, 2, 8) == 0);
  CHECK(page_for(8, 2, 8) == 1);
  CHECK(page_for(16, 2, 8) == 0);
  CHECK(page_for(8, 3, 8) == 1 && page_for(16, 3, 8) == 2 && page_for(24, 3, 8) == 0);

  // views, in the order of the table of the spec
  Situation s = good();
  CHECK(resolve_view(s) == View::LIST);
  s.shown = 0;
  CHECK(resolve_view(s) == View::EMPTY);
  s = good();
  s.has_entity = false;
  CHECK(resolve_view(s) == View::CHOOSE_SENSOR);
  s = good();
  s.wrong_entity = true;
  CHECK(resolve_view(s) == View::CHOOSE_SENSOR);
  s = good();
  s.waiting = true;
  CHECK(resolve_view(s) == View::WAITING);
  s = good();
  s.clock_set = false;
  CHECK(resolve_view(s) == View::WAITING);          // without the clock a date means nothing: no button
  s = good();
  s.no_value = true;
  CHECK(resolve_view(s) == View::NO_DATA);
  s = good();
  s.day_offset = INT32_MIN;
  CHECK(resolve_view(s) == View::NO_DATA);
  s = good();
  s.day_offset = -1;
  CHECK(resolve_view(s) == View::OLD_GUIDE);
  s.day_offset = 1;
  CHECK(resolve_view(s) == View::OLD_GUIDE);
  s = good();
  s.no_value = true;
  s.day_offset = -1;
  CHECK(resolve_view(s) == View::NO_DATA);          // the state wins over the date
  s = good();
  s.day_offset = -1;
  s.shown = 0;
  CHECK(resolve_view(s) == View::OLD_GUIDE);        // an old guide asks for Update even when it lists nothing

  // the button
  Refresh r;
  CHECK(button_state(r, 1000, 50) == Button::IDLE);
  r.updated_at_tap = 50;
  r.busy_until = 1090;
  CHECK(button_state(r, 1000, 50) == Button::BUSY);
  CHECK(button_state(r, 1000, 51) == Button::IDLE);  // the sensor changed: done
  CHECK(button_state(r, 1090, 50) == Button::IDLE);  // 90 seconds are over
  r.denied_until = 1005;
  CHECK(button_state(r, 1000, 50) == Button::DENIED);
  CHECK(button_state(r, 1005, 50) == Button::BUSY);  // denied is over, busy still holds

  if (failures == 0) std::printf("logic_test: ok\n");
  return failures == 0 ? 0 : 1;
}
```

- [ ] **Step 2: verifica che fallisca**

Run: `cd ~/tessera-film-stasera && g++ -std=c++17 -Wall -Wextra -Werror -I components/film_stasera tests/logic_test.cpp -o /tmp/logic_test 2>&1 | head -3`
Expected: `fatal error: logic.h: No such file or directory`.

- [ ] **Step 3: implementa** — crea `components/film_stasera/logic.h`:

```cpp
#pragma once
// The decisions of the tile that need no screen: which mode and view, which page, and what the Update button says. Plain C++ so tests/logic_test.cpp can run it on a computer.
#include <climits>
#include <cstdint>

namespace esphome::film_stasera {

enum class Mode { FILMS, PROGRAMMES };
enum class View { CHOOSE_SENSOR, WAITING, NO_DATA, OLD_GUIDE, EMPTY, LIST };
enum class Button { IDLE, BUSY, DENIED };

// How many pages `items` make with `per_page` on each (0 for nothing), and the page to show at `epoch` when the pages
// turn by themselves every `seconds_per_page`.
inline int page_count(int items, int per_page) {
  return per_page <= 0 || items <= 0 ? 0 : (items + per_page - 1) / per_page;
}
inline int page_for(uint32_t epoch, int pages, int seconds_per_page) {
  if (pages <= 1 || seconds_per_page <= 0) return 0;
  return static_cast<int>((epoch / static_cast<uint32_t>(seconds_per_page)) % static_cast<uint32_t>(pages));
}

// What the tile knows when it paints.
struct Situation {
  bool has_entity = false;     // the app sent data: a sensor was chosen
  bool wrong_entity = false;   // "wait": "wrong_entity"
  bool waiting = false;        // any other "wait"
  bool no_value = false;       // the sensor is unavailable or unknown
  bool clock_set = false;      // the screen knows the time
  int day_offset = INT32_MIN;  // days_from_today of the sensor's `date` (seconds since 1970); INT32_MIN when it has none
  int shown = 0;               // what the current mode would list
};

// The first that holds: no sensor; waiting for the app (no button: nothing to ask Home Assistant); no value or no date
// (Update); a guide that is not today's (Update); nothing to list; the list.
inline View resolve_view(const Situation &s) {
  if (!s.has_entity || s.wrong_entity) return View::CHOOSE_SENSOR;
  if (s.waiting || !s.clock_set) return View::WAITING;
  if (s.no_value || s.day_offset == INT32_MIN) return View::NO_DATA;
  if (s.day_offset != 0) return View::OLD_GUIDE;
  return s.shown > 0 ? View::LIST : View::EMPTY;
}

// The Update button after a tap: busy until the sensor's `updated` changes or `busy_until` passes; "not allowed" for a
// few seconds when the screen could not send the action.
struct Refresh {
  uint32_t busy_until = 0, denied_until = 0, updated_at_tap = 0;
};
inline Button button_state(const Refresh &r, uint32_t now, uint32_t updated_now) {
  if (now < r.denied_until) return Button::DENIED;
  if (now < r.busy_until && updated_now == r.updated_at_tap) return Button::BUSY;
  return Button::IDLE;
}

}  // namespace esphome::film_stasera
```

- [ ] **Step 4: verifica che passi, e che il check del plugin accetti la cartella `tests/`**

Run: `cd ~/tessera-film-stasera && g++ -std=c++17 -Wall -Wextra -Werror -I components/film_stasera tests/logic_test.cpp -o /tmp/logic_test && /tmp/logic_test && python3 -I ~/tessera-plugins/tools/check.py . | tail -3`
Expected: `logic_test: ok`, poi `: ok (no store.png yet...)`. Se `check.py` protesta per `tests/`, sposta il test in una cartella che accetta e aggiorna il comando qui sopra.

- [ ] **Step 5: commit**

```bash
cd ~/tessera-film-stasera && git add components/film_stasera/logic.h tests/logic_test.cpp && git commit -q -F - <<'EOF'
Tile: logica di modalita', stato, pagine e pulsante in un header provato sul PC

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Manifest, traduzioni, anteprima e changelog (plugin)

**Files:**
- Modify: `~/tessera-film-stasera/tessera-plugin.yaml`, `translations/it.json`, `translations/en.json`, `preview.yaml`, `CHANGELOG.md`

**Interfaces:**
- Consumes: i nomi degli attributi del task 3.
- Produces: tile `films` con gli attributi `date`, `updated`, `prog_*`, l'opzione `start` (`films`|`programmes`), il permesso `homeassistant.update_entity`, `memory: 11000`, le chiavi di testo `refresh`, `refreshing`, `not_allowed`, `no_data`, `old_day`, `programmes`, `none_programmes` (parte `screen`) e `start`, `start_hint`, `start_films`, `start_programmes` (parte `app`).

- [ ] **Step 1: manifest** — sostituisci l'intero `tessera-plugin.yaml` con:

```yaml
# The manifest: who made the plugin, what it may do, and what the Tessera app shows. It holds no code and no words:
# every name, label and hint below is a key into translations/<language>.json, part "app".
# Every field is explained in docs/MANIFEST.md of the plugins repository.
id: film_stasera
version: 0.3.0
api: "0.8"
icon: movie-open
maintainer: alexcoscia
license: MIT
# beta while it finds its feet, stable once people use it every day, example when it is there to learn from.
stage: beta
topics: [media]
requires:
  esphome: 2026.6.2
boards: any
flash_kb: 8

# The tile asks Home Assistant to update its own sensor when there is no data (the Update button).
permissions:
  home_assistant_actions: [homeassistant.update_entity]

tiles:
  # A tile that belongs to one sensor of Home Assistant: sensor.film_stasera, with the films of tonight as four lists
  # of the same length (titles, channels, starts as seconds since 1970, genres, and groups: a number 1 to 4 for the colour of each channel's dot). It draws one row per film, as many as
  # fit, and nothing is fetched from the internet: Home Assistant makes the sensor (see the README).
  - id: films
    name: tile_name
    icon: movie-open
    # From 1x1: the editor resizes one axis at a time, so a minimum above 1x1 leaves a new tile no first step (it would
    # be stuck at 1x1). One cell shows the next film; a bigger tile shows as many as fit.
    sizes: { min: 1x1, max: 4x4 }
    # Worst case, a wide tile: 2 columns of 8 rows (5 labels and a dot each, ~100 bytes a label), up to 20 films and 20
    # channels kept, and the Update button.
    memory: 11000
    domains: [sensor]
    # The films, then the Programmes mode (one entry per channel: prime-time and late programme with their starts), then
    # `date` (the day of the guide) and `updated` (when the script last ran): the tile compares the day with today's.
    attributes: [titles, channels, starts, genres, groups, stale, date, updated, prog_channels, prog_groups, prog1_titles,
                 prog1_starts, prog2_titles, prog2_starts]
    # Offer only a sensor that has these two lists, not every sensor in the house.
    has_attributes: [titles, starts]
    example: tile_example
    # How the editor draws it: the sensor's name and its state (the number of films).
    preview: { title: "{name}", value: "{state}" }
    # Which mode the tile starts in; a tap on the tile changes it.
    options:
      - id: start
        kind: choice
        choices:
          - { value: films, label: start_films }
          - { value: programmes, label: start_programmes }
        default: films
        label: start
        hint: start_hint
```

- [ ] **Step 2: traduzioni** — sostituisci l'intero `translations/it.json`:

```json
{
  "_meta": {
    "name": "Italiano"
  },
  "screen": {
    "header": "Film stasera",
    "none": "Nessun altro film stasera",
    "waiting": "In attesa della guida",
    "choose_sensor": "Scegli il sensore dei film",
    "old": "Guida vecchia",
    "refresh": "Aggiorna",
    "refreshing": "Aggiorno...",
    "not_allowed": "Azioni non consentite",
    "no_data": "In attesa della guida",
    "old_day": "Guida di ieri",
    "programmes": "Programmi",
    "none_programmes": "Nessun programma stasera"
  },
  "app": {
    "name": "Film stasera",
    "summary": "I film in TV stasera in Italia, da un sensore di Home Assistant.",
    "tile_name": "Film stasera",
    "tile_example": "21:00 Cine34 - un film",
    "start": "Modalita' iniziale",
    "start_hint": "Un tocco sul tile cambia modalita'.",
    "start_films": "Film",
    "start_programmes": "Programmi"
  }
}
```

e l'intero `translations/en.json`:

```json
{
  "_meta": {
    "name": "English"
  },
  "screen": {
    "header": "Films tonight",
    "none": "No more films tonight",
    "waiting": "Waiting for the guide",
    "choose_sensor": "Choose the film sensor",
    "old": "Old guide",
    "refresh": "Update",
    "refreshing": "Updating...",
    "not_allowed": "Actions not allowed",
    "no_data": "Waiting for the guide",
    "old_day": "Yesterday's guide",
    "programmes": "Programmes",
    "none_programmes": "No programmes tonight"
  },
  "app": {
    "name": "Films tonight",
    "summary": "The films on Italian TV tonight, from a sensor in Home Assistant.",
    "tile_name": "Films tonight",
    "tile_example": "21:00 Cine34 - a film",
    "start": "Start mode",
    "start_hint": "A tap on the tile changes the mode.",
    "start_films": "Films",
    "start_programmes": "Programmes"
  }
}
```

- [ ] **Step 3: anteprima** — sostituisci l'intero `preview.yaml` (esempi: Film com'è, Programmi, Programmi a pagine, guida di ieri, senza valore, guida vecchia, nessun film, senza sensore; `date` è un giorno intero, come lo manda HA):

```yaml
# What tools/preview.py shows (docs/PREVIEW.md of the plugins repository): the sensor of tonight's films, as Home
# Assistant has it, with a film that has started and the ones after it; the same sensor in the Programmes mode (and a
# small tile, where the channels turn pages); a guide that is old; no film left; yesterday's guide and a sensor
# without a value (both with the Update button); and the tile before a sensor is chosen. Moments are made from the time of the render ("{epoch+25m}" is in 25 minutes).
time_zone: Europe/Rome

tiles:
  - tile: films
    name: Film stasera
    entity: sensor.film_stasera
  - tile: films
    name: Programmi
    entity: sensor.film_stasera
    options: { start: programmes }
  - tile: films
    name: Programmi a pagine
    entity: sensor.film_stasera
    options: { start: programmes }
    sizes: [2x2]
  - tile: films
    name: Guida di ieri
    entity: sensor.film_ieri
    sizes: [2x2, 4x4]
  - tile: films
    name: Senza valore
    entity: sensor.film_senza_valore
    sizes: [1x1, 2x2]
  - tile: films
    name: Guida vecchia
    entity: sensor.film_vecchia
    sizes: [2x2, 4x4]
  - tile: films
    name: Nessun film
    entity: sensor.film_vuoto
    sizes: [2x2, 4x4]
  - tile: films
    name: Senza sensore
    sizes: [4x4]

states:
  sensor.film_stasera:
    state: "16"
    attributes:
      friendly_name: Film stasera
      stale: false
      date: "{now}"
      updated: "{epoch-5m}"
      titles:
        - Point Break - Punto di rottura
        - La giuria
        - The Italian Job
        - Il club delle prime mogli
        - Maigret e le lettere anonime
        - The Gentleman
        - Fuochi d'artificio
        - I laureati
        - Non siamo soli (2022)
        - Poirot: La parola alla difesa
        - Giustizia a tutti i costi
        - Nightmare - Dal Profondo della notte
        - Palermo Milano - Solo andata
        - No Sudden Move
        - Io prima di te
        - Stag. 2026 - Sul cammino di Francesco - La vita di Biagio Conte
      channels: [Iris, Rai Movie, "20", La7, Top Crime, Rai 4, Cine34, NOVE, Rai 4, Top Crime, "20", Italia 2, Rai Movie, Iris, TV8, Rai 1]
      groups: [2, 1, 2, 4, 2, 1, 2, 3, 1, 2, 2, 2, 1, 2, 4, 1]
      starts:
        - "{epoch-40m}"
        - "{epoch+10m}"
        - "{epoch+25m}"
        - "{epoch+1h}"
        - "{epoch+75m}"
        - "{epoch+90m}"
        - "{epoch+105m}"
        - "{epoch+2h}"
        - "{epoch+135m}"
        - "{epoch+150m}"
        - "{epoch+165m}"
        - "{epoch+3h}"
        - "{epoch+195m}"
        - "{epoch+210m}"
        - "{epoch+4h}"
        - "{epoch+270m}"
      genres: [Poliziesco, Thriller, Azione, Commedia, Poliziesco, "", Commedia, Commedia, "", Thriller, Drammatico, Horror, "", Poliziesco, Drammatico, Biografico]
      prog_channels: ["Rai 1", "Rai 2", "Rai 3", "Rete 4", "Canale 5", "Italia 1", "La7", "TV8", "20", "Rai 4", "Iris", "Rai Movie", "Cine34", "Focus", "Top Crime", "Italia 2"]
      prog_groups: [1, 1, 1, 2, 2, 2, 4, 4, 2, 1, 2, 1, 2, 2, 2, 2]
      prog1_titles:
        - "I casi di Teresa Battaglia"
        - "Formidabile! 2026"
        - "Lo stato delle cose"
        - "Quarta Repubblica"
        - "Grande Fratello Vip"
        - "Retribution"
        - "La torre di Babele"
        - "Assassinio sull'Orient Express"
        - "The Suicide Squad"
        - "Striking Rescue"
        - "Gangs of New York"
        - "Per qualche dollaro in piu'"
        - "Odio l'estate"
        - "Treasures with Bettany Hughes"
        - "C.S.I. Miami"
        - "One Piece"
      prog1_starts: ["{epoch+60m}", "{epoch+70m}", "{epoch+80m}", "{epoch+90m}", "{epoch+100m}", "{epoch+110m}", "{epoch+120m}", "{epoch+130m}", "{epoch+140m}", "{epoch+150m}", "{epoch+160m}", "{epoch+170m}", "{epoch+180m}", "{epoch+190m}", "{epoch+200m}", "{epoch+210m}"]
      prog2_titles:
        - "Cose Nostre"
        - "Il Processo del Lunedi'"
        - "Tg3 Linea Notte"
        - "Achille Lauro: la crociera del terrore"
        - "Tg5"
        - "Cold Case - Delitti irrisolti"
        - "Ep. 2"
        - "The Equalizer 2 - Senza perdono"
        - "The Italian Job"
        - "Elyas"
        - "Anna dei mille giorni"
        - "Il grande silenzio"
        - "Ferie d'Agosto"
        - "Predatori e prede"
        - "C.S.I. Miami"
        - ""
      prog2_starts: ["{epoch+240m}", "{epoch+252m}", "{epoch+264m}", "{epoch+276m}", "{epoch+288m}", "{epoch+300m}", "{epoch+312m}", "{epoch+324m}", "{epoch+336m}", "{epoch+348m}", "{epoch+360m}", "{epoch+372m}", "{epoch+384m}", "{epoch+396m}", "{epoch+408m}", 0]
  sensor.film_vecchia:
    state: "2"
    attributes:
      friendly_name: Film stasera
      stale: true
      date: "{now}"
      updated: "{epoch-3h}"
      titles: [La giuria, The Gentleman]
      channels: [Rai Movie, Rai 4]
      groups: [1, 1]
      starts: ["{epoch+30m}", "{epoch+80m}"]
      genres: [Thriller, ""]
  sensor.film_vuoto:
    state: "0"
    attributes:
      friendly_name: Film stasera
      stale: false
      date: "{now}"
      updated: "{epoch-5m}"
      titles: []
      channels: []
      starts: []
      genres: []
  sensor.film_ieri:
    state: "12"
    attributes:
      friendly_name: Film stasera
      stale: false
      date: "{now-1d}"
      updated: "{epoch-1d}"
      titles: [La giuria, The Gentleman]
      channels: [Rai Movie, Rai 4]
      groups: [1, 1]
      starts: ["{epoch-20h}", "{epoch-19h}"]
      genres: [Thriller, ""]
  sensor.film_senza_valore:
    state: unavailable
    attributes:
      friendly_name: Film stasera
```

- [ ] **Step 4: changelog** — in cima a `CHANGELOG.md` (sopra `## 0.2.1`) metti:

```markdown
## 0.3.0 - 2026-10-12
- A second mode, Programmes: for each channel, in the order of the remote, the prime-time programme and the late one,
  each with its time. A tap on the tile changes between Films and Programmes; the tile option "Start mode" says which
  one it starts in. When the channels do not fit, the page turns by itself every 8 seconds.
- When there is no data (the sensor has no value, or its guide is not today's) the tile says so and shows an Update
  button: a tap asks Home Assistant to update the sensor, which runs the script that fetches the guide. The screen must
  be allowed to perform Home Assistant actions.
- Needs the 0.3 version of the script `film-stasera-ha` (the sensor's new attributes `prog_*`); without them the Films
  mode works as before and the Programmes mode says there are no programmes.
- The tile asks for a little more room in the screen's layout memory (11000 bytes).
```

(il file deve restare con `# Changelog` come prima riga e `## 0.3.0 - 2026-10-12` come prima sezione.)

- [ ] **Step 5: verifica**

Run: `cd ~/tessera-film-stasera && python3 -I ~/tessera-plugins/tools/check.py . | tail -4`
Expected: `: ok ...`, `needs: ok`, `plugin API 0.9: 1 checked`, nessun errore (se c'è `its first heading is ...` il changelog non è in cima).

- [ ] **Step 6: commit**

```bash
cd ~/tessera-film-stasera && git add tessera-plugin.yaml translations preview.yaml CHANGELOG.md && git commit -q -F - <<'EOF'
Plugin 0.3.0: manifest, traduzioni, anteprima e changelog

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Il tile con le due modalità e il pulsante Aggiorna (plugin)

**Files:**
- Modify: `~/tessera-film-stasera/components/film_stasera/film_stasera.cpp` (sostituisci l'intero file)

**Interfaces:**
- Consumes: `logic.h` (task 5) e gli attributi/opzione/testi del task 6; API Tessera `tessera::action`, `tessera::days_from_today`, `tessera::clock_text`, `tessera::date_text`.
- Produces: il tile `films` con modalità Film (invariata) e Programmi, tocco che alterna le modalità o, senza dati, lancia l'aggiornamento.

Note dal bench (già verificate): un attributo `date` arriva come numero; i blocchi senza gruppo si nascondono con `LV_OBJ_FLAG_HIDDEN` (altrimenti il bench li segnala sovrapposti al pulsante); il pulsante è una sola etichetta con sfondo arrotondato, impostato anche alla creazione e non solo in `on_theme`.

- [ ] **Step 1: scrivi il file** — sostituisci tutto `components/film_stasera/film_stasera.cpp` con:

```cpp
#include "film_stasera.h"
#include "logic.h"
#include <algorithm>
#include <climits>
#include <string>
#include <vector>

namespace esphome::film_stasera {

using tessera::Font;
namespace ui = tessera::ui;

// One film as Home Assistant's sensor has it: four lists of the same length, one entry per film (README.md).
struct Film {
  std::string title, channel, genre;
  uint32_t at = 0;   // when it starts, seconds since 1970
  int group = 0;     // the channel's group (1 to 4, 0 for none): the colour of the dot before its name
};

// One channel of the Programmes mode: the prime-time programme and the late one, each with its start (0 = none).
// Six lists of the same length, one entry per channel (README.md).
struct Show {
  std::string channel, title1, title2;
  uint32_t at1 = 0, at2 = 0;
  int group = 0;
};

// A film that started less than this long ago is still on, so it stays on the tile. The guide has no end times.
static constexpr uint32_t ON_AIR_SECONDS = 150 * 60;
static constexpr int MAX_PER_COLUMN = 8;
static constexpr size_t MAX_FILMS = 20;
static constexpr size_t MAX_SHOWS = 20;
static constexpr int PAGE_SECONDS = 8;           // the Programmes mode turns its page this often
static constexpr uint32_t BUSY_SECONDS = 90;     // "Updating..." lasts at most this long
static constexpr uint32_t DENIED_SECONDS = 5;    // "Actions not allowed" shows this long

// The tile has two modes, and a tap on it changes the mode. Films: a header (its name and the date), then one row per
// film as many as fit. A row has the start time on the left; beside it the title, and under the title the channel's
// name with a dot in the colour of its group (Rai, Mediaset...) and the genre. A film that has already started shows
// its time in the accent. Programmes: a header (its name and "Programmes"), then one block per channel in the order of
// the remote: the channel on the left, and on its right two lines, the prime-time programme with its time and the late
// one with its time. When the channels do not fit the page turns by itself. A tile at least WIDE_MM wide is split into
// two columns that fill one after the other. The sensor changes a few times a day, the clock every second: only a text
// that changes is set again.
// Without data (no value, or a guide that is not today's) the tile says so and shows an Update button: a tap asks Home
// Assistant to update the sensor, which runs the script that fetches the guide.
class FilmsTile : public tessera::Tile {
 public:
  explicit FilmsTile(const tessera::Plugin *plugin) : plugin_(plugin) {}

  void create(const tessera::TileContext &c) override {
    width_ = c.width;
    height_ = c.height;
    name_ = c.name;
    entity_ = c.entity;
    mode_ = std::string(c.options["start"] | "films") == "programmes" ? Mode::PROGRAMMES : Mode::FILMS;
    gap_ = ui::px(ui::large() ? 8 : 5);
    line_ = std::max(ui::line_height(Font::TITLE), ui::line_height(Font::BODY_LARGE));
    row_h_ = line_ + ui::line_height(Font::BODY);
    // The header only where at least two rows still fit under it.
    const int head = ui::line_height(Font::TITLE) + gap_;
    const int step = row_h_ + gap_;
    has_head_ = (height_ - head + gap_) / step >= 2;
    top_ = has_head_ ? head : 0;
    // Wide: two columns, by the glass's own size, so a 4-column tile of a 7-inch screen splits and a narrow one does not.
    columns_ = width_ >= ui::mm(130) ? 2 : 1;
    col_gap_ = ui::px(ui::large() ? 28 : 18);
    col_w_ = (width_ - (columns_ - 1) * col_gap_) / columns_;
    const int fit = (height_ - top_ + gap_) / step;
    per_column_ = std::max(1, std::min(MAX_PER_COLUMN, fit));
    rows_.resize(static_cast<size_t>(per_column_ * columns_));
    for (size_t i = 0; i < rows_.size(); ++i) {
      const int col = static_cast<int>(i) / per_column_, r = static_cast<int>(i) % per_column_;
      make_row(rows_[i], c.parent, col * (col_w_ + col_gap_), top_ + r * step);
    }
    if (has_head_) {
      head_ = ui::label(c.parent, Font::TITLE, theme::INK);
      head_note_ = ui::label(c.parent, Font::BODY, theme::MUTED);
    }
    // The Update button: one label with a rounded fill of its own, hidden until there is no data.
    btn_text_ = ui::label(c.parent, Font::TITLE, theme::INK);
    lv_obj_set_style_radius(btn_text_, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(btn_text_, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(btn_text_, ui::color(theme::BUTTON), 0);
    lv_obj_set_style_text_align(btn_text_, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_add_flag(btn_text_, LV_OBJ_FLAG_HIDDEN);
  }

  void on_state(JsonObjectConst data) override {
    films_.clear();
    shows_.clear();
    JsonObjectConst a = data["attributes"];
    JsonArrayConst titles = a["titles"].as<JsonArrayConst>();
    JsonArrayConst channels = a["channels"].as<JsonArrayConst>();
    JsonArrayConst starts = a["starts"].as<JsonArrayConst>();
    JsonArrayConst genres = a["genres"].as<JsonArrayConst>();
    JsonArrayConst groups = a["groups"].as<JsonArrayConst>();
    for (size_t i = 0; i < titles.size() && films_.size() < MAX_FILMS; ++i) {
      Film f;
      f.title = std::string(titles[i] | "");
      f.channel = std::string(channels[i] | "");
      f.genre = std::string(genres[i] | "");
      f.at = starts[i] | 0u;
      f.group = groups[i] | 0;
      if (f.at && !f.title.empty()) films_.push_back(std::move(f));
    }
    std::sort(films_.begin(), films_.end(), [](const Film &x, const Film &y) { return x.at < y.at; });
    JsonArrayConst p_channels = a["prog_channels"].as<JsonArrayConst>();
    JsonArrayConst p_groups = a["prog_groups"].as<JsonArrayConst>();
    JsonArrayConst p1_titles = a["prog1_titles"].as<JsonArrayConst>();
    JsonArrayConst p1_starts = a["prog1_starts"].as<JsonArrayConst>();
    JsonArrayConst p2_titles = a["prog2_titles"].as<JsonArrayConst>();
    JsonArrayConst p2_starts = a["prog2_starts"].as<JsonArrayConst>();
    for (size_t i = 0; i < p_channels.size() && shows_.size() < MAX_SHOWS; ++i) {
      Show s;
      s.channel = std::string(p_channels[i] | "");
      s.group = p_groups[i] | 0;
      s.title1 = std::string(p1_titles[i] | "");
      s.at1 = p1_starts[i] | 0u;
      s.title2 = std::string(p2_titles[i] | "");
      s.at2 = p2_starts[i] | 0u;
      if (!s.channel.empty() && (s.at1 || s.at2)) shows_.push_back(std::move(s));
    }
    // Before a person has chosen the sensor the tile gets {}; a sensor without a value says unavailable or unknown.
    has_entity_ = !data["state"].isNull();
    const std::string state = std::string(data["state"] | "");
    no_value_ = state == "unavailable" || state == "unknown";
    stale_ = a["stale"] | false;
    // The app turns an attribute named ...date into seconds since 1970: the sensor's `date` is midnight of the guide's day.
    date_epoch_ = a["date"] | 0u;
    updated_ = a["updated"] | 0u;
    wait_ = std::string(data["wait"] | "");
  }

  void on_tick(uint32_t now) override {
    now_ = now;
    const bool programmes = mode_ == Mode::PROGRAMMES;
    // What is still worth showing of the films: not over yet. The list comes in order of start.
    std::vector<const Film *> films;
    for (const auto &f : films_)
      if (now && f.at + ON_AIR_SECONDS >= now) films.push_back(&f);

    Situation s;
    s.has_entity = has_entity_;
    s.wrong_entity = wait_ == "wrong_entity";
    s.waiting = !wait_.empty() && !s.wrong_entity;
    s.no_value = no_value_;
    s.clock_set = now != 0;
    s.day_offset = now && date_epoch_ ? tessera::days_from_today(date_epoch_) : INT32_MIN;
    s.shown = static_cast<int>(programmes ? shows_.size() : films.size());
    view_ = resolve_view(s);

    pages_ = programmes && view_ == View::LIST ? page_count(static_cast<int>(shows_.size()), static_cast<int>(rows_.size())) : 0;
    page_ = page_for(now, pages_, PAGE_SECONDS);

    const char *message = nullptr;
    switch (view_) {
      case View::CHOOSE_SENSOR: message = "choose_sensor"; break;
      case View::WAITING: message = "waiting"; break;
      case View::NO_DATA: message = "no_data"; break;
      case View::OLD_GUIDE: message = "old_day"; break;
      case View::EMPTY: message = programmes ? "none_programmes" : "none"; break;
      case View::LIST: break;
    }
    const bool button = view_ == View::NO_DATA || view_ == View::OLD_GUIDE;
    paint_head(now);
    paint_button(button);
    if (message)
      show_message(plugin_->text(message), button);
    else if (programmes)
      show_shows();
    else
      show_films(films, now);
  }

  // A tap: Update where there is no data, otherwise the other mode.
  void on_tap() override {
    switch (view_) {
      case View::NO_DATA:
      case View::OLD_GUIDE:
        refresh();
        break;
      case View::EMPTY:
      case View::LIST:
        mode_ = mode_ == Mode::FILMS ? Mode::PROGRAMMES : Mode::FILMS;
        on_tick(now_);
        break;
      default:
        break;
    }
  }

  void on_theme() override {
    if (head_) ui::set_color(head_, theme::INK);
    if (head_note_) ui::set_color(head_note_, theme::MUTED);
    lv_obj_set_style_bg_color(btn_text_, ui::color(theme::BUTTON), 0);
    ui::set_color(btn_text_, theme::INK);
    for (auto &r : rows_) {
      ui::set_color(r.when, r.on_air ? theme::ACCENT : theme::INK);
      ui::set_color(r.title, theme::INK);
      ui::set_color(r.chan, theme::INK);
      ui::set_color(r.when2, theme::MUTED);
      ui::set_color(r.sub, theme::MUTED);
      paint_dot(r);
    }
  }

 private:
  struct Row {
    lv_obj_t *when{}, *title{}, *dot{}, *chan{}, *sub{}, *when2{};
    int x = 0, y = 0, group = 0;
    bool on_air = false;
  };

  void make_row(Row &r, lv_obj_t *parent, int x, int y) {
    r.x = x;
    r.y = y;
    r.when = ui::label(parent, Font::TITLE, theme::INK);
    r.title = ui::label(parent, Font::BODY_LARGE, theme::INK);
    r.dot = ui::block(parent, theme::MARK_BLUE);
    r.chan = ui::label(parent, Font::BODY, theme::INK);
    r.sub = ui::label(parent, Font::BODY, theme::MUTED);
    r.when2 = ui::label(parent, Font::BODY, theme::MUTED);
  }

  // The colour of a group's dot: the four colours of the Tessera mark, the same in both looks. No group: no dot.
  static theme::Role group_role(int group) {
    switch (group) {
      case 1: return theme::MARK_BLUE;
      case 2: return theme::MARK_AMBER;
      case 3: return theme::MARK_GREEN;
      default: return theme::MARK_PURPLE;
    }
  }
  // A row without a group has no dot at all (hidden, so it cannot lie under another part).
  void paint_dot(Row &r) {
    if (r.group <= 0) {
      lv_obj_add_flag(r.dot, LV_OBJ_FLAG_HIDDEN);
      return;
    }
    lv_obj_remove_flag(r.dot, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_bg_color(r.dot, ui::color(group_role(r.group)), 0);
  }

  // Ask Home Assistant to update the sensor: that runs the script. The button says "Updating..." until the sensor's
  // `updated` changes (or BUSY_SECONDS pass), or "Actions not allowed" when the screen may not call Home Assistant.
  void refresh() {
    if (entity_.empty()) return;
    refresh_.updated_at_tap = updated_;
    if (tessera::action("homeassistant.update_entity", entity_))
      refresh_.busy_until = now_ + BUSY_SECONDS;
    else
      refresh_.denied_until = now_ + DENIED_SECONDS;
    on_tick(now_);
  }

  void paint_button(bool visible) {
    if (!visible) {
      ui::set_text(btn_text_, "");
      lv_obj_add_flag(btn_text_, LV_OBJ_FLAG_HIDDEN);
      return;
    }
    const Button b = button_state(refresh_, now_, updated_);
    const std::string text = plugin_->text(b == Button::BUSY ? "refreshing" : b == Button::DENIED ? "not_allowed" : "refresh");
    const int pad = ui::px(ui::large() ? 14 : 9);
    const int text_h = ui::line_height(Font::TITLE);
    const int w = std::min(width_, ui::text_width(text, Font::TITLE) + 2 * pad);
    // Under the message, on the second row; a tile of one row has only the button.
    const int y = top_ + (rows_.size() >= 2 ? row_h_ + gap_ : 0);
    lv_obj_remove_flag(btn_text_, LV_OBJ_FLAG_HIDDEN);
    ui::set_text(btn_text_, text);
    lv_obj_set_style_pad_top(btn_text_, pad / 2, 0);
    lv_obj_set_size(btn_text_, std::max(1, w), text_h + pad);
    lv_obj_set_pos(btn_text_, 0, y);
  }

  // A message on the first row, the rest empty; the button takes the first row alone on a tile of one row.
  void show_message(const std::string &message, bool button) {
    for (size_t i = 0; i < rows_.size(); ++i) {
      if (i == 0 && !(button && rows_.size() < 2))
        place(rows_[0], "", message, nullptr, false, 0, width_);
      else
        place(rows_[i], "", "", nullptr, false, 0, col_w_);
    }
  }

  void show_films(const std::vector<const Film *> &shown, uint32_t now) {
    // One time column as wide as the widest time on the tile, so every title starts at the same place.
    int when_w = 0;
    for (size_t i = 0; i < rows_.size() && i < shown.size(); ++i)
      when_w = std::max(when_w, ui::text_width(tessera::clock_text(shown[i]->at), Font::TITLE));
    when_w += when_w ? ui::px(ui::large() ? 12 : 8) : 0;
    for (size_t i = 0; i < rows_.size(); ++i) {
      if (i >= shown.size()) {
        place(rows_[i], "", "", nullptr, false, 0, col_w_);
      } else {
        const Film &f = *shown[i];
        place(rows_[i], tessera::clock_text(f.at), f.title, &f, f.at <= now, when_w, col_w_);
      }
    }
  }

  // The channels of this page, in order: the widest name and the widest time set the two columns.
  void show_shows() {
    const size_t per_page = rows_.size();
    const size_t first = static_cast<size_t>(page_) * per_page;
    const Font chan_font = col_w_ < ui::mm(70) ? Font::BODY : Font::BODY_LARGE;
    int name_w = 0, when_w = 0;
    for (size_t i = 0; i < per_page && first + i < shows_.size(); ++i) {
      const Show &s = shows_[first + i];
      name_w = std::max(name_w, ui::text_width(s.channel, chan_font));
      if (s.at1) when_w = std::max(when_w, ui::text_width(tessera::clock_text(s.at1), Font::TITLE));
      if (s.at2) when_w = std::max(when_w, ui::text_width(tessera::clock_text(s.at2), Font::BODY));
    }
    const int dot_room = ui::px(ui::large() ? 16 : 12);
    name_w = std::min(name_w + dot_room, col_w_ / 3 + dot_room) + ui::px(ui::large() ? 12 : 8);
    when_w += when_w ? ui::px(ui::large() ? 12 : 8) : 0;
    for (size_t i = 0; i < per_page; ++i)
      place_show(rows_[i], first + i < shows_.size() ? &shows_[first + i] : nullptr, name_w, when_w, chan_font);
  }

  // The time in a column of `when_w`, the title beside it and under the title the channel and the genre (`film`; null for
  // a message, which has only the title), in a row `row_w` wide. A message takes the title's place from the row's left
  // edge. Nothing to show: everything empty.
  void place(Row &r, const std::string &when, const std::string &title, const Film *film, bool on_air, int when_w,
             int row_w) {
    r.on_air = on_air;
    ui::set_text(r.when2, "");
    ui::set_font(r.chan, Font::BODY);
    ui::set_font(r.sub, Font::BODY);
    ui::set_color(r.chan, theme::INK);
    ui::set_color(r.sub, theme::MUTED);
    ui::set_text(r.when, when);
    ui::set_color(r.when, on_air ? theme::ACCENT : theme::INK);
    const int tw = when.empty() ? 0 : when_w;
    lv_obj_set_size(r.when, std::max(1, tw), ui::line_height(Font::TITLE));
    lv_obj_set_pos(r.when, r.x, r.y + (line_ - ui::line_height(Font::TITLE)) / 2);
    const int w = std::max(1, row_w - tw);
    ui::set_text(r.title, title);
    ui::set_color(r.title, theme::INK);
    lv_obj_set_size(r.title, w, ui::line_height(Font::BODY_LARGE));
    lv_obj_set_pos(r.title, r.x + tw, r.y + (line_ - ui::line_height(Font::BODY_LARGE)) / 2);
    // The second line: [dot] Channel . Genre
    const int lh = ui::line_height(Font::BODY), y2 = r.y + line_;
    const std::string channel = film ? film->channel : std::string();
    const std::string genre = film && !film->genre.empty() ? "· " + film->genre : std::string();
    r.group = film ? film->group : 0;
    const int d = std::max(ui::px(7), lh * 6 / 10);
    const int dot_w = r.group > 0 ? d + ui::px(6) : 0;
    paint_dot(r);
    lv_obj_set_size(r.dot, std::max(1, d), std::max(1, d));
    lv_obj_set_pos(r.dot, r.x + tw, y2 + (lh - d) / 2);
    const int chan_w = std::min(w - dot_w, channel.empty() ? 0 : ui::text_width(channel, Font::BODY) + ui::px(2));
    ui::set_text(r.chan, channel);
    lv_obj_set_size(r.chan, std::max(1, chan_w), lh);
    lv_obj_set_pos(r.chan, r.x + tw + dot_w, y2);
    const int gx = dot_w + (chan_w > 0 ? chan_w + ui::px(6) : 0);
    ui::set_text(r.sub, genre);
    lv_obj_set_size(r.sub, std::max(1, w - gx), lh);
    lv_obj_set_pos(r.sub, r.x + tw + gx, y2);
  }

  // A channel of the Programmes mode (null: an empty block). On the left the dot and the channel's name, in the middle of
  // the block; on the right two lines: the first with its time and title, the second (smaller, muted) with its time and
  // title. A programme that is missing shows a dash.
  void place_show(Row &r, const Show *s, int name_w, int when_w, Font chan_font) {
    r.on_air = false;
    r.group = s ? s->group : 0;
    const int lh = ui::line_height(Font::BODY), y2 = r.y + line_, block_h = line_ + lh;
    const int d = std::max(ui::px(7), lh * 6 / 10);
    const int dot_w = r.group > 0 ? d + ui::px(6) : 0;
    paint_dot(r);
    lv_obj_set_size(r.dot, std::max(1, d), std::max(1, d));
    lv_obj_set_pos(r.dot, r.x, r.y + (block_h - d) / 2);
    const int chan_h = ui::line_height(chan_font);
    ui::set_font(r.chan, chan_font);
    ui::set_color(r.chan, theme::INK);
    ui::set_text(r.chan, s ? s->channel : std::string());
    lv_obj_set_size(r.chan, std::max(1, name_w - dot_w), chan_h);
    lv_obj_set_pos(r.chan, r.x + dot_w, r.y + (block_h - chan_h) / 2);
    const int x = r.x + (s ? name_w : 0);
    const int tw = std::max(1, col_w_ - (s ? name_w : 0) - when_w);
    // Line 1: the prime-time programme.
    ui::set_text(r.when, s && s->at1 ? tessera::clock_text(s->at1) : std::string());
    ui::set_color(r.when, theme::INK);
    lv_obj_set_size(r.when, std::max(1, when_w), ui::line_height(Font::TITLE));
    lv_obj_set_pos(r.when, x, r.y + (line_ - ui::line_height(Font::TITLE)) / 2);
    ui::set_text(r.title, !s ? std::string() : s->at1 ? s->title1 : std::string("—"));
    ui::set_color(r.title, theme::INK);
    lv_obj_set_size(r.title, tw, ui::line_height(Font::BODY_LARGE));
    lv_obj_set_pos(r.title, x + when_w, r.y + (line_ - ui::line_height(Font::BODY_LARGE)) / 2);
    // Line 2: the late programme.
    ui::set_font(r.sub, Font::BODY);
    ui::set_text(r.when2, s && s->at2 ? tessera::clock_text(s->at2) : std::string());
    ui::set_color(r.when2, theme::MUTED);
    lv_obj_set_size(r.when2, std::max(1, when_w), lh);
    lv_obj_set_pos(r.when2, x, y2);
    ui::set_text(r.sub, !s ? std::string() : s->at2 ? s->title2 : std::string("—"));
    ui::set_color(r.sub, theme::MUTED);
    lv_obj_set_size(r.sub, tw, lh);
    lv_obj_set_pos(r.sub, x + when_w, y2);
  }

  // The tile's name on the left; on the right the date (films), or "Programmes" and the page (programmes), or that the
  // guide is old.
  void paint_head(uint32_t now) {
    if (!head_) return;
    std::string note;
    if (stale_) {
      note = plugin_->text("old");
    } else if (mode_ == Mode::PROGRAMMES) {
      note = plugin_->text("programmes");
      if (pages_ > 1) note += " " + std::to_string(page_ + 1) + "/" + std::to_string(pages_);
    } else if (now) {
      note = tessera::date_text(now);
    }
    const int note_w = note.empty() ? 0 : ui::text_width(note, Font::BODY) + ui::px(2);
    const std::string title = name_.empty() ? plugin_->text("header") : name_;
    ui::set_text(head_, title);
    lv_obj_set_size(head_, std::max(1, width_ - note_w - (note_w ? ui::px(8) : 0)), ui::line_height(Font::TITLE));
    lv_obj_set_pos(head_, 0, 0);
    ui::set_text(head_note_, note);
    lv_obj_set_size(head_note_, std::max(1, note_w), ui::line_height(Font::BODY));
    lv_obj_set_pos(head_note_, width_ - note_w, (ui::line_height(Font::TITLE) - ui::line_height(Font::BODY)) / 2);
    lv_obj_set_style_text_align(head_note_, LV_TEXT_ALIGN_RIGHT, 0);
  }

  const tessera::Plugin *plugin_;
  int width_ = 0, height_ = 0, gap_ = 0, line_ = 0, row_h_ = 0, top_ = 0;
  int columns_ = 1, col_gap_ = 0, col_w_ = 0, per_column_ = 1;
  bool has_head_ = false, has_entity_ = false, no_value_ = false, stale_ = false;
  std::string name_, wait_, entity_;
  std::vector<Row> rows_;
  lv_obj_t *head_{}, *head_note_{}, *btn_text_{};
  std::vector<Film> films_;
  std::vector<Show> shows_;
  Mode mode_ = Mode::FILMS;
  View view_ = View::WAITING;
  Refresh refresh_;
  uint32_t now_ = 0, date_epoch_ = 0, updated_ = 0;
  int page_ = 0, pages_ = 0;
};

void FilmStasera::setup() {
  // The id is the tile's id in the manifest; the core makes a FilmsTile for every card that shows one.
  add_tile("films", [this]() { return new FilmsTile(this); });
}

}  // namespace esphome::film_stasera
```

- [ ] **Step 2: bench su tutti gli schermi** (circa 5 minuti: dagli la finestra di tempo, o lanciali in background e aspetta)

Run: `cd ~/tessera-film-stasera && python3 -I ~/tessera-plugins/tools/preview.py . --strict 2>&1 | tail -6`
Expected: `4 of 4 screens rendered, 0 warnings`. Se compaiono avvisi, leggi `.preview/summary.json` (campo `findings`, livello `warning`) e correggi **solo** quello che segnalano: i messaggi `info` ("not on a 2 x 3 grid...") sono normali.

- [ ] **Step 3: guarda le immagini** — apri `.preview/overview.png` e controlla: modalità Film uguale a prima; Programmi con canale a sinistra e due righe a destra; intestazione `Programmi 1/3` sul tile a pagine; i tile "Guida di ieri" e "Senza valore" con messaggio e pulsante rotondo; il tile 1×1 senza valore con il solo pulsante.

- [ ] **Step 4: commit** (`.preview/` non va nel repository: se `git status` lo mostra, aggiungi `.preview/` a `.gitignore`)

```bash
cd ~/tessera-film-stasera && git status -s | head -5 && git add components/film_stasera/film_stasera.cpp .gitignore 2>/dev/null; git commit -q -F - <<'EOF'
Tile: modalita' Programmi, tocco per cambiare modalita', pulsante Aggiorna senza dati

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: README del plugin

**Files:**
- Modify: `~/tessera-film-stasera/README.md`, `README.it.md`

- [ ] **Step 1: aggiungi la sezione in inglese** in fondo a `README.md`:

```bash
cd ~/tessera-film-stasera && cat >> README.md <<'EOF'

## Modes and the Update button

The tile has two modes. **Films** (the default) lists tonight's films. **Programmes** lists, for each channel in the
order of the remote, the prime-time programme and the late one, each with its time; when the channels do not fit, the
page turns by itself every 8 seconds. A tap on the tile changes the mode; the tile option "Start mode" says which one it
starts in.

When there is no data (the sensor has no value, or its guide is not today's) the tile says so and shows an **Update**
button. A tap asks Home Assistant to update the sensor, which runs the script that fetches the guide. The screen must be
allowed to perform Home Assistant actions.

The sensor needs the attributes `prog_channels`, `prog_groups`, `prog1_titles`, `prog1_starts`, `prog2_titles` and
`prog2_starts` for the Programmes mode: they come with the 0.3 version of the script `film-stasera-ha`. The app sends a
tile at most 2600 bytes: on an evening with many films the lists are cut to the same length.
EOF
```

- [ ] **Step 2: la stessa in italiano** in fondo a `README.it.md`:

```bash
cd ~/tessera-film-stasera && cat >> README.it.md <<'EOF'

## Modalità e pulsante Aggiorna

Il tile ha due modalità. **Film** (quella di partenza) elenca i film di stasera. **Programmi** elenca, per ogni canale in
ordine di numero del telecomando, il programma di prima serata e quello di seconda serata, ognuno con il suo orario;
quando i canali non entrano, la pagina cambia da sola ogni 8 secondi. Un tocco sul tile cambia modalità; l'opzione
"Modalità iniziale" dice da quale parte.

Quando mancano i dati (il sensore non ha un valore, o la sua guida non è di oggi) il tile lo dice e mostra un pulsante
**Aggiorna**. Un tocco chiede a Home Assistant di aggiornare il sensore, cioè di lanciare lo script che scarica la guida.
Lo schermo deve poter eseguire azioni di Home Assistant.

Per i Programmi il sensore ha bisogno degli attributi `prog_channels`, `prog_groups`, `prog1_titles`, `prog1_starts`,
`prog2_titles` e `prog2_starts`: arrivano con la versione 0.3 dello script `film-stasera-ha`. L'app manda a ogni tile al
massimo 2600 byte: in una serata con molti film le liste vengono tagliate alla stessa lunghezza.
EOF
```

- [ ] **Step 3: verifica e commit**

```bash
cd ~/tessera-film-stasera && python3 -I ~/tessera-plugins/tools/check.py . | tail -3 && git add README.md README.it.md && git commit -q -F - <<'EOF'
README: modalita', pulsante Aggiorna e attributi del sensore

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: Sul 7B (serve l'utente)

**Files:**
- Nessun file del repository: compila `~/espscreen/checkout/waveshare7b.yaml` (include già `~/tessera-film-stasera` da `waveshare7b.plugins.yaml`) e copia il plugin in HA.

**Interfaces:**
- Consumes: plugin 0.3.0 (task 5–8) e sensore con `prog_*` (task 4).

**Prima di cominciare: chiedi il via all'utente per l'OTA** (il 7B si riavvia per circa un minuto e il touch a volte non risponde: servono 1–3 riavvii; rollback in `~/backup-7b-2026-10-11/`).

- [ ] **Step 1: compila** (circa 5 minuti, in background)

Run: `cd ~/espscreen && ~/esphome/esphome-tessera/bin/esphome compile checkout/waveshare7b.yaml 2>&1 | tail -6`
Expected: `Successfully compiled program.` e un'occupazione di RAM e flash simile a prima (RAM ~43 %, flash ~33 %).

- [ ] **Step 2: copia il plugin in HA** (così l'editor di Tessera conosce l'opzione e gli attributi nuovi)

```bash
cd ~/tessera-film-stasera && tar --exclude=.git --exclude=.preview --exclude=__pycache__ --exclude=tests -cf - . \
  | ssh -o BatchMode=yes root@100.116.129.24 "mkdir -p /homeassistant/tessera-plugins/film_stasera && tar -xf - -C /homeassistant/tessera-plugins/film_stasera && grep -n '^version' /homeassistant/tessera-plugins/film_stasera/tessera-plugin.yaml"
```

Expected: `version: 0.3.0`.

- [ ] **Step 3: OTA e controllo del touch**

```bash
cd ~/espscreen && ~/esphome/esphome-tessera/bin/esphome upload checkout/waveshare7b.yaml --device 192.168.0.16 2>&1 | tail -3
until ping -c1 -W1 192.168.0.16 >/dev/null 2>&1; do sleep 2; done; sleep 25
timeout 40 ~/esphome/esphome-tessera/bin/esphome logs checkout/waveshare7b.yaml --device 192.168.0.16 2>&1 | grep -i -E 'FAILED|Calibration|short of memory' | head
```

Expected: `OTA successful`; nel log nessun `FAILED`/`Calibration`/`short of memory`. Se compare `touchscreen is marked FAILED`, riavvia con `switch.my_waveshare_7b_restart` (fino a 3 volte).

- [ ] **Step 4: nell'editor di Tessera** (lo fa l'utente) — Ctrl+Shift+R; il tile "Film stasera" già nel layout va **eliminato e riaggiunto** (sono cambiati `attributes` e `memory`); scegli `sensor.film_stasera`; controlla l'opzione "Modalità iniziale".

- [ ] **Step 5: prove sul 7B** — con l'utente: (a) il tile parte in Film come prima; (b) un tocco passa a Programmi e l'intestazione dice "Programmi"; (c) con più pagine la pagina cambia ogni ~8 secondi e il numero sale; (d) un altro tocco torna a Film; (e) per vedere il pulsante, in HA metti `sensor.film_stasera` fuori servizio o cancella la cache (`/homeassistant/film_stasera/film_stasera_cache.json`) e aspetta: compare "In attesa della guida" + Aggiorna; un tocco dice "Aggiorno..." e dopo qualche secondo ricompaiono i dati; se lo schermo non è autorizzato alle azioni di HA compare "Azioni non consentite" (Impostazioni → Dispositivi → ESPHome → CONFIGURA → "Allow the device to perform Home Assistant actions"). **Prima del punto (e) fai una copia della cache** e rimettila se serve.

- [ ] **Step 6: se qualcosa non va** — torna indietro con `~/backup-7b-2026-10-11/` (vedi `project_tessera_7b` in memoria) e riporta cosa è successo.

---

### Task 10: Rilascio (solo dopo il via dell'utente)

**Files:**
- Nessuna modifica: push, tag e release.

**Prima di cominciare: chiedi il via all'utente** (pubblica su GitHub, repository pubblici).

- [ ] **Step 1: script e package** (`film-stasera-ha`)

```bash
cd ~/film-stasera && python3 -m unittest discover -s tests 2>&1 | tail -3 && git status -sb | head -3 && git push origin main
```

Expected: `OK` e il push riuscito (il commit della specifica e del piano parte con questo).

- [ ] **Step 2: plugin** (`tessera-film-stasera`) — controllo finale, tag, release

```bash
cd ~/tessera-film-stasera && python3 -I ~/tessera-plugins/tools/check.py . | tail -2 && git status -sb | head -3
git push origin main && git tag v0.3.0 && git push origin v0.3.0
gh release create v0.3.0 -R alexcoscia/tessera-film-stasera --title 0.3.0 --notes "Modalità Programmi (prima e seconda serata di ogni canale, un tocco cambia modalità) e pulsante Aggiorna quando mancano i dati. Serve la versione 0.3 dello script film-stasera-ha. Vedi CHANGELOG.md."
```

Expected: release `v0.3.0` creata; il catalogo Community la prende da solo entro un'ora.

- [ ] **Step 3: immagine della scheda (facoltativa)** — la prima immagine di `preview.yaml` è ancora quella dei film, quindi `store.png` non cambia in modo visibile. Se l'utente vuole l'immagine con i Programmi, sposta in cima a `preview.yaml` il tile "Programmi", `python3 ~/tessera-plugins/tools/store_image.py .`, guardala e pubblica una 0.3.1.

- [ ] **Step 4: aggiorna le note in memoria** (`project_film_stasera.md`): modalità Programmi, budget di 2600 byte per tile, `date` come numero, regola della cache senza `prog_*`.

---

## Verifica finale del piano (rilettura)

- Specifica → task: fasce e ordine (1), estrazione (2), attributi/cache/dimensione (3), messa in opera e prova sulla guida vera (4), logica di modalità/stato/pagine/pulsante (5), manifest/permesso/opzione/testi/anteprima (6), tile con le due modalità, pagine, "Aggiorna" e stato "guida di ieri" (7), documentazione (8), prove sul 7B (9), rilascio (10).
- Nomi coerenti tra i task: `PROG_KEYS`, `build_programmes`, `cache_is_fresh`, `programmes_lines`, `resolve_view`, `button_state`, `page_for`.
- Nessun segnaposto: i blocchi di codice sono i file provati.
