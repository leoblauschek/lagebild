# Lagebild

Ein statisches Nachrichten-Dashboard für KI, deutsche und europäische Politik sowie Weltpolitik. Es wird jeden Abend automatisch neu gebaut und über GitHub Pages veröffentlicht.

## Das Wichtigste

- Null OpenAI- oder LLM-Aufrufe: Der laufende Betrieb verbraucht keine ChatGPT-Tokens.
- Null kostenpflichtige APIs: Quellen werden ausschließlich über frei erreichbare RSS- und Atom-Feeds abgerufen.
- Kein Server und keine Datenbank: GitHub Actions baut eine einzelne statische HTML-Datei.
- Sicherheitsnetz: Wenn zu wenige Meldungen oder Themen eintreffen, stoppt der Lauf. Die letzte vollständige Ausgabe bleibt online.
- Jede Meldung ist ausklappbar und führt zur Originalquelle. Reddit-Einträge werden deutlich als Community-Signale markiert.

## Automatischer Ablauf

1. GitHub Actions startet täglich um 18:30 Uhr in der Zeitzone Europe/Berlin.
2. pipeline/update_dashboard.py lädt die Feeds parallel.
3. Ähnliche Überschriften werden zusammengeführt.
4. Meldungen werden nach Aktualität, Quellenart und Themenquote ausgewählt.
5. Tests und Qualitätsprüfung laufen vor jeder Veröffentlichung.
6. Das Ergebnis in dist/index.html wird als GitHub-Pages-Artefakt bereitgestellt.

Der Workflow lässt sich zusätzlich unter **Actions → Abendbericht aktualisieren → Run workflow** manuell starten.

## Quellen

Die Liste liegt in pipeline/sources.json. Enthalten sind offizielle Feeds von OpenAI, Google DeepMind, Hugging Face und der Bundesregierung, Tagesschau, thematische Google-News-RSS-Suchen sowie Reddit-Feeds.

X ist bewusst nicht direkt eingebunden: Eine robuste offizielle X-Anbindung ist nicht dauerhaft kostenlos. Diese Einschränkung verhindert versteckte Kosten und fragile Umgehungslösungen.

## Lokal prüfen

Voraussetzung ist Python 3.11 oder neuer; zusätzliche Pakete werden nicht benötigt.

    python -m unittest discover -s tests -v
    python pipeline/update_dashboard.py --fixture pipeline/fixtures/articles.json
    node scripts/static-preview.mjs

Danach ist die Vorschau unter http://127.0.0.1:4173 erreichbar.

## Einmalige GitHub-Einrichtung

1. Repository als **public** anlegen und diesen Code auf main pushen.
2. Unter **Settings → Pages → Build and deployment** die Quelle **GitHub Actions** wählen.
3. Den Workflow einmal manuell starten.

Danach läuft die Aktualisierung vollständig automatisch. Bei öffentlichen Repositories sind GitHub Pages und die üblichen Standard-Runner im GitHub-Free-Modell nutzbar.
