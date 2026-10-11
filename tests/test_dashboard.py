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
