#!/usr/bin/env python3
"""Genera dashboard.json, la dashboard intera (vista Film e vista Programmi, ognuna con in alto il testo che porta
all'altra): 20 righe button-card (orario, logo, titolo) per i film di sensor.film_stasera, ognuna con un
popup browser_mod (locandina, trama, cast). Uso: make_dashboard.py > dashboard.json"""
import json
import sys

SENSOR = "sensor.film_stasera"
ONAIR_SECONDS = 9000   # un film iniziato da piu' di due ore e mezza sparisce (come nel tile)

# JS comune ai tre campi: k = indice del film mostrato da questa riga (l'i-esimo non ancora finito), '' se non c'e'.
JS_HEAD = (
    "const a = entity.attributes; const now = Date.now() / 1000; "
    "const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g, (c) => "
    "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'}[c])); "
    f"const ks = (a.titles || []).map((_, j) => j).filter((j) => a.starts[j] + {ONAIR_SECONDS} >= now); "
    "const k = ks[variables.i]; if (k === undefined) return ''; "
)

TMDB_CREDIT = "This product uses the TMDB API but is not endorsed or certified by TMDB."


def popup_template(i):
    """Modello Jinja del markdown nel popup: l'i-esimo film non ancora finito, con i dettagli che ci sono."""
    return (
        "{%- set a = states.sensor.film_stasera.attributes -%}\n"
        "{%- set ora = now().timestamp() -%}\n"
        "{%- set ns = namespace(k=-1, n=0) -%}\n"
        f"{{%- for j in range(a.titles | length) if a.starts[j] + {ONAIR_SECONDS} >= ora -%}}\n"
        f"{{%- if ns.n == {i} %}}{{% set ns.k = j %}}{{% endif -%}}\n"
        "{%- set ns.n = ns.n + 1 -%}\n"
        "{%- endfor -%}\n"
        "{%- set k = ns.k -%}\n"
        "{%- set P = a.posters | default([]) -%}{%- set O = a.overviews | default([]) -%}\n"
        "{%- set C = a.casts | default([]) -%}{%- set Y = a.years | default([]) -%}\n"
        "{%- if k >= 0 -%}\n"
        "{% if P | length > k and P[k] %}<img src=\"{{ P[k] }}\" width=\"150\" "
        "style=\"float:left;margin:0 16px 8px 0;border-radius:8px\">{% endif %}\n"
        "**{{ a.titles[k] }}**{% if Y | length > k and Y[k] %} ({{ Y[k] }}){% endif %}\n\n"
        "{{ a.channels[k] }} · {{ a.starts[k] | timestamp_custom('%H:%M') }}"
        "{% if a.genres[k] %} · {{ a.genres[k] }}{% endif %}\n\n"
        "{% if O | length > k and O[k] %}{{ O[k] }}{% else %}Nessuna trama disponibile.{% endif %}\n\n"
        "{% if C | length > k and C[k] %}**Cast:** {{ C[k] }}{% endif %}\n\n"
        f"<br style=\"clear:both\"><small>{TMDB_CREDIT}</small>\n"
        "{%- else -%}\nFilm non piu' in programma.\n{%- endif -%}"
    )


def film_row_template():
    return {
        "show_icon": False, "show_name": False, "show_state": False,
        "styles": {
            "card": [{"padding": "6px 12px"},
                     {"display": "[[[ " + JS_HEAD.replace("return ''", "return 'none'") + "return 'block'; ]]]"}],
            "grid": [{"grid-template-areas": '"t l n"'}, {"grid-template-columns": "52px 96px 1fr"},
                     {"align-items": "center"}, {"column-gap": "12px"}],
            "custom_fields": {
                "t": [{"font-weight": "bold"}],
                "l": [{"justify-self": "start"}],
                "n": [{"text-align": "left"}, {"overflow": "hidden"}],
            },
        },
        "custom_fields": {
            "t": "[[[ " + JS_HEAD + "return new Date(a.starts[k] * 1000).toLocaleTimeString('it-IT', "
                 "{hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome'}); ]]]",
            "l": "[[[ " + JS_HEAD + "const logo = (a.logos || [])[k]; "
                 "if (logo) return '<img src=\"' + esc(logo) + '\" height=\"30\" "
                 "style=\"background:#fff;border-radius:6px;padding:2px 8px\">'; "
                 "return '<span>' + esc(a.channels[k]) + '</span>'; ]]]",
            "n": "[[[ " + JS_HEAD + "const sub = [a.channels[k], a.genres[k]].filter(Boolean).map(esc).join(' · '); "
                 "return '<b>' + esc(a.titles[k]) + '</b><br><small>' + sub + '</small>'; ]]]",
        },
    }


