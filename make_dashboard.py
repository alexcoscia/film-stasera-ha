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


# --- Vista Programmi: un canale per riga, con prima e seconda serata (attributi prog_* del sensore) ---
PROG_PATH = "programmi"
FILM_PATH = "stasera"
DASH_URL = "/film-stasera"
GROUP_COLORS = "{1: '#3B82F6', 2: '#F59E0B', 3: '#10B981'}"   # Rai, Mediaset, Discovery; gli altri viola come nel tile

PROG_HEAD = (
    "const a = entity.attributes; const k = variables.i; "
    "const esc = (s) => String(s == null ? '' : s).replace(/[&<>\"']/g, (c) => "
    "({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', \"'\": '&#39;'}[c])); "
    "if (k >= (a.prog_channels || []).length) return ''; "
    "const hm = (t) => new Date(t * 1000).toLocaleTimeString('it-IT', "
    "{hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Rome'}); "
)


def prog_row_template():
    return {
        "show_icon": False, "show_name": False, "show_state": False,
        "styles": {
            "card": [{"padding": "6px 12px"},
                     {"display": "[[[ " + PROG_HEAD.replace("return ''", "return 'none'") + "return 'block'; ]]]"}],
            "grid": [{"grid-template-areas": '"c p" "c l"'}, {"grid-template-columns": "150px 1fr"},
                     {"align-items": "center"}, {"column-gap": "12px"}, {"row-gap": "2px"}],
            "custom_fields": {
                "c": [{"justify-self": "start"}, {"font-weight": "bold"}],
                "p": [{"text-align": "left"}, {"overflow": "hidden"}],
                "l": [{"text-align": "left"}, {"overflow": "hidden"}, {"opacity": "0.7"}, {"font-size": "0.9em"}],
            },
        },
        "custom_fields": {
            "c": "[[[ " + PROG_HEAD + f"const col = ({GROUP_COLORS})[(a.prog_groups || [])[k]] || '#A855F7'; "
                 "return '<span style=\"display:inline-block;width:10px;height:10px;border-radius:50%;"
                 "margin-right:8px;background:' + col + '\"></span>' + esc(a.prog_channels[k]); ]]]",
            "p": "[[[ " + PROG_HEAD + "const t = a.prog1_starts[k]; if (!t) return '&ndash;'; "
                 "return '<b>' + hm(t) + '</b> ' + esc(a.prog1_titles[k]); ]]]",
            "l": "[[[ " + PROG_HEAD + "const t = a.prog2_starts[k]; if (!t) return '&ndash;'; "
                 "return hm(t) + ' ' + esc(a.prog2_titles[k]); ]]]",
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
    return [{"type": "custom:button-card", "template": "prog_row", "entity": SENSOR,
             "variables": {"i": i}, "grid_options": {"columns": "full"}} for i in range(slots)]


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
                  nav_card("Programmi stasera \u2192", PROG_PATH)] + films["cards"]),
            view("Programmi", PROG_PATH, "mdi:television-classic",
                 [{"type": "heading", "heading": "Programmi in TV stasera", "heading_style": "title",
                   "icon": "mdi:television-classic"},
                  nav_card("\u2190 Film stasera", FILM_PATH)] + build_programmes_cards(slots)),
        ],
        "button_card_templates": {**films["button_card_templates"], "prog_row": prog_row_template()},
    }


if __name__ == "__main__":
    json.dump(build_dashboard(), sys.stdout, ensure_ascii=False, indent=1)
    print()
