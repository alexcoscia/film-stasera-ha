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

    def __init__(self, search=None, movies=None, fail=None, tv_search=None, tv=None):
        self.search, self.movies, self.fail = search or {}, movies or {}, fail
        self.tv_search, self.tv = tv_search or {}, tv or {}
        self.calls = []

    def __call__(self, path, key, params, timeout=10):
        self.calls.append((path, dict(params)))
        if self.fail:
            raise self.fail
        if path == "search/movie":
            return {"results": self.search.get(params["query"], [])}
        if path == "search/tv":
            return {"results": self.tv_search.get(params["query"], [])}
        if path.startswith("tv/"):
            return self.tv[int(path.split("/")[1])]
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


class CliTest(unittest.TestCase):
    def test_senza_chiave(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "c.json")
            with open(cache, "w", encoding="utf-8") as f:
                import time as _t
                # una cache buona e di oggi: ha anche i programmi, altrimenti lo script la ritiene da rifare
                json.dump(dict(out_of("La giuria", "Boh"), updated=int(_t.time()), **{k: [] for k in fs.PROG_KEYS + fs.PD_KEYS}), f)
            r = subprocess.run([sys.executable, "-I", os.path.join(os.path.dirname(fs.__file__), "film_stasera.py"),
                                "--date", "2026-10-11", "--cache", cache, "--logos-dir", tmp,
                                "--tmdb-key-file", os.path.join(tmp, "manca.key"),
                                "--tmdb-cache", os.path.join(tmp, "t.json")],
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tmdb_ids"], [0, 0])
        self.assertEqual(out["titles"], ["La giuria", "Boh"])


if __name__ == "__main__":
    unittest.main()


FBI = {"results": [{"id": 7, "name": "FBI: Most Wanted", "original_name": "FBI: Most Wanted"}]}
FBI_SHOW = {"id": 7, "overview": "Una squadra  speciale.", "poster_path": "/fbi.jpg", "first_air_date": "2020-01-07",
            "credits": {"cast": [{"name": f"Agente {i}"} for i in range(10)]}}


def pd_of(**kw):
    """Un'uscita con una prima e una seconda serata per due canali: Iris (un film dell'elenco) e Rai 1 (un programma)."""
    base = dict(out_of("Sette strade al tramonto"), channels=["Iris"], starts=[1791919020],
                pd_channels=["Iris", "Rai 1"], pd_groups=[2, 1], pd_logos=["", ""],
                pd1_titles=["Sette strade al tramonto", "FBI: Most Wanted - Stag. 6 Ep. 3 - Titolo"],
                pd1_starts=[1791919020, 1791918960], pd1_descs=["", "Trama guida"], pd1_casts=["", ""],
                pd1_imgs=["http://sky/a.png", "http://sky/b.png"],
                pd2_titles=["", ""], pd2_starts=[0, 0], pd2_descs=["", ""], pd2_casts=["", ""], pd2_imgs=["", ""])
    base.update(kw)
    return base


class TvLookupTest(unittest.TestCase):
    def test_pulisce_il_titolo(self):
        for raw, want in (("Tutto l'amore che resta - Stag. 1 - Episodio 5", "Tutto l'amore che resta"),
                          ("Filorosso - Stag. 2026 - Puntata del 13/10/2026", "Filorosso"),
                          ("One Piece - Stag. 1 Ep. 50 - Ep. 50 - Zoro", "One Piece"),
                          ("Boss in incognito 2026", "Boss in incognito"), ("X Factor 1^TV", "X Factor"), ("C.S.I. Miami", "C.S.I. Miami"),
                          ("FBI: Most Wanted", "FBI: Most Wanted"), ("", "")):
            self.assertEqual(fs.clean_prog_title(raw), want, raw)

    def test_trova_la_serie(self):
        d = fs.lookup_tv("FBI: Most Wanted", "k", FakeTmdb(tv_search={"FBI: Most Wanted": FBI["results"]}, tv={7: FBI_SHOW}))
        self.assertEqual((d["id"], d["poster"], d["year"]), (7, "https://image.tmdb.org/t/p/w342/fbi.jpg", "2020"))
        self.assertEqual(d["overview"], "Una squadra speciale.")
        self.assertEqual(len(d["cast"].split(", ")), fs.MAX_CAST)

    def test_puntini_e_spazi_non_contano(self):
        r = [{"id": 7, "name": "CSI: Miami", "original_name": "CSI: Miami"}]
        self.assertEqual(fs.lookup_tv("C.S.I. Miami", "k", FakeTmdb(tv_search={"C.S.I. Miami": r}, tv={7: FBI_SHOW}))["id"], 7)

    def test_nessuna_corrispondenza_sicura(self):
        wrong = [{"id": 9, "name": "Porta a Porta Kids", "original_name": "x"}]
        fake = FakeTmdb(tv_search={"Porta a porta": wrong})
        self.assertEqual(fs.lookup_tv("Porta a porta", "k", fake), {"id": 0})
        self.assertEqual(len(fake.calls), 1)


class ProgTargetsTest(unittest.TestCase):
    def test_film_dell_elenco_e_serie(self):
        t = fs.prog_targets(pd_of())
        self.assertEqual(t[("pd1", 0)], (fs.key_of("Sette strade al tramonto"), "film", "Sette strade al tramonto"))
        self.assertEqual(t[("pd1", 1)], ("tv:fbimostwanted", "tv", "FBI: Most Wanted"))

    def test_fascia_vuota(self):
        self.assertIsNone(fs.prog_targets(pd_of())[("pd2", 0)])


class ProgEnrichTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = os.path.join(self.tmp.name, "t.json")
        self.fake = FakeTmdb({"Sette strade al tramonto": [{"id": 1, "title": "Sette strade al tramonto",
                                                              "original_title": "x"}]}, {1: dict(JOB_MOVIE, poster_path="/film.jpg")},
                             tv_search={"FBI: Most Wanted": FBI["results"]}, tv={7: FBI_SHOW})
        self.ticks = iter(range(1000, 2000))

    def tearDown(self):
        self.tmp.cleanup()

    def test_cerca_le_serie_e_riempie_la_cache(self):
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        with open(self.cache, encoding="utf-8") as f:
            cache = json.load(f)
        self.assertEqual(cache["tv:fbimostwanted"]["poster"], "https://image.tmdb.org/t/p/w342/fbi.jpg")
        self.assertIn("search/tv", [c[0] for c in self.fake.calls])

    def test_non_cerca_due_volte(self):
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        n = len(self.fake.calls)
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        self.assertEqual(len(self.fake.calls), n)

    def test_il_film_dell_elenco_non_si_cerca_come_serie(self):
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        self.assertEqual([c[1]["query"] for c in self.fake.calls if c[0] == "search/tv"], ["FBI: Most Wanted"])

    def test_locandine_al_posto_delle_copertine(self):
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        pd = fs.with_tmdb_details(pd_of(), fs.load_dict(self.cache))
        self.assertEqual(pd["pd1_imgs"], ["https://image.tmdb.org/t/p/w342/film.jpg", "https://image.tmdb.org/t/p/w342/fbi.jpg"])

    def test_trama_della_guida_resta_e_cast_manca_si_riempie(self):
        fs.enrich(pd_of(), "k", self.cache, self.fake, lambda: next(self.ticks))
        pd = fs.with_tmdb_details(pd_of(), fs.load_dict(self.cache))
        self.assertEqual(pd["pd1_descs"][1], "Trama guida")              # la guida c'e': resta
        self.assertEqual(pd["pd1_descs"][0], "Una rapina a Venezia.")    # la guida non aveva nulla: TMDB
        self.assertTrue(pd["pd1_casts"][1].startswith("Agente 0"))
        self.assertEqual(len(pd["pd1_casts"][1].split(", ")), fs.MAX_PROG_CAST)

    def test_senza_cache_restano_le_copertine_della_guida(self):
        pd = fs.with_tmdb_details(pd_of(), {})
        self.assertEqual(pd["pd1_imgs"], ["http://sky/a.png", "http://sky/b.png"])

    def test_serie_non_trovata_non_cambia_nulla(self):
        pd = fs.with_tmdb_details(pd_of(), {"tv:fbimostwanted": {"id": 0, "checked": 5}})
        self.assertEqual(pd["pd1_imgs"][1], "http://sky/b.png")

    def test_senza_chiave_nessuna_richiesta(self):
        fs.enrich(pd_of(), "", self.cache, self.fake, lambda: next(self.ticks))
        self.assertEqual(self.fake.calls, [])
