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
