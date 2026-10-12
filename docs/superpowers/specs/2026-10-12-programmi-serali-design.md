# Film stasera: modalità Programmi (prima e seconda serata)

Data: 2026-10-12. Stato: approvata; aggiornata lo stesso giorno dopo le prime prove nel bench (budget dei dati, `date`).

Riguarda due repository: lo script e il package HA (`film-stasera-ha`, questa cartella) e il plugin Tessera
(`tessera-film-stasera`, `~/tessera-film-stasera`, release 0.3.0).

## Obiettivo
Il tile Tessera "Film stasera" oggi mostra solo i film. Si aggiunge una seconda modalità, **Programmi**, che mostra per
ogni canale il programma di prima serata e quello di seconda serata, in ordine di numero del telecomando. La modalità
**Film resta com'è**. Inoltre, quando mancano i dati (guida di ieri, sensore senza valore) il tile non resta con una riga
che sembra vuota: mostra un pulsante **Aggiorna** che lancia lo script.

## Decisioni già prese
- **Cambio di modalità:** un tocco sul tile alterna Film e Programmi; l'intestazione dice quale è attiva.
- **Fasce serali:** il primo programma di almeno 30 minuti che inizia tra le 21:00 e le 22:30 (prima serata) e il primo di
  almeno 30 minuti che inizia tra le 23:00 e le 02:00 (seconda serata).
- **Troppi canali:** se non entrano tutti nel tile, la modalità Programmi cambia pagina da sola ogni ~8 secondi.
- **Dove stanno i dati:** attributi nuovi sullo stesso `sensor.film_stasera`. Il tile legge un'entità sola, un solo
  download, una sola cache; stato e attributi attuali non cambiano.

## Dati (script `film_stasera.py`)
- Nello stesso passaggio sul file della guida, accanto ai film, si raccolgono per ogni canale i programmi della fascia
  19:00–03:00 con ora di inizio e di fine. Nessun secondo download.
- **Regola** (costanti in testa allo script, per ritoccarle senza toccare il resto):
  - `PRIME_FROM=21:00`, `PRIME_TO=22:30`, `LATE_FROM=23:00`, `LATE_TO=02:00` (del giorno dopo), `MIN_MINUTES=30`.
  - Prima serata = primo programma (per ora di inizio) con inizio in `[PRIME_FROM, PRIME_TO)` e durata ≥ `MIN_MINUTES`.
    Seconda serata = lo stesso in `[LATE_FROM, LATE_TO)`. Se la fine manca, la durata si considera sufficiente.
  - Le voci ripetute dal file (stesso canale e titolo a meno di `DUP_WINDOW` secondi) contano una volta, come per i film.
- **Ordine dei canali:** lista fissa `CHANNEL_ORDER` nello script, per numero di telecomando: Rai 1, Rai 2, Rai 3, Rete 4,
  Canale 5, Italia 1, La7, TV8, NOVE, 20, Rai 4, Iris, Rai Movie, Real Time, Cine34, Focus, Top Crime, DMAX, Italia 2,
  Discovery. È la numerazione più comune del digitale terrestre, non una fonte verificata: l'utente corregge l'ordine
  guardando il risultato. Un canale non in lista va in fondo.
- **Canali elencati:** solo quelli con almeno una delle due fasce. Un canale con una fascia sola mostra "—" nell'altra.
  Un canale senza nessuna fascia (oggi NOVE, Discovery, Real Time, DMAX, che la fonte non copre) non compare: chiarimento
  rispetto alla discussione, per non sprecare righe.
- **Nuovi attributi**, liste parallele della stessa lunghezza (un elemento per canale elencato):
  `prog_channels`, `prog_groups` (il gruppo 1–4 già usato per il pallino), `prog1_titles`, `prog1_starts` (secondi dal
  1970), `prog2_titles`, `prog2_starts`. Fascia mancante: titolo `""` e inizio `0`. Titoli accorciati con la `short()`
  esistente (`MAX_TITLE=40`).