def build_config(slots=20):
    cards = []
    for i in range(slots):
        cards.append({
            "type": "custom:button-card",
            "template": "film_row",
            "entity": SENSOR,
            "variables": {"i": i},
            "grid_options": {"columns": "full"},
            "tap_action": {
                "action": "fire-dom-event",
                "browser_mod": {
                    "service": "browser_mod.popup",
                    "data": {"dismissable": True, "content": {"type": "markdown", "content": popup_template(i)}},
                },
            },
        })
    return {"button_card_templates": {"film_row": film_row_template()}, "cards": cards}


# --- Vista Programmi: prima e seconda serata, un programma per riga, dal secondo sensore (attributi pd* di
# film_stasera.py --details). Come per i film: ora, logo del canale, titolo; un clic apre il popup con immagine, trama e cast.
PROG_SENSOR = "sensor.film_stasera_programmi"
PROG_PATH = "programmi"
FILM_PATH = "stasera"
DASH_URL = "/film-stasera"
SLOTS = ((1, "Prima serata", "dalle 21:00"), (2, "Seconda serata", "dopo le 23:00"))

# JS comune ai tre campi: s = fascia (1 o 2), k = canale; '' se quel canale non ha programmi in quella fascia.
PROG_HEAD = (
    "const a = entity.attributes; const s = variables.s; const k = variables.i; "
    "const esc = (v) => String(v == null ? '' : v).replace(/[&<>\"']/g, (c) => "
    "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'}[c])); "
    "const start = (a['pd' + s + '_starts'] || [])[k]; if (!start) return ''; "
)


def prog_popup_template(slot, i):
    """Modello Jinja del popup: il programma `slot` (1 o 2) del canale i, con immagine, trama e cast della guida."""
    p = f"pd{slot}"
    return (
        f"{{%- set a = states.sensor.film_stasera_programmi.attributes -%}}\n"
        f"{{%- set k = {i} -%}}\n"
        f"{{%- set S = a.{p}_starts | default([]) -%}}{{%- set T = a.{p}_titles | default([]) -%}}\n"
        f"{{%- set D = a.{p}_descs | default([]) -%}}{{%- set C = a.{p}_casts | default([]) -%}}"
        f"{{%- set I = a.{p}_imgs | default([]) -%}}\n"
        "{%- if S | length > k and S[k] -%}\n"
        "{% if I[k] %}<img src=\"{{ I[k] }}\" width=\"200\" "
        "style=\"float:left;margin:0 16px 8px 0;border-radius:8px\">{% endif %}\n"
        "**{{ T[k] }}**\n\n"
        "{{ a.pd_channels[k] }} · {{ S[k] | timestamp_custom('%H:%M') }}\n\n"
        "{% if D[k] %}{{ D[k] }}{% else %}Nessuna trama disponibile.{% endif %}\n\n"
        "{% if C[k] %}**Cast:** {{ C[k] }}{% endif %}\n\n"
        "<br style=\"clear:both\">\n"
        "{%- else -%}\nProgramma non piu' in elenco.\n{%- endif -%}"
    )


