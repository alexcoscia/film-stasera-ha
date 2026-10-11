# Film stasera: loghi in riga e scheda del film (TMDB)

Data: 2026-10-11. Stato: da approvare.

## Obiettivo
Nella dashboard HA `/film-stasera`:
1. Ogni riga mostra orario, logo del canale, titolo (in quest'ordine).
2. Un clic sul film apre un popup con locandina, trama e cast, in italiano.

Il tile Tessera del 7B non cambia: l'API dei plugin non mostra immagini né apre riquadri.

## Dati (script `film_stasera.py`)
- Per ogni film della sera, una ricerca su TMDB (`search/movie`, `language=it-IT`), poi `movie/{id}` con `credits` e `append_to_response`.
- Risultato salvato nella cache dello script, per titolo normalizzato + anno: ogni film si cerca una sola volta, anche tra giorni diversi. Voci senza corrispondenza si ricordano per 7 giorni, per non rifare la ricerca a ogni aggiornamento.
- Nuovi attributi del sensore, liste parallele a `titles`:
  - `tmdb_ids` (numero, 0 se non trovato)
  - `posters` (URL `https://image.tmdb.org/t/p/w342/...`, "" se manca)
  - `overviews` (trama; al massimo 600 caratteri, piu' corta quando serve per restare sotto i 15.500 byte di attributi)
  - `casts` (primi 6 nomi, separati da virgola)
  - `years` (anno di uscita, "" se ignoto)
- Chiave API: file `/config/film_stasera/tmdb.key` (una riga), escluso dal repository con `.gitignore`. Senza il file lo script funziona come oggi (nessun attributo nuovo valorizzato).
- Dimensione: con 16 film gli attributi stanno sotto i 16 KB che HA salva nel database; lo script accorcia le trame piu' lunghe finche' il JSON sta sotto 15.500 byte (e i film sono al massimo 20).
- Errori di rete o di TMDB: il film resta senza dettagli, mai un errore per tutta la guida.

## Dashboard
- Dipendenze: `button-card` (HACS, installato), `browser_mod` 3.3.0 (installato).
- 20 slot fissi in una vista a sezioni. Ogni slot è una `custom:button-card` con griglia a tre colonne: orario, logo (su riquadro bianco, come ora), titolo con canale e genere sotto.
- Uno slot è visibile solo se `sensor.film_stasera` ha almeno quel numero di film (carta `conditional`, condizione numerica sullo stato).
- Film già finiti non mostrati (come ora).
- Tap action: `browser_mod.popup` con titolo (titolo, anno), locandina a sinistra, trama e cast a destra, la dicitura TMDB in fondo.
- Senza locandina o trama il popup mostra solo quello che c'è.

## Fuori programma
- Tile Tessera, immagini nei plugin.
- Canali senza dati nella guida (NOVE, Discovery, Real Time, DMAX).
- Qualsiasi ricerca per film diversi da quelli della sera.

## Verifica
- Test dello script con `--input` su una guida di prova e una risposta TMDB simulata (nessuna chiamata di rete nei test).
- Prova reale sul Pi dopo che la chiave è nel file: tempo di aggiornamento e dimensione degli attributi.
- Dashboard: apertura nel browser e clic su una riga, con e senza locandina.

## Condizioni TMDB
Uso non commerciale. Dicitura obbligatoria: "This product uses the TMDB API but is not endorsed or certified by TMDB."