- **Dimensione:** l'app manda a ogni tile al massimo **2600 byte** (`X_BUDGET`): se film e programmi non ci stanno, taglia
  tutte le liste alla stessa lunghezza (24, 16, 12, 8…). Misurato il 12/10 sulla guida vera: film 793 byte (12 film) +
  programmi 1569 byte (16 canali) = 2258. Per lasciare margine i titoli dei programmi si accorciano a 30 caratteri
  (`MAX_PROG_TITLE`). Con più di ~16 film la sera il taglio comune accorcia anche i film: limite noto, il tile mostra
  quelli che arrivano. I 16 KB di HA (`MAX_JSON`, `fit_size`) restano il limite del database, non quello del tile;
  `fit_size` taglia sempre prima le trame e i cast, mai i programmi.
- **Compatibilità:** `date`, `updated`, `stale` e la cache restano come ora; la cache vecchia, senza i campi nuovi, si
  legge come "nessun programma". Lo stato del sensore (numero di film) e gli attributi esistenti non cambiano: dashboard
  e popup attuali continuano a funzionare.
- **Package HA** (`packages/film_stasera.yaml`): i nuovi attributi si aggiungono a `json_attributes`.

## Tile (plugin 0.3.0)
- **Modalità Film:** invariata (righe con orario, titolo, canale con pallino, genere; due colonne se largo).
- **Modalità Programmi:** per ogni canale un blocco di due righe. A sinistra pallino di gruppo e nome del canale; a destra
  la prima riga `21:30 titolo` e la seconda `00:08 titolo`. Il canale occupa la colonna a sinistra come oggi l'orario nei
  film, così i titoli partono tutti dallo stesso punto. Una fascia mancante mostra "—".
- **Pagine:** i blocchi che entrano nel tile (colonne e righe calcolate come ora dalla dimensione) formano una pagina.
  Con più pagine, si passa alla successiva ogni 8 secondi, a rotazione; l'intestazione mostra `1/2`. Con una pagina sola
  niente rotazione e niente numero.
- **Data del sensore:** l'app converte un attributo il cui nome finisce per `date` in secondi dal 1970 (la mezzanotte del
  giorno, nel fuso di HA): il tile lo legge come numero e lo confronta con oggi con `tessera::days_from_today`. Per lo
  stesso motivo `updated` resta un numero e `stale` un booleano.
- **Intestazione:** in modalità Film a destra resta la data, come ora; in modalità Programmi dice "Programmi" e, con più
  pagine, il numero (`Programmi 1/3`). La nota "Guida vecchia" ha la precedenza in entrambe.
- **Tocco:** con dati validi alterna Film e Programmi. In stato senza dati (sotto) il tocco è Aggiorna. La modalità vive
  nel tile: dopo un riavvio dello schermo riparte da quella scelta nell'editor.
- **Opzione del tile** `start` (scelta Film / Programmi, default Film): la modalità iniziale. Serve anche al bench per
  disegnare la modalità Programmi.
- **Manifest:** `version: 0.3.0`; `attributes` con i sei nuovi; `has_attributes` invariato (titles, starts), così il tile
  continua a proporre solo il sensore giusto; `permissions.home_assistant_actions: [homeassistant.update_entity]`;
  `memory` rivalutata (sotto). Il testo nuovo sta in `translations/it.json` e `en.json`: Aggiorna, Aggiorno…, Film,
  Programmi, Guida di ieri, In attesa della guida, Nessun programma stasera, Azioni non consentite.
- **Memoria:** le due modalità riusano lo stesso insieme di widget di riga (nessun raddoppio). Obiettivo: restare sotto
  11.000 byte per tile; misura reale nel bench sul 7B e sugli altri schermi.

## Senza dati e pulsante Aggiorna
Stati, in ordine di precedenza (il primo che vale vince):

| Stato | Si vede | Tocco |
|---|---|---|
| Nessun sensore scelto | "Scegli il sensore" | niente |
| Sensore `unavailable`/`unknown` o senza `date` | "In attesa della guida" + pulsante **Aggiorna** | Aggiorna |
| `date` diversa da oggi (ora di Roma) | "Guida di ieri" + pulsante **Aggiorna** | Aggiorna |
| Dati di oggi ma nessun film (modalità Film) o nessun programma (modalità Programmi) | "Nessun film stasera" / "Nessun programma stasera" | cambia modalità |
| Dati validi | l'elenco | cambia modalità |

