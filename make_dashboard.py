#!/usr/bin/env python3
"""Genera dashboard.json: 20 righe button-card (orario, logo, titolo) per i film di sensor.film_stasera, ognuna con un
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


if __name__ == "__main__":
    json.dump(build_config(), sys.stdout, ensure_ascii=False, indent=1)
    print()
