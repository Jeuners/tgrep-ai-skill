# Handoff an Astra: tgrep-ai-skill

Repo: https://github.com/Jeuners/tgrep-ai-skill
Stand: 08.09.2026
Status ergänzt: 09.09.2026. Die Review-Befunde unten beschreiben den damaligen Stand.
Rollen: Astra hat implementiert, Claude (Anthropic) hat reviewt, H.G.O.D. ist AI Operator.

Dieses Dokument ist die Übergabe nach dem externen Review. Es sagt dir, was geprüft
wurde, was geändert wurde, was du nicht anfassen sollst und was als Nächstes ansteht.

---

## 1. Review-Ergebnis

Der Code wurde geklont, gelesen, getestet und gegen die echten Upstream-Artefakte
geprüft. Ergebnis: solide. Rund 850 Zeilen Quellcode, 330 Zeilen Tests, keine
Laufzeitabhängigkeit außer der Standardbibliothek.

Verifiziert, nicht nur gelesen:

- Beide SHA256-Werte in `dependencies.lock.json` stimmen exakt mit den echten
  Release-Artefakten überein (tgrep `072b8b5d...`, ripgrep `33e15bcf...`).
- tgrep v1.0.5 und ripgrep 15.2.0 sind die jeweils aktuellsten Upstream-Releases.
- Die README-Aussage zu `serve --hidden` stimmt. Die Binary lehnt das Flag aktiv ab
  ("it would be ignored and the index would not match what you asked for").
- 19 Unit-Tests laufen in 0,16 s durch, 3 übersprungen (Integration).
- `scripts/smoke_install.py` deckt Install, Reinstall mit Einstellungserhalt, echte
  Suche und Deinstall ab, inklusive Prefix mit Leerzeichen. Es ruft die Unit-Tests
  mit `LOCAL_SEARCH_INTEGRATION=1` mit auf, CI ist damit vollständig.

Besonders positiv bewertet wurden: Tar-Extraktion nur genau einer regulären Datei,
PID-Identitätsprüfung vor jedem Signal, kein SIGKILL, Verweigerung fremde Launcher
oder Skills zu überschreiben, `python -I` im Launcher, Loopback-Zwang für Ollama, und
die durchgehend ehrliche Dokumentation der Grenzen (eventual consistency,
`count_is_lower_bound`, Datengrenze zum Agenten-Kontext).

---

## 2. Was im Review-Commit geändert wurde

Commit `5e58144` "Default to the official qwen3.5 tag, report per-root match counts".
Der externe Patch trug ursprünglich die Commit-ID `8151ec6`; im Repository wurde
er als `5e58144` angewendet. `8151ec6` ist kein Commit dieses Repositories.
Fünf Dateien, 31 Zeilen rein, 10 raus. Tests danach grün.

### 2.1 Default-Modell (`src/local_search/config.py`)

`MODEL` ist jetzt `qwen3.5:latest` statt `srchmnmichael/qwen3.5-9B-uncensored:latest`.

Begründung: Alles andere im Projekt ist SHA-gepinnt, ausgerechnet die Komponente, die
Codeausschnitte zu sehen bekommt, hing an einem mutablen `:latest`-Tag aus einem
unauditierten Community-Namespace. Das war der schwächste Punkt der Lieferkette und
hätte dem Projekt jede Bewertung im Unternehmenskontext gekostet. "uncensored" bringt
für einen Code-Zusammenfasser keinen Mehrwert.

Geprüft: `qwen3.5` existiert in der offiziellen Ollama-Library mit den Varianten
0.8b, 2b, 4b, 9b, 27b, 35b, 122b; `latest` sind 6,6 GB. README nennt jetzt die
korrekte Downloadgröße und empfiehlt einen Tag mit fester Größe (`qwen3.5:4b`) für
reproduzierbare Setups. Das Beispiel bei `local-search model` wurde entsprechend
angepasst, damit es nicht mehr mit dem Default identisch ist.

Bestandsinstallationen sind nicht betroffen, der Installer bewahrt eine vorhandene
Modellwahl.

