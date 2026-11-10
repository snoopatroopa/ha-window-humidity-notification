# Raumfeuchte & Lüftungswächter (Home-Assistant-Blueprint)

Ein Automations-Blueprint, den du **pro Raum** einmal anlegst. Er überwacht die relative
Luftfeuchte und den Fensterzustand (offen / gekippt / zu) und meldet:

1. **„Bitte lüften“**, wenn die Feuchte über dem kritischen Wert liegt und das Fenster zu ist.
   Bei aktiver Taupunktprüfung heißt die Meldung **„Lüften bringt aktuell nichts – Lüfter/Entfeuchter
   nutzen“**, wenn die Außenluft nicht deutlich trockener ist.
2. **„Fenster kann geschlossen werden“**, wenn die Feuchte bei offenem oder gekipptem Fenster wieder
   unter den OK-Wert fällt.
3. **„Fenster zu lange offen“**, wenn das Fenster zu lange ganz offen oder insgesamt zu lange nicht
   zu ist (gekippt + offen zusammengerechnet). Danach folgen Erinnerungen.

Optional senkt der Blueprint das Thermostat bei offenem Fenster ab und stellt es beim Schließen
wieder her. Außerdem kann er einen Lüfter oder Entfeuchter schalten.

Datei: [`blueprints/automation/raumfeuchte_lueftung.yaml`](blueprints/automation/raumfeuchte_lueftung.yaml)
Mindestversion: **Home Assistant 2026.7.0**

---

## Installation

1. Trage in `source_url` im Blueprint deinen GitHub-Pfad ein (Platzhalter `<user>/<repo>`).
2. In Home Assistant: **Einstellungen → Automationen & Szenen → Blueprints → Blueprint importieren**
   und die GitHub-URL der Datei einfügen.
   Alternativ kopierst du die Datei mit der **File editor App** nach
   `config/blueprints/automation/<dein-name>/raumfeuchte_lueftung.yaml`.
