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


class ProgrammesViewTest(unittest.TestCase):
    def setUp(self):
        self.dash = md.build_dashboard(20)
        self.view = self.dash["views"][1]
        self.cards = self.view["sections"][0]["cards"]
        self.rows = [c for c in self.cards if c.get("template") == "prog_row"]

    def test_due_viste_con_il_testo_che_rimanda_all_altra(self):
        self.assertEqual([v["path"] for v in self.dash["views"]], ["stasera", "programmi"])
        navs = [[c for c in v["sections"][0]["cards"] if c.get("tap_action", {}).get("action") == "navigate"]
                for v in self.dash["views"]]
        self.assertEqual(navs[0][0]["tap_action"]["navigation_path"], "/film-stasera/programmi")
        self.assertEqual(navs[1][0]["tap_action"]["navigation_path"], "/film-stasera/stasera")
        self.assertIn("Programmi", navs[0][0]["name"])
        self.assertIn("Film", navs[1][0]["name"])

    def test_il_testo_e_il_primo_dopo_il_titolo(self):
        for v in self.dash["views"]:
            cards = v["sections"][0]["cards"]
            self.assertEqual(cards[0]["type"], "heading")
            self.assertEqual(cards[1]["tap_action"]["action"], "navigate")

    def test_due_fasce_di_venti_righe(self):
        self.assertEqual(len(self.rows), 40)
        self.assertEqual([(r["variables"]["s"], r["variables"]["i"]) for r in self.rows],
                         [(s, i) for s in (1, 2) for i in range(20)])
        self.assertTrue(all(r["entity"] == "sensor.film_stasera_programmi" for r in self.rows))

    def test_ogni_riga_apre_il_popup_del_suo_programma(self):
        for r in self.rows:
            tap = r["tap_action"]
            self.assertEqual(tap["browser_mod"]["service"], "browser_mod.popup")
            text = tap["browser_mod"]["data"]["content"]["content"]
            self.assertIn(f"a.pd{r['variables']['s']}_descs", text)
            self.assertIn("set k = %d " % r["variables"]["i"], text)

    def test_popup_con_immagine_trama_e_cast(self):
        text = self.rows[0]["tap_action"]["browser_mod"]["data"]["content"]["content"]
        for part in ("<img", "Nessuna trama disponibile", "**Cast:**", "pd_channels"):
            self.assertIn(part, text)

    def test_riga_con_logo_e_testi_protetti(self):
        t = self.dash["button_card_templates"]["prog_row"]
        self.assertEqual(set(t["custom_fields"]), {"t", "l", "n"})
        self.assertIn("pd_logos", t["custom_fields"]["l"])
        for f in ("l", "n"):
            self.assertIn("esc(", t["custom_fields"][f])

    def test_riga_vuota_si_nasconde(self):
        t = self.dash["button_card_templates"]["prog_row"]
        self.assertIn("return 'none'", t["styles"]["card"][1]["display"])