- `stale: true` (download fallito, cache servita) mantiene la nota "Guida vecchia" in intestazione, come oggi, senza
  pulsante: i dati si possono ancora usare.
- **Aggiorna:** chiama `homeassistant.update_entity` sull'entità del tile (`tessera::action`), cioè lancia lo script. Il
  pulsante diventa "Aggiorno…" e resta così finché cambia `updated` del sensore o passano 90 secondi; poi torna Aggiorna
  se i dati sono ancora mancanti. Lo script può impiegare fino a 240 s (timeout del sensore): oltre i 90 s il tile torna al
  pulsante, e i dati compariranno da soli all'arrivo.
- Se lo schermo non è autorizzato a eseguire azioni di HA, `tessera::action` restituisce falso: per 5 secondi compare
  "Azioni non consentite" al posto di "Aggiorno…".
- **Conseguenza accettata:** dopo mezzanotte e fino al primo aggiornamento il tile dice "Guida di ieri"; dopo
  l'aggiornamento mostra la serata che sta per cominciare.

## Rilascio e messa in opera
1. Script + test + package (`film-stasera-ha`): commit; copia di `film_stasera.py` e del package in HA con backup del
   package. Per rileggere `command_line` usare `command_line.reload`, non `rest.reload`, che ricarica anche i sensori
   REST del bar.
2. Plugin `tessera-film-stasera` 0.3.0: manifest, C++, traduzioni, `preview.yaml` con esempi per Programmi, per più pagine
   e per gli stati senza dati; `CHANGELOG.md`; `check.py` e bench `--strict` senza avvisi; nuovo `store.png` solo se la
   scheda cambia in modo visibile.
3. Copia della cartella del plugin in `/config/tessera-plugins/film_stasera/` (così l'editor conosce le nuove opzioni),
   compile e OTA sul 7B da `~/espscreen/checkout/waveshare7b.yaml`, Ctrl+Shift+R nell'editor; il tile già posizionato va
   eliminato e riaggiunto dopo la modifica di `attributes` e `memory`.
4. Release GitHub v0.3.0 del plugin: arriva da sola al catalogo Community. Le release e i push si fanno solo dopo il via
   dell'utente.

## Verifica
- **Script:** test con una guida di prova e `--input`, senza rete: regola delle fasce (limiti 21:00/22:30 e 23:00/02:00,
  programma da 20 minuti saltato, fine mancante), deduplica, ordine dei canali, canali senza fasce esclusi, lunghezza
  delle liste, dimensione sotto `MAX_JSON` con 20 canali e trame lunghe, lettura di una cache vecchia.
- **Prova reale** sulla guida di oggi: l'elenco per i 16 canali che hanno dati, controllato a occhio dall'utente.
- **Plugin:** `check.py`, bench `--strict` su tutti gli schermi (con avvisi a zero), esempi per modalità Film (come
  prima), Programmi a una e a più pagine, "—" per fasce mancanti, "Guida di ieri", "In attesa della guida".
- **Sul 7B:** tocco che alterna le modalità, rotazione delle pagine, pulsante Aggiorna con l'azione consentita e non.

## Fuori programma
- Canali senza dati nella fonte (NOVE, Discovery, Real Time, DMAX): restano esclusi come per i film.
- Mostrare il numero del telecomando accanto al nome (si può aggiungere dopo).
- Locandine, trame o cast per i programmi; scorrimento con il dito.
- Salvare la modalità scelta oltre il riavvio dello schermo.

## Punti da verificare durante la costruzione
- L'ordine `CHANNEL_ORDER` e le fasce, sui dati reali.
- Titoli poveri nella fonte (La7 seconda serata oggi: "Ep. 2"): limite dei dati, non dello script.
- L'orario del primo aggiornamento utile della guida (il file di oggi è del 06:01): se alle 02:00 non c'è ancora la guida
  del giorno, il pulsante Aggiorna e la regola "Guida di ieri" servono proprio a questo.
- Se la memoria del tile supera l'obiettivo sul 7B, si riducono le righe per pagina.