3. Empfohlen: pro Raum zwei Helfer anlegen (siehe [Helfer](#helfer-empfohlen)).
4. **Automation aus Blueprint erstellen**, den Raum benennen und die Sensoren wählen.

---

## Funktionsweise

| Trigger-ID | Auslöser | Was passiert |
|---|---|---|
| `feuchte_hoch` | `humidity.crossed_threshold` über *kritisch*, für *Mindestdauer* | Fenster **zu**: Push „bitte lüften“ bzw. „Lüften bringt nichts“. Fenster **unbekannt**: gleiche Meldung mit Zusatz „Fensterstatus unbekannt“. Fenster **offen/gekippt**: kein Push, außer Lüften bringt laut Taupunkt nichts. Dann kommt „Lüften bringt aktuell nichts: bitte Fenster schließen und Lüfter/Entfeuchter nutzen“. Lüfter an, wenn Fenster zu oder Lüften nichts bringt. Cooldown setzen. |
| `feuchte_ok` | `humidity.crossed_threshold` unter *OK-Wert*, für 2 min | Fenster offen/gekippt: Push „Fenster kann geschlossen werden“. Sonst wird die alte Feuchte-Meldung gelöscht. Lüfter aus. „Ignorieren bis Feuchte ok“ endet. |
| `fenster_auf` | Fensterzustand wechselt auf offen/gekippt (von etwas anderem) | Feuchte über *kritisch* und Lüften nutzlos: Push „bitte Fenster schließen“ (der Cooldown greift hier nicht, „Ignorieren bis Feuchte ok“ schon). Sonst wird die Feuchte-Meldung gelöscht, weil gelüftet wird. Optional nach *Verzögerung* Thermostat-Snapshot (`scene.create`) und Absenkung. |
| `fenster_zu` | Fensterzustand wechselt auf *zu* | Fenster- und Feuchte-Meldungen löschen (`clear_notification` mit gleichem `tag`), Fenster-Pause zurücksetzen, Thermostat wiederherstellen (`scene.turn_on`, danach `scene.delete`). Feuchte noch hoch: Lüfter an. Laufende Erinnerungen enden von selbst. |
| `fenster_zu_lange_nicht_zu` | Template-Trigger „offen ODER gekippt“ mit `for:` | Meldung mit Dauer, Zustand und Außentemperatur, danach Erinnerungen |
| `fenster_zu_lange_ganz_offen` | State-Trigger *offen* mit `for:` | wie oben, für den Zustand ganz offen |
| `aktion_*` | `mobile_app_notification_action` mit den Aktions-IDs dieser Instanz | „Später erinnern (30 min)“ bzw. „Ignorieren“ |

### Fensterzustände

Jeder Zustand wird **explizit** geprüft:

| Sensorwert | gilt als |
|---|---|
| = *Zustandswert offen* (`open`) | offen |
| = *Zustandswert gekippt* (`tilted`) | gekippt |
| = *Zustandswert zu* (`closed`) | zu |
| alles andere (`unavailable`, `unknown`, Tippfehler …) | **unbekannt**: keine Fenster-Meldungen, nur Feuchte-Meldungen |

„Zu“ wird nie als „alles außer offen“ ausgewertet.

### Erinnerungen

Nach der ersten Fenster-Meldung kommen bis zu *Max. Anzahl Erinnerungen* weitere Meldungen im
*Erinnerungsintervall*. Die Schleife nutzt `repeat` und wartet per `wait_template` mit `timeout` auf
„Fenster nicht mehr offen/gekippt“ oder „Fenster-Pause aktiv“. Sie endet also sofort beim Schließen,
auch wenn das Fenster schon zu ist, wenn die Wartezeit beginnt. Alle Meldungen eines Raums nutzen
dieselben Tags `feuchte_<raum>` und `fenster_<raum>`, eine neue Meldung ersetzt also die alte.

### Taupunkt / absolute Feuchte

Mit aktivierter Taupunktprüfung berechnet der Blueprint die absolute Feuchte (g/m³) innen und außen
nach der Magnus-Formel (Koeffizienten nach DIN 4108-3: über Wasser 7,5/237,3, über Eis 7,6/240,7):

```
SDD = 6,1078 · 10^(a·T / (b + T))        Sättigungsdampfdruck [hPa]
DD  = rF/100 · SDD                        Dampfdruck [hPa]
AF  = 216,7 · DD / (T + 273,15)           absolute Feuchte [g/m³]
TD  = b·v / (a − v), v = log10(DD/6,1078) Taupunkt [°C]
```

Ist `AF_innen − AF_außen < Mindestdifferenz` (Standard 1 g/m³), heißt die Meldung
„Lüften bringt aktuell nichts – Lüfter/Entfeuchter nutzen“. Fehlt ein Messwert, gilt Lüften als
sinnvoll (Standardmeldung). Die Formel steht als Jinja-Macro einmal in `variables:` und wird dort für
innen und außen aufgerufen. Externe `custom_templates` braucht es nicht.

### Kältefaktor

Mit *Maximaldauern bei Kälte verkürzen* und einer Außentemperatur unter der Kälteschwelle werden
beide Maximaldauern mit dem Kältefaktor multipliziert (Standard 0,5). Technisch feuern die Trigger
immer bei der **verkürzten** Dauer. Ist es zu diesem Zeitpunkt nicht kalt, wartet die Automation die
restliche Zeit ab (`wait_template` mit `timeout`). So kommt der Trigger ohne `states()` aus, und die
Temperatur wird erst beim Ablauf geprüft.

---

## Inputs

### Raum & Sensoren

| Input | Typ | Standard | Bedeutung |
|---|---|---|---|
| `raum_name` | Text | – | Name in den Meldungen. Daraus entstehen Tags und Aktions-IDs (`Bad OG` → `feuchte_bad_og`, `RFL_BAD_OG_…`). **Pro Raum eindeutig.** |
| `feuchte_sensor` | Entität (sensor, humidity) | – | rel. Feuchte in % |
| `temperatur_sensor_innen` | Entität (sensor, temperature) | leer | nur für die Taupunktprüfung |
| `fenster_sensor` | Entität (sensor) | – | z. B. `sensor.bad_og_fenster` |
| `fenster_offen_wert` | Text | `open` | Zustandswert für offen |
| `fenster_gekippt_wert` | Text | `tilted` | Zustandswert für gekippt |
| `fenster_zu_wert` | Text | `closed` | Zustandswert für zu |

### Schwellwerte

| Input | Typ | Standard | Bedeutung |
|---|---|---|---|
| `feuchte_kritisch` | Zahl % | 65 | Schwelle für „bitte lüften“ |
| `feuchte_ok` | Zahl % | 55 | Schwelle für „wieder OK“, **muss < kritisch sein**. Sonst gibt es eine dauerhafte Benachrichtigung in HA und die Automation bricht ab. |
| `mindestdauer_ueberschreitung` | Dauer | 3 min | so lange muss die Feuchte über *kritisch* liegen |
| `max_dauer_nicht_zu` | Dauer | 45 min | Gesamtzeit gekippt ODER offen. Ein Wechsel gekippt ↔ offen setzt **nicht** zurück. |
| `max_dauer_ganz_offen` | Dauer | 15 min | Zeit im Zustand offen |
| `cooldown` | Dauer | 30 min | keine erneute „Feuchte hoch“-Meldung in dieser Zeit (braucht den Helfer *Feuchte-Pause*) |

### Außenklima & Taupunkt (eingeklappt)

| Input | Typ | Standard | Bedeutung |
|---|---|---|---|
| `taupunkt_pruefung_aktiv` | Schalter | aus | Vergleich der absoluten Feuchte innen/außen |
| `aussen_temperatur` | Entität (sensor, temperature) | leer | hat Vorrang vor der Wetter-Entität |
| `aussen_feuchte` | Entität (sensor, humidity) | leer | hat Vorrang vor der Wetter-Entität |
| `wetter_entitaet` | Entität (weather) | leer | Ersatzquelle (Attribute `temperature`, `humidity`) |
| `min_differenz_abs_feuchte` | Zahl g/m³ | 1 | so viel trockener muss die Außenluft sein |
| `dauer_temperaturabhaengig` | Schalter | aus | Maximaldauern bei Kälte verkürzen (geht auch ohne Taupunktprüfung) |
| `kalt_schwelle` | Zahl °C | 5 | darunter gilt es als kalt |
| `kalt_faktor` | Zahl | 0,5 | Faktor für beide Maximaldauern (0,1–1) |

### Benachrichtigung

| Input | Typ | Standard | Bedeutung |
|---|---|---|---|
| `notify_geraete` | Gerät (mobile_app, mehrfach) | leer | Push per `notify.mobile_app_<gerätename>` |
| `zusaetzliche_aktionen` | Aktionen | leer | laufen bei jeder Meldung zusätzlich (TTS, Telegram …). Variablen: `meldung_titel`, `meldung_text`, `meldung_tag`, `raum_name`. |
| `erinnerung_intervall` | Dauer | 10 min | Abstand der Fenster-Erinnerungen (mindestens 60 s) |
| `max_erinnerungen` | Zahl | 3 | Erinnerungen nach der ersten Fenster-Meldung |
| `ruhezeit_start` / `ruhezeit_ende` | Uhrzeit | leer | keine Meldungen dazwischen. Über Mitternacht geht es, wenn Start > Ende. |
| `anwesenheit` | Entität (person/zone/group) | leer | nur melden, wenn jemand zu Hause ist (Person `home`, Zone > 0, Gruppe `home`/`on`) |
| `helfer_feuchte_pause` | Entität (input_datetime) | leer | „Feuchte-Meldungen stumm bis …“: für Cooldown und die Buttons an Feuchte-Meldungen |
| `helfer_fenster_pause` | Entität (input_datetime) | leer | „Fenster-Meldungen stumm bis …“: für die Buttons an Fenster-Meldungen |

### Optionale Aktionen (eingeklappt)

| Input | Typ | Standard | Bedeutung |
|---|---|---|---|
| `thermostat_aktiv` | Schalter | aus | Thermostat absenken |
| `thermostat` | Entität (climate) | leer | |
| `heizung_verzoegerung` | Dauer | 2 min | erst absenken, wenn das Fenster so lange offen/gekippt ist |
| `absenk_art` | Auswahl | Temperatur | `temperatur` (→ `climate.set_temperature`) oder `aus` (→ `climate.turn_off`) |
| `absenk_temperatur` | Zahl °C | 12 | Zieltemperatur bei `temperatur` |
| `luefter_aktiv` | Schalter | aus | Lüfter/Entfeuchter schalten |
| `luefter` | Entität (fan/switch) | leer | |

---

## Helfer (empfohlen)

Cooldown und die Aktions-Buttons brauchen einen Zustand, der zwischen Automationsläufen erhalten
bleibt. Ohne Helfer geht das in einer Multi-Trigger-Automation nicht zuverlässig (Begründung unter
[Designentscheidungen](#designentscheidungen)). Lege pro Raum an:
**Einstellungen → Geräte & Dienste → Helfer → Helfer erstellen → Datum und/oder Uhrzeit →
„Datum und Uhrzeit“**

| Helfer | Zweck |
|---|---|
| `input_datetime.bad_og_feuchte_pause` | Cooldown (`jetzt + Cooldown`), „Später erinnern“ (`jetzt + 30 min`), „Ignorieren bis Feuchte ok“ (`jetzt + 1 Jahr`, wird bei `feuchte_ok` zurückgesetzt) |
| `input_datetime.bad_og_fenster_pause` | „Später erinnern“ (`jetzt + 30 min`), „Ignorieren bis Fenster zu“ (`jetzt + 1 Jahr`, wird bei `fenster_zu` zurückgesetzt) |

Ohne Helfer läuft alles andere normal. Es gibt dann nur **keinen Cooldown** und **keine
Aktions-Buttons**.

---

## Beispielkonfiguration: Bad OG

Am einfachsten über die UI. Als YAML (Automations-Editor → „In YAML bearbeiten“):

```yaml
alias: Raumfeuchte & Lüftung – Bad OG
description: Feuchte- und Fensterwächter für das Bad im OG
use_blueprint:
  path: <dein-name>/raumfeuchte_lueftung.yaml
  input:
    raum_name: Bad OG
    feuchte_sensor: sensor.bad_og_luftfeuchte          # Entity-ID anpassen
    temperatur_sensor_innen: sensor.bad_og_temperatur  # Entity-ID anpassen
    fenster_sensor: sensor.bad_og_fenster
    feuchte_kritisch: 65
    feuchte_ok: 55
    taupunkt_pruefung_aktiv: true
    wetter_entitaet: weather.forecast_home             # oder aussen_temperatur/aussen_feuchte
    dauer_temperaturabhaengig: true
    notify_geraete:
      - <device_id des Handys>                          # in der UI auswählen
    ruhezeit_start: "22:00:00"
    ruhezeit_ende: "06:30:00"
    anwesenheit: zone.home
    helfer_feuchte_pause: input_datetime.bad_og_feuchte_pause
    helfer_fenster_pause: input_datetime.bad_og_fenster_pause
    thermostat_aktiv: true
    thermostat: climate.bad_og
    luefter_aktiv: true
    luefter: fan.bad_og_luefter
```

---

## Fenster-Template-Sensor (Eltako FFG7B über KNX-ENO-Gateway)

Der FFG7B (Fenstergriff) liefert über das Gateway zwei `binary_sensor`. Die **Annahme** hier:

- **A** = `binary_sensor.bad_og_fenster_offen` (an, wenn der Griff waagerecht steht = offen)
- **B** = `binary_sensor.bad_og_fenster_gekippt` (an, wenn der Griff oben steht = gekippt)

| A (offen) | B (gekippt) | `sensor.bad_og_fenster` |
|---|---|---|
| off | off | `closed` |
| on | off | `open` |
| off | on | `tilted` |
| on | on | `fehler` (unmöglich; der Blueprint wertet das als *unbekannt*) |
| unavailable/unknown | beliebig | *unknown* |
| beliebig | unavailable/unknown | *unknown* |

> Prüfe die Zuordnung an deinem Gateway: Manche ENO-Gateways geben stattdessen
> „nicht zu“ (offen **oder** gekippt) + „gekippt“ aus. Dann gilt: A=on/B=off → `open`,
> A=on/B=on → `tilted`, A=off/B=off → `closed`, A=off/B=on → `fehler`.

Anlegen als **Template-Helfer** (Einstellungen → Geräte & Dienste → Helfer → Helfer erstellen →
Template → Template-Sensor), Feld *Zustand*:

```jinja
{% set a = states('binary_sensor.bad_og_fenster_offen') %}
{% set b = states('binary_sensor.bad_og_fenster_gekippt') %}
{% if a not in ['on', 'off'] or b not in ['on', 'off'] %}
  {{ none }}
{% elif a == 'off' and b == 'off' %}closed
{% elif a == 'on' and b == 'off' %}open
{% elif a == 'off' and b == 'on' %}tilted
{% else %}fehler
{% endif %}
```

`{{ none }}` setzt den Sensor auf `unknown`. Das ist gewollt: Der Blueprint wertet das weder als offen
noch als zu.

---

## Designentscheidungen

- **`mode: parallel` (max 20).** `fenster_zu` muss eine laufende Erinnerungsschleife zuverlässig
  beenden, und `feuchte_ok` darf nie blockiert werden. Bei `single`/`queued` würde eine wartende
  Schleife `feuchte_ok` verwerfen oder verzögern. Bei `restart` würde jeder Feuchte-Trigger eine
  laufende Fenster-Erinnerung und die Heizungs-Absenkverzögerung abbrechen. Mit `parallel` endet
  jede Schleife über ihr eigenes `wait_template` („nicht mehr offen/gekippt“ oder „Pause aktiv“).
  Das greift auch dann, wenn der Zustand schon vor der Wartezeit erfüllt ist.
- **Gesamtdauer „offen ODER gekippt“: Template-Trigger mit `for:`.** Ein State-Trigger mit
  `to: [open, tilted]` und `for:` reicht nicht. Der Core-Code
  (`homeassistant/components/homeassistant/triggers/state.py`, `_check_same_state`) vergleicht den
  aktuellen Zustand mit **genau dem Zustand, der den Timer gestartet hat**, und `open` → `tilted`
  bricht den Timer ab. Die einzige native Alternative wäre ein zusätzlicher Template-Binärsensor-Helfer
  „Fenster nicht zu“ pro Raum. Der Template-Trigger hält den Blueprint helferfrei.
- **Feuchte-Trigger: `humidity.crossed_threshold` statt `numeric_state`.** Das ist der
  purpose-specific Trigger, Standard seit 2026.7. Er verwirft Zustandswechsel, die von
  `unavailable`/`unknown` kommen, und verhindert damit genau den Fehlalarm nach einem Neustart.
  Zusätzlich prüft jede Feuchte-Verzweigung `trigger.from_state` explizit (doppelte Absicherung).
- **`fenster_auf` mit `not_from: [offen, gekippt]` statt `from: zu`.** Sonst fehlt der Wechsel
  `closed → unavailable → open` (Funk- oder Gateway-Aussetzer), und das Thermostat bliebe hoch.
- **Cooldown und Snooze über optionale `input_datetime`-Helfer.** `this.attributes.last_triggered`
  passt hier nicht: Es wird von **jedem** Lauf gesetzt, auch von Fenster-Triggern. Ein Cooldown darüber
  würde z. B. eine berechtigte Feuchte-Meldung kurz nach dem Schließen des Fensters schlucken. Eine
  laufende `wait_template`-Schleife kann außerdem nicht gleichzeitig auf ein Event (Button) warten. Sie
  sieht aber die Änderung des Helfers und endet.
- **Button an Fenster-Meldungen: „Ignorieren bis Fenster zu“** statt „bis Feuchte ok“. Eine
  Fenster-Meldung bis „Feuchte ok“ zu ignorieren, ergibt bei geschlossenem Fenster keinen Sinn.
- **Kältefaktor:** Die Trigger feuern bei der verkürzten Dauer, die Actions warten den Rest ab, wenn es
  nicht kalt ist (siehe oben).
- **Doppelte Meldungen vermeiden:** Ist das Fenster schon länger als *max. Dauer ganz offen* offen,
  sendet nur die „ganz offen“-Schleife. Die „nicht zu“-Schleife setzt dann aus.
- **Wiederkehrende Bausteine** (Senden, Löschen, Erinnerungsschleife, Feuchte-Meldung) sind per
  YAML-Anker einmal definiert. `!input` steht nie in Templates, alles läuft über
  `trigger_variables:` bzw. `variables:`.
- **Ruhezeit als Template-Bedingung** statt `condition: time`, weil beide Zeiten optional sind und
  `condition: time` keine leeren Werte annimmt.

## Annahmen

- Der Fenstersensor hat genau die drei konfigurierten Zustandswerte. Andere Werte gelten als
  unbekannt.
- Die Feuchte-Sensoren melden in `%`, das prüft `humidity.crossed_threshold`. Außentemperatur und
  Wetter-Entität melden in °C.
- Der Notify-Dienst heißt `notify.mobile_app_<slug des ursprünglichen Gerätenamens>`. Das ist das
  Standardverhalten der Companion App. Ein in HA umbenanntes Gerät behält seinen Dienstnamen, der
  Blueprint nutzt `device_attr(…, 'name')`.
- Ruhezeit und Anwesenheit gelten auch für die *zusätzlichen Aktionen*, damit TTS nachts still bleibt.
  Meldungen in der Ruhezeit werden **verworfen**, nicht nachgeholt.
- „Später erinnern“ bei Feuchte: Nach 30 min kommt die Meldung erneut, wenn die Feuchte noch über
  *kritisch* liegt und das Fenster zu oder unbekannt ist.
- „Lüfter aus“ bei `feuchte_ok` gilt auch für einen von Hand eingeschalteten Lüfter.

## Bekannte Grenzen

- **Neustart oder Automation-Reload:** Laufende Erinnerungen, Snooze-Wartezeiten und die
  Heizungsverzögerung gehen verloren. Der Thermostat-Snapshot (`scene.create`) ist flüchtig: Nach einem
  Neustart bei offenem Fenster bleibt das Thermostat abgesenkt. `for:`-Timer der Trigger beginnen nach
  einem Neustart neu. Der Template-Trigger „nicht zu“ wird nur scharf, wenn das Fenster beim Laden zu
  war (oder der Sensor noch `unknown` war). Ist es beim Neustart schon offen, kommt für diese Öffnung
  keine „nicht zu“-Meldung, die „ganz offen“-Meldung kann trotzdem kommen.
- Der Kältefaktor wird beim Ablauf der verkürzten Dauer geprüft, nicht laufend.
- Die Taupunktdaten in der „Später erinnern“-Meldung stammen vom Zeitpunkt des Buttons (Feuchte wird
  neu gelesen, Außenklima nicht).
- `max_erinnerungen` zählt Durchläufe, auch solche ohne Push (Ruhezeit, Pause, Übernahme durch die
  „ganz offen“-Schleife).
- Wird das Thermostat bei offenem Fenster von Hand verstellt, überschreibt die Wiederherstellung das.
- „Fenster schließen“ wegen nutzlosen Lüftens kommt nur bei zwei Ereignissen: wenn die Feuchte die
  kritische Schwelle überschreitet oder wenn das Fenster geöffnet wird. Kippt das Außenklima, während
  das Fenster schon offen ist und die Feuchte schon hoch, kommt keine neue Meldung.
- Den Raumnamen in eine Form bringen, die zu „im …“ passt (z. B. „Bad OG“, „Wohnzimmer“).
  Ein Umbenennen ändert Tags und Aktions-IDs, Buttons alter Meldungen tun dann nichts mehr.
- Höchstens 20 parallele Läufe pro Instanz. Das reicht im Normalbetrieb mit großem Abstand.

## Validierung

- `yamllint` (Konfiguration in `.yamllint`) läuft ohne Fehler durch.
- Der Ende-zu-Ende-Test [`tests/test_blueprint_e2e.py`](tests/test_blueprint_e2e.py) lädt den
  Blueprint in einen echten Home-Assistant-Core (getestet mit 2026.11.1, Schema-Validierung inklusive)
  und spielt 48 Szenarien mit auf Sekunden verkürzten Dauern durch: Restart-Guard, Cooldown,
  Taupunkt, Thermostat-Snapshot und -Wiederherstellung, `tilted`↔`open` ohne Reset, Erinnerungen,
  Abbruch beim Schließen, Snooze/Ignorieren für Fenster und Feuchte, unbekannter Fensterzustand,
  Hysterese-Absicherung, Kältefaktor, Instanz ohne Helfer, „Fenster schließen“ bei nutzlosem Lüften.
  Ergebnis: **48/48 bestanden**, keine Warnungen oder Fehler im HA-Log.
