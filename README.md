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
