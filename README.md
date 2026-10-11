# Film stasera (Home Assistant)

Uno script Python e un package per Home Assistant che trasformano la guida TV di EPGItalia in un sensore con i
**film in TV stasera in Italia** (prima serata, dalle 20 alle 24). Il sensore alimenta il plugin Tessera
[`tessera-film-stasera`](https://github.com/alexcoscia/tessera-film-stasera), ma si puo' usare anche da solo
(dashboard, notifiche, automazioni).

## Cosa fa
- Scarica la guida XMLTV dal link ufficiale di [EPGItalia](https://www.epgitalia.tv/scarica-epg-box-iptv/) (circa 9 MB
  compressi) e la legge in streaming.
- Tiene i programmi con categoria `Film` o `Film Animazione` (i `Telefilm` restano fuori) che **iniziano** tra le 20:00 e
  le 24:00, ora di Roma, sui canali di `CHANNELS` nello script. Scarta i duplicati (la fonte ripete i canali con id
  diversi).
- Stampa **una riga di JSON** e la ricorda in un file di cache. Se il download fallisce o il file e' anomalo, restituisce
  l'ultimo risultato buono con `"stale": true` (e la data originale), invece di perdere i dati. Se la cache di oggi ha
  meno di 4 ore, non riscarica niente (utile all'avvio di Home Assistant).
- L'ora legale e' calcolata nello script: non servono database dei fusi orari.
- Solo libreria standard.

## Il sensore
`sensor.film_stasera`: lo **stato** e' il numero di film; gli **attributi** sono liste della stessa lunghezza, una voce
per film, in ordine di orario:

| Attributo | Cosa |
|---|---|
| `titles` | Titoli (al massimo 40 caratteri) |
| `channels` | Canali |
| `starts` | Inizio, secondi dal 1970 |
| `genres` | Genere (puo' essere vuoto) |
| `groups` | Gruppo del canale: 1 Rai, 2 Mediaset, 3 Discovery, 4 altri (il tile Tessera lo trasforma in un colore) |
| `logos` | Percorso del logo (`/local/tv-logos/<canale>.png`), vuoto se non c'e' il file |
| `date` | Il giorno della guida (`AAAA-MM-GG`) |
| `updated` | Quando e' stata fatta, secondi dal 1970 |
| `stale` | `true` se e' un risultato vecchio |
| `error` | L'ultimo errore, se c'e' stato |

Al massimo 20 film.

## Installazione in Home Assistant
1. Copia `film_stasera.py` in `/config/film_stasera/` e `film_stasera.yaml` in `/config/packages/` (serve
   `packages: !include_dir_named packages` nel tuo `configuration.yaml`).
2. Controlla la configurazione (`ha core check` o Strumenti per sviluppatori).
3. Ricarica `command_line` e le automazioni (nessun riavvio necessario).

Il package aggiorna il sensore ogni giorno alle 6:15 e alle 17:00. Il primo aggiornamento scarica 9 MB: sul
Raspberry 4 e' durato circa 17 secondi.

**Per toglierlo:** cancella `packages/film_stasera.yaml` e la cartella `film_stasera`, poi ricarica.

## Loghi dei canali (facoltativi)
`download_logos.py` scarica i loghi dei tuoi canali (quelli che la guida indica) in `/config/www/tv-logos/`, da dove HA li
serve a `/local/tv-logos/<canale>.png`. Sono **15 canali su 20** e circa **300 KB** in tutto; NOVE, Rai 4, Discovery, Real
Time e DMAX non hanno un logo nella guida. Si esegue una volta (e di nuovo se aggiungi canali):

```
python3 download_logos.py --dest /config/www/tv-logos
```

Poi il sensore riempie `logos` da solo, e `dashboard_card.yaml` e' una scheda Markdown da incollare in una dashboard
(ora, logo e titolo, con i film gia' finiti nascosti). I loghi sono marchi di terzi che ospita guidatv.sky.it:
**non metterli in un repository pubblico** (la cartella e' esclusa dal repository).

## Dettagli dei film (TMDB) e dashboard con popup (facoltativi)

Con una chiave di [TMDB](https://www.themoviedb.org/) il sensore ha anche locandina, trama e cast in italiano.

1. Crea un account su themoviedb.org, poi *Impostazioni, API* e copia la chiave (v3) o il token (v4, inizia per `eyJ`).
2. Mettila, da sola su una riga, nel file `/config/film_stasera/tmdb.key` di HA. **Non** va nel repository (`.gitignore` la esclude) e non va incollata in chat.
3. Aggiorna il sensore. Attributi nuovi, una voce per film: `tmdb_ids` (0 se non trovato), `posters`, `overviews`, `casts`, `years`. Senza il file i film hanno id 0 e testi vuoti, e tutto il resto funziona come prima.

Come funziona: ogni film si cerca una volta sola e il risultato resta in `film_stasera_tmdb.json` (un film non trovato si riprova dopo 7 giorni). Un titolo si accetta solo se coincide con il titolo italiano o originale: per i titoli che non sono film (speciali, serie) non c'e' nessun dettaglio, mai quello di un altro film. Le trame piu' lunghe vengono accorciate perche' gli attributi restino sotto i 16 KB che HA salva nel database.

**Dashboard con popup.** `python3 make_dashboard.py > dashboard.json` genera 20 righe `custom:button-card` (orario, logo, titolo) e il template `film_row`. Servono da HACS **button-card** e **browser_mod**. Il template va nella radice della configurazione della dashboard (`button_card_templates`), le 20 schede in una sezione; un clic su una riga apre il popup con locandina, trama e cast. Senza button-card puoi usare la scheda Markdown di `dashboard_card.yaml`, senza popup.

*This product uses the TMDB API but is not endorsed or certified by TMDB.* Uso personale e non commerciale.

## Prova
```
python3 film_stasera.py --dry-run          # elenco leggibile, non scrive la cache
python3 film_stasera.py --date 2026-10-12  # un altro giorno
python3 film_stasera.py --input guide.gzip # un file gia' scaricato
```

## Limiti
- **La fonte** e' una raccolta di terze parti, senza una licenza chiara: le [condizioni
  d'uso](https://www.epgitalia.tv/condizioni-di-utilizzo/) consentono l'uso personale e non commerciale e vietano di
  riprodurre i contenuti senza permesso. Questo repository contiene solo il codice, non i dati: non pubblicare la guida.
- I link del sito riportano a un file su un indirizzo IP in HTTP e uno dei tre (`guide2.gzip`) risultava gia' rotto:
  puo' smettere di funzionare.
- **NOVE, Discovery, Real Time e DMAX** non hanno programmi nella fonte, quindi non compaiono mai.
- Gli orari di fine non esistono nella guida: solo l'inizio.