def prog_row_template():
    return {
        "show_icon": False, "show_name": False, "show_state": False,
        "styles": {
            "card": [{"padding": "6px 12px"},
                     {"display": "[[[ " + PROG_HEAD.replace("return ''", "return 'none'") + "return 'block'; ]]]"}],
            "grid": [{"grid-template-areas": '"t l n"'}, {"grid-template-columns": "52px 96px 1fr"},
                     {"align-items": "center"}, {"column-gap": "12px"}],
            "custom_fields": {
                "t": [{"font-weight": "bold"}],
                "l": [{"justify-self": "start"}],
                "n": [{"text-align": "left"}, {"overflow": "hidden"}],
            },
        },
        "custom_fields": {
            "t": "[[[ " + PROG_HEAD + "return new Date(start * 1000).toLocaleTimeString('it-IT', "
                 "{hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome'}); ]]]",
            "l": "[[[ " + PROG_HEAD + "const logo = (a.pd_logos || [])[k]; "
                 "if (logo) return '<img src=\"' + esc(logo) + '\" height=\"30\" "
                 "style=\"background:#fff;border-radius:6px;padding:2px 8px\">'; "
                 "return '<span>' + esc(a.pd_channels[k]) + '</span>'; ]]]",
            "n": "[[[ " + PROG_HEAD + "return '<b>' + esc(a['pd' + s + '_titles'][k]) + '</b><br><small>' "
                 "+ esc(a.pd_channels[k]) + '</small>'; ]]]",
        },
    }


def nav_card(text, path):
    """Testo cliccabile in cima a una vista: porta all'altra vista della stessa dashboard."""
    return {
        "type": "custom:button-card",
        "name": text,
        "show_icon": False,
        "grid_options": {"columns": "full"},
        "styles": {
            "card": [{"background": "none"}, {"box-shadow": "none"}, {"padding": "0 12px"}],
            "name": [{"color": "var(--primary-color)"}, {"font-weight": "500"}, {"font-size": "16px"},
                     {"justify-self": "start"}],
        },
        "tap_action": {"action": "navigate", "navigation_path": f"{DASH_URL}/{path}"},
    }


def build_programmes_cards(slots=20):
    """Per ogni fascia un titoletto e `slots` righe; la riga di un canale senza programmi in quella fascia si nasconde."""
    cards = []
    for slot, title, hint in SLOTS:
        cards.append({"type": "heading", "heading": f"{title} ({hint})", "heading_style": "subtitle"})
        for i in range(slots):
            cards.append({
                "type": "custom:button-card", "template": "prog_row", "entity": PROG_SENSOR,
                "variables": {"s": slot, "i": i}, "grid_options": {"columns": "full"},
                "tap_action": {
                    "action": "fire-dom-event",
                    "browser_mod": {
                        "service": "browser_mod.popup",
                        "data": {"dismissable": True,
                                 "content": {"type": "markdown", "content": prog_popup_template(slot, i)}},
                    },
                },
            })
    return cards


def build_dashboard(slots=20):
    """La dashboard intera: vista Film (stasera) e vista Programmi, ognuna con in alto il testo che porta all'altra."""
    films = build_config(slots)
    def view(title, path, icon, cards):
        return {"title": title, "path": path, "type": "sections", "icon": icon, "max_columns": 2,
                "sections": [{"type": "grid", "cards": cards}]}
    return {
        "views": [
            view("Stasera", FILM_PATH, "mdi:movie-open",
                 [{"type": "heading", "heading": "Film in TV stasera", "heading_style": "title",
                   "icon": "mdi:movie-open"},
                  nav_card("Programmi stasera →", PROG_PATH)] + films["cards"]),
            view("Programmi", PROG_PATH, "mdi:television-classic",
                 [{"type": "heading", "heading": "Programmi in TV stasera", "heading_style": "title",
                   "icon": "mdi:television-classic"},
                  nav_card("← Film stasera", FILM_PATH)] + build_programmes_cards(slots)),
        ],
        "button_card_templates": {**films["button_card_templates"], "prog_row": prog_row_template()},
    }


if __name__ == "__main__":
    json.dump(build_dashboard(), sys.stdout, ensure_ascii=False, indent=1)
    print()
