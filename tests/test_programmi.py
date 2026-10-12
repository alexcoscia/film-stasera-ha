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