### 2.2 `match_count` pro Report (`src/local_search/cli.py`, `query_roots`)

Bisher wurde `matches` aus dem Ergebnis gepoppt, bevor der Report gebaut wurde. Bei
`--all` wird global nach Pfad sortiert und auf `limit` gekappt, alphabetisch späte
Wurzeln konnten also komplett verschwinden, ohne dass der Agent sehen konnte, welche.
`truncated` allein sagt nur, dass etwas fehlt, nicht was.

Jeder Report trägt jetzt `match_count` für seine Wurzel und Suchanfrage. Funktional
geprüft mit zwei Wurzeln und `--limit 1`: die zweite Wurzel liefert einen Treffer,
fällt aus der zusammengeführten Liste, und der Report weist ihn aus.

`skills/local-search/SKILL.md` und README erklären beide, wie das zu lesen ist. Der
Skill weist den Agenten an, bei `truncated` die Counts mit den gelieferten Treffern zu
vergleichen und Wurzeln einzugrenzen oder `--limit` zu erhöhen, statt eine
Teilmenge als vollständig zu melden.

### 2.3 Wiederherstellungsweg bei PID-Konflikt (`src/local_search/engine.py`)

`owned_pid` warf bisher "PID identity changed; refusing to signal an unrelated
process." ohne Ausweg. Der Fehler blockiert `start` dauerhaft, die Lösung stand
nirgends. Die Meldung nennt jetzt die konkrete PID und den Pfad zur `owner.json`, die
README hat einen eigenen Punkt in der Fehlerbehebung.

### 2.4 Autorschaft (README, Abschnitt "Herkunft und Lizenz")

> Autorschaft: Implementierung geschrieben mit OpenAI Astra. Review und Überarbeitung
> durch Claude von Anthropic. AI Operator: H.G.O.D.

Im Commit zusätzlich als Trailer: `Authored-by: OpenAI Astra`, `Reviewed-by:`,
`Co-authored-by:`, `AI-Operator: H.G.O.D.`

---

## 3. Invarianten. Bitte nicht brechen

Diese Eigenschaften sind der Grund, warum das Projekt im Review gut abgeschnitten hat.
Wenn eine davon fallen soll, vorher begründen, nicht nebenbei entfernen.

1. Keine Laufzeitabhängigkeiten außer der Standardbibliothek. `dependencies = []`
   bleibt leer, der venv wird ohne pip gebaut.
2. Jede heruntergeladene Binärdatei wird per SHA256 gegen `dependencies.lock.json`
   geprüft, bevor sie ausgeführt wird. Aus dem Archiv wird ausschließlich genau eine
   reguläre Datei extrahiert, niemals Pfade oder Symlinks.
3. Ollama nur über Loopback, ohne Proxy, ohne Redirects, mit Cloud-Modell-Abweisung
   vor dem ersten Textversand. Modellausgabe ist Daten, niemals Kommando.
4. Kein SIGKILL, keine Signale an Prozesse ohne vorherige Identitätsprüfung, kein
   Überschreiben fremder Launcher oder Skills.
5. Suchergebnisse werden gegen die registrierte Wurzel validiert.
6. Die Dokumentation bleibt ehrlich über Grenzen. Kein "semantische Suche", kein
   "vollständig", kein Verschweigen der eventual consistency. Das ist ein Merkmal des
   Projekts, kein Makel.
7. Tests bleiben grün und decken weiter Sicherheitseigenschaften ab, nicht nur
   Happy Paths.
8. Stil: Zeilen bis rund 88 Zeichen, Modul-Docstrings als Einzeiler, Kommentare
   erklären das Warum, nicht das Was.

---

## 4. Offene Punkte

### 4.1 Für H.G.O.D., nicht für dich (braucht Push- bzw. UI-Rechte)

- `v0.1.0` zeigt auf `a52a726`, vor den Review-Korrekturen, und bleibt unverändert.
  `v0.1.1` wurde am 09.09.2026 auf dem korrigierten Stand `0fce1aa` veröffentlicht.
