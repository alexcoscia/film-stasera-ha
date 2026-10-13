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


def write_guide(path, channels, programmes):
    """Una guida XMLTV minima. channels: {id: nome}; programmes: [(id, inizio, fine, titolo, categorie)] con gli orari
    come AAAAMMGGhhmm (ora di Roma, +0200: il 12 ottobre 2026 c'e' ancora l'ora legale)."""
    xml = ['<?xml version="1.0" encoding="UTF-8"?><tv>']
    for cid, name in channels.items():
        xml.append(f'<channel id="{cid}"><display-name>{escape(name)}</display-name></channel>')
    for cid, start, stop, title, cats, *extra in programmes:
        stop_attr = f' stop="{stop}00 +0200"' if stop else ""
        cat_xml = "".join(f"<category>{escape(c)}</category>" for c in cats)
        more = extra[0] if extra else {}   # facoltativo: {"desc": ..., "icon": ..., "actors": [...]}
        desc = f"<desc>{escape(more['desc'])}</desc>" if "desc" in more else ""
        icon = f'<icon src="{escape(more["icon"])}"/>' if "icon" in more else ""
        actors = "".join(f"<actor>{escape(a)}</actor>" for a in more.get("actors", []))
        credits = f"<credits>{actors}</credits>" if actors else ""
        xml.append(f'<programme channel="{cid}" start="{start}00 +0200"{stop_attr}>'
                   f"<title>{escape(title)}</title>{desc}{credits}{cat_xml}{icon}</programme>")
    xml.append("</tv>")
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("".join(xml))


CHANNELS = {"r1": "Rai 1", "r2": "Rai 2", "c5a": "Canale 5", "c5b": "Canale 5", "i1": "Italia 1", "n9": "NOVE"}
PROGRAMMES = [
    ("r1", "202610122000", "202610122130", "Tg1", ["Informazione"]),
    ("r1", "202610122130", "202610122235", "I casi di Teresa Battaglia - Stag. 3 - Episodio 2 - La resa dei conti",
     ["Intrattenimento"],
     {"desc": "Una  trama\n su due righe.", "icon": "https://img.example/t.png",
      "actors": ["Elena Sofia Ricci", "Maurizio Lastrico", "A", "B", "C", "D", "E"]}),
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
        self.assertEqual(self.by["Rai 1"]["prime"]["title"], "I casi di Teresa Battaglia - Stag. 3 - E")   # corto: 40 caratteri
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


class DetailsTest(unittest.TestCase):
    """Trama, immagine e cast della guida per i programmi di prima e seconda serata (secondo sensore)."""
    day = date(2026, 10, 12)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "guide.gzip")
        write_guide(self.path, CHANNELS, PROGRAMMES)
        _, self.rows, _ = fs.extract(self.path, self.day)
        self.out = fs.build(self.day, [], programmes=self.rows)

    def tearDown(self):
        self.tmp.cleanup()

    def test_extract_porta_i_dettagli(self):
        prime = self.rows[0]["prime"]
        self.assertEqual(prime["desc"], "Una trama su due righe.")        # spazi e a capo ridotti a uno
        self.assertEqual(prime["img"], "https://img.example/t.png")
        self.assertTrue(prime["full"].endswith("La resa dei conti"))       # il titolo intero, non quello corto

    def test_programma_senza_dettagli(self):
        late = self.rows[0]["late"]
        self.assertEqual((late["desc"], late["img"], late["cast"]), ("", "", ""))

    def test_liste_della_stessa_lunghezza(self):
        self.assertEqual({len(self.out[k]) for k in fs.PD_KEYS}, {len(self.rows)})

    def test_cast_limitato_ai_primi_cinque(self):
        cast = self.out["pd1_casts"][0].split(", ")
        self.assertEqual(cast, ["Elena Sofia Ricci", "Maurizio Lastrico", "A", "B", "C"])

    def test_titolo_intero_e_inizio(self):
        self.assertEqual(self.out["pd1_titles"][0], self.rows[0]["prime"]["full"])
        self.assertEqual(self.out["pd1_starts"][0], self.rows[0]["prime"]["at"])

    def test_fascia_mancante_voci_vuote(self):
        i = self.out["pd_channels"].index("Canale 5")          # solo prima serata
        self.assertEqual((self.out["pd2_titles"][i], self.out["pd2_starts"][i], self.out["pd2_descs"][i]), ("", 0, ""))

    def test_il_primo_sensore_non_cambia(self):
        self.assertEqual(self.out["prog1_titles"][0], "I casi di Teresa Battaglia - S")   # il tile: 30

    def test_nessun_programma_liste_vuote(self):
        empty = fs.build(self.day, [])
        self.assertTrue(all(empty[k] == [] for k in fs.PD_KEYS))

    def test_trame_accorciate_sotto_il_limite(self):
        pd = {k: [""] * 20 for k in fs.PD_KEYS}
        for slot in fs.PD_SLOTS:
            pd[f"{slot}_descs"] = ["x" * 400] * 20
        fitted = fs.fit_details(pd, limit=9000)
        self.assertLessEqual(len(json.dumps(fitted, ensure_ascii=False, separators=(",", ":"))), 9000)
        self.assertEqual(len(fitted["pd1_descs"]), 20)

    def test_fit_size_non_conta_gli_attributi_pd(self):
        out = dict(self.out, titles=["a"], overviews=["y" * 500], tmdb_ids=[1], posters=[""], casts=[""], years=[""])
        out["pd1_descs"] = ["z" * 20000] * len(self.rows)
        self.assertEqual(fs.fit_size(out)["overviews"], ["y" * 500])

    def test_cache_senza_dettagli_non_e_fresca(self):
        c = dict(self.out, updated=1000)
        self.assertTrue(fs.cache_is_fresh(c, self.day, 4, now=1001))
        old = {k: v for k, v in c.items() if k not in fs.PD_KEYS}
        self.assertFalse(fs.cache_is_fresh(old, self.day, 4, now=1001))

    def test_cache_con_liste_diverse_si_scarta(self):
        c = dict(self.out, updated=1000)
        c["pd2_imgs"] = c["pd2_imgs"][:1]
        path = os.path.join(self.tmp.name, "c.json")
        with open(path, "w") as f:
            json.dump(c, f)
        self.assertIsNone(fs.load_cache(path))

    def test_opzione_details_legge_la_cache_senza_rete(self):
        import subprocess
        path = os.path.join(self.tmp.name, "c.json")
        with open(path, "w") as f:
            json.dump(dict(self.out, updated=1000), f)
        r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(fs.__file__), "film_stasera.py"),
                            "--details", "--cache", path], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["count"], len(self.rows))
        self.assertEqual(got["pd1_descs"][0], "Una trama su due righe.")
        self.assertNotIn("titles", got)

    def test_opzione_details_senza_cache(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(fs.__file__), "film_stasera.py"),
                            "--details", "--cache", os.path.join(self.tmp.name, "manca.json")],
                           capture_output=True, text=True, timeout=60)
        got = json.loads(r.stdout)
        self.assertEqual((got["count"], got["pd_channels"]), (0, []))