- Repo-Beschreibung und Topics: `claude-code`, `codex`, `agent-skills`,
  `ollama`, `tgrep`, `ripgrep` wurden am 09.09.2026 auf GitHub gesetzt.

### 4.2 Hauptaufgabe für dich: englische README

Erledigt in `632f6cc`: `README.md` ist Englisch, `README.de.md` enthält die deutsche
Fassung, beide sind gegenseitig verlinkt. Dieser Dokumentationscommit liegt nach
dem für `v0.1.1` ausgewählten Code-Stand `0fce1aa`.
Die folgenden Anforderungen bleiben als ursprünglicher Auftrag dokumentiert.

Die Zielgruppe für Claude-Code- und Codex-Skills ist überwiegend englischsprachig, ein
rein deutsches README kostet praktisch die gesamte Auffindbarkeit. Vorschlag: `README.md`
englisch als Primärdokument, `README.de.md` als deutsche Fassung, gegenseitig oben
verlinkt.

Anforderungen:

- Inhaltsgleich, keine Kürzung der Grenzen-Abschnitte. Gerade "Datengrenze",
  eventual consistency und der Hinweis, dass Ausschlüsse keine Geheimniserkennung
  sind, müssen in beiden Fassungen stehen.
- Alle Kommandos, Pfade, Flags und Zahlen identisch. Bei Divergenz gewinnt der Code.
- `install.sh --uninstall`, Offline-Installation und Fehlerbehebung vollständig
  übernehmen.
- Der Autorschafts-Abschnitt bleibt in beiden Fassungen.

Die endgültige Entscheidung, welche Sprache primär wird, trifft H.G.O.D.

### 4.3 Kleinere Codepunkte aus dem Review, optional

- `localhost` wird als Ollama-Host abgewiesen, nur literale Loopback-IPs sind
  erlaubt. Bewusst richtig, für Nutzer aber überraschend. Gehört als Zeile in die
  Fehlerbehebung.
- Für die PID-Identitätsprüfung wäre unter Linux `/proc/<pid>/cmdline` robuster als
  `ps`, mit `ps` als Fallback für macOS. `ps` fehlt in schlanken Containern.
- In `engine.search` wird im Malformed-JSON-Zweig `data.splitlines()` innerhalb der
  Schleife neu berechnet und per Wertvergleich gegen die letzte Zeile geprüft.
  Praktisch harmlos, weil nur bei `truncated` erreichbar, aber unsauber. Sauberer
  wäre Iteration mit Index oder Behandlung nach der Schleife.
- Ein `SECURITY.md` mit Meldeweg wäre für ein Projekt mit diesem Anspruch
  naheliegend, sobald es öffentlich beworben wird.

---

## 5. Verifikation vor jedem Commit

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Vollständig, mit echten Binärdateien, Install/Reinstall/Uninstall:
python3 scripts/smoke_install.py

# Optional, gegen das lokal installierte Modell, nur synthetischer Quelltext:
python3 scripts/smoke_ollama.py
```

Bei Änderungen an Flags immer gegen die echte Binary prüfen, nicht gegen die
Erinnerung. `tgrep serve --help` und `tgrep index --help` sind die Referenz. Genau
das hat sich beim `--hidden`-Punkt bewährt: die Behauptung in der README war
korrekt, weil sie an der Binary getestet war.

---

## 6. Offene Fragen an dich

1. Gibt es einen Grund für das "uncensored"-Modell, den das Review nicht sieht? Wenn
   ja, bitte nennen, dann wird es als dokumentierte Option statt als Default geführt.
2. Soll `--limit` bei mehreren Wurzeln fair verteilt werden (Round Robin pro Wurzel)
   statt global nach Pfad zu kappen? `match_count` macht die Kappung jetzt sichtbar,
   löst sie aber nicht.
3. Ist ein zweiter unterstützter tgrep-Versionsstand vorgesehen, oder bleibt das
   Lockfile bewusst bei genau einer gepinnten Version?
