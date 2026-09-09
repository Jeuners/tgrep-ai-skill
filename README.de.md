# tgrep AI Skill

[English](README.md) | **Deutsch**

Lokale, indexierte Suche für **Claude Code und Codex** – mit frei wählbaren
Verzeichnissen und optionalen Antworten von **Qwen über Ollama**.

Ein gemeinsamer Skill, eine CLI, gemeinsame Indizes. tgrep sucht Text und Code;
Qwen übersetzt Fragen in Suchbegriffe und beantwortet sie anhand gefundener
Ausschnitte. Die Hauptmodelle von Claude und Codex werden dabei nicht ersetzt.

## Installation

Voraussetzungen: macOS oder Linux (ARM64/x86_64), Git, Python **3.10+** mit venv.
Windows: innerhalb von WSL installieren. Kein sudo, kein pip und keine
Python-Paketdownloads erforderlich. Der Installer lädt tgrep **1.0.5** und
ripgrep **15.2.0** aus offiziellen Releases; SHA256-Werte stehen fest in
[dependencies.lock.json](dependencies.lock.json).

~~~sh
git clone https://github.com/Jeuners/tgrep-ai-skill.git
cd tgrep-ai-skill
./install.sh
export PATH="$HOME/.local/bin:$PATH"
local-search doctor
~~~

Der Installer richtet beide Skills ein:

- Claude Code: ~/.claude/skills/local-search/
- Codex: ~/.agents/skills/local-search/

Er installiert einen unabhängigen Laufzeitordner unter
~/.local/share/tgrep-ai-skill/. Der Checkout kann danach verschoben werden.
Bestehende Konfiguration und Modellwahl bleiben erhalten; fremde gleichnamige
Launcher oder Skills werden nicht überschrieben. Die Home-Wurzel wird registriert,
aber noch nicht indexiert. Neue Agent-Sitzung öffnen, falls der Skill nicht erscheint.

Nur einen Agenten installieren:

~~~sh
./install.sh --target claude
./install.sh --target codex
~~~

**Installation durch einen Agenten:** Gib Claude Code oder Codex diesen Auftrag:

> Installiere https://github.com/Jeuners/tgrep-ai-skill für Claude Code und Codex.
> Lies zuerst die README, führe den Installer aus und prüfe local-search doctor.
> Verwende mein vorhandenes Ollama-Modell. Starte noch keine Home-Indexierung.

## Ollama und Qwen

Die direkte Suche funktioniert ohne LLM. Für **ask** muss
[Ollama](https://ollama.com/download) separat installiert und gestartet sein:

~~~sh
ollama serve
~~~

Bei laufender Ollama-App ist kein zweiter Server nötig. In einem weiteren Terminal:

~~~sh
ollama list
# Nur falls das Modell fehlt: rund 6,6 GB Download
ollama pull qwen3.5:latest
local-search doctor
~~~

Dieses Modell aus der offiziellen Ollama-Library ist die Voreinstellung. Ein
anderes installiertes Modell wählen, etwa eine kleinere Variante:

~~~sh
local-search model qwen3.5:4b
~~~

Modell und Loopback-URL stehen in ~/.config/local-search/config.json.
Vor jeder Modellanfrage werden die Ollama-Metadaten geprüft: Cloud-Modelle,
Remote-Aliasse und Modelle ohne erkennbare lokale Gewichte werden abgewiesen.
Der Installer lädt weder Ollama noch Modellgewichte ungefragt herunter.
Modellgewichte sind nicht Teil dieses MIT-Projekts; ihre eigenen Lizenzbedingungen
gelten. Der Standardtag verweist auf die jeweils aktuelle Version und kann sich
ändern. Ein Tag wie qwen3.5:4b legt die Modellgröße fest, bleibt aber ebenfalls
veränderlich und garantiert keine unveränderten Modellgewichte.

## Home und weitere Ordner

~~~sh
local-search preview home
local-search index home

local-search add projekte "/Volumes/Projekte"
local-search preview projekte
local-search index projekte

local-search add backend "$HOME/Desktop/backend" --exclude vendor --max-filesize 16M
local-search status
~~~

**preview** listet eine Dateianzahl, Beispiele und Ausschlüsse; die Zahl ist eine
Schätzung vor Inhalts-/Binärprüfung. Bei gekappter Ausgabe ist sie eine Untergrenze.
**index** baut synchron auf und startet danach einen Hintergrundserver. Es gibt
keinen Login-Autostart; eine spätere Suche startet den Server bei Bedarf.

Standardausschlüsse: .git, node_modules, .venv, venv, target, dist, build,
__pycache__, .ssh, .gnupg, .aws, .azure, .ollama, .Trash, Library, Caches.
Ausschlüsse gelten als **Verzeichnisnamen auf jeder Ebene**.
Standard-Dateigrößenlimit: **8 MiB**. Normale Ignore-Regeln gelten auch außerhalb
eines Git-Repositories. Symlinks werden nicht verfolgt.

Versteckte Nachkommen werden nicht indexiert: tgrep 1.0.5 unterstützt
serve --hidden nicht. Einen versteckten Projektordner gegebenenfalls als eigene
Wurzel registrieren. PDFs, Office, Bilder, Archive und semantische Embedding-Suche
sind nicht enthalten. Ausschlüsse ersetzen keine allgemeine Geheimniserkennung.

## Suchen

~~~sh
local-search search "WebSocket" --root projekte
local-search search 'auth|login' --regex --root backend
local-search ask "Wo wird die Anmeldung geprüft?" --root backend
local-search search "TODO" --root backend --root projekte
local-search search "Rechnungsnummer" --all --paths-only
local-search search "removed_function" --root backend --fresh
~~~

Ohne --root wird die spezifischste registrierte Wurzel um das aktuelle
Arbeitsverzeichnis verwendet. --all durchsucht alle registrierten Wurzeln.
Überlappende Treffer werden nach kanonischem Dateipfad und Zeilennummer dedupliziert;
überlappende Indizes können trotzdem zusätzlichen Speicher und Sucharbeit kosten.

Ausgabe: JSON mit Treffern, Quellen, Backend, Aktualität, Warnungen und
truncated. Standardmäßig höchstens 40 Treffer. --limit 100 erhöht das Limit.
Jeder Report nennt zusätzlich match_count: die pro Wurzel und Suchanfrage
gelieferten Treffer vor der globalen Zusammenführung. Diese Zahl ist bereits
durch das jeweilige Suchlimit begrenzt; bei report.truncated können weitere,
nicht gezählte Treffer existieren. Die Summe kann wegen der Deduplizierung größer
als die zusammengeführte Trefferliste sein. Bei globaler Kappung die ausgewählten
Wurzeln einzeln durchsuchen oder --limit erhöhen.
Zeilentexte sind auf 2.000 Zeichen begrenzt; ask erhält höchstens rund 12.000
JSON-Zeichen Quellenkontext und führt maximal drei Suchbegriffe pro Wurzel aus.

Ein laufender Index ist **eventuell konsistent**. Während Aufbau oder erkennbar
gestörter Aktualisierung wird frisch mit ripgrep gesucht. --fresh erzwingt das
auch für wichtige Negativbefunde. Ein gleichzeitig verändertes Dateisystem ist
kein atomarer Snapshot. ripgrep und tgrep können bei Randfällen ihrer
Ignore-/Binärbehandlung abweichen.

Exitcodes: **0** Erfolg/Treffer, **1** keine Treffer, **2** Fehler,
**130** abgebrochen. Ollama-Ausfall ist ein Fehler bei ask; search bleibt nutzbar.

In Claude Code: /local-search. In Codex: $local-search.
Bei expliziten Vorgaben „immer zuerst rg“ muss die übergeordnete Regel eine
Ausnahme erlauben; der Skill überschreibt sie nicht.

**Datengrenze:** tgrep und Qwen arbeiten lokal. Ausgaben, die ein Claude-/Codex-Agent
liest, gelangen dennoch in dessen Kontext. --paths-only unterdrückt Ausschnitte
und generierte Antworten, nicht Dateinamen. Bei ask --paths-only wird nur die
Frage zur lokalen Suchplanung an Ollama geschickt.

## Wartung

~~~sh
local-search stop home
local-search index home      # vollständiger Neuaufbau mit anschließendem Start
local-search remove backend # Registrierung entfernen, Index behalten
~~~

Konfiguration: ~/.config/local-search/config.json.
Indizes/Status/Serverlogs: ~/.local/share/local-search/indexes/.
XDG_CONFIG_HOME und XDG_DATA_HOME werden unterstützt.
Eine geänderte Wurzelkonfiguration bekommt einen neuen Indexpfad. Vor manuellen
Konfigurationsänderungen den Server stoppen; danach neu indexieren.

Update im Checkout:

~~~sh
git pull --ff-only
./install.sh
~~~

Für reproduzierbare Installation vorher einen Release-Tag auschecken. Updates
legen einen neuen Laufzeitordner an; alte bleiben für laufende Server erhalten.
Server stoppen und neu starten, damit sie die neue Binärdatei verwenden.

Deinstallation:

~~~sh
local-search stop home
# Weitere laufende Wurzeln ebenfalls stoppen.
./install.sh --uninstall
~~~

Entfernt den verwalteten Launcher und die Skills. Konfiguration, Indizes und alte
Laufzeitordner bleiben absichtlich erhalten und können nach Prüfung manuell
entfernt werden.

## Fehlerbehebung und Entwicklung

- command not found: PATH setzen oder ~/.local/bin/local-search aufrufen.
- Python/venv fehlt: Python 3.10+ installieren; unter Debian/Ubuntu gegebenenfalls
  das passende python3-venv-Paket.
- Modell nicht erreichbar: ollama list, laufende App bzw. ollama serve prüfen.
- macOS-Zugriff verweigert: betreffende Ordner benötigen ggf. Zugriff für das
  verwendete Terminal. Nicht lesbare Pfade werden als Fehler gemeldet.
- Index hängt: local-search status und server.log im gemeldeten Indexpfad lesen.
- "PID identity changed": die Identität der vermerkten Prozess-ID stimmt nicht
  mehr mit dem gespeicherten Suchserver überein; deshalb wird kein Signal gesendet.
  Mit ps die gemeldete PID prüfen. Nur wenn die Zuordnung nachweislich veraltet ist
  und kein Suchserver mehr diesen Index verwendet, die gemeldete owner.json
  entfernen. Einen fremden Prozess dafür nicht beenden; anschließend erneut starten.
- Große Verzeichnisse: mit ausgewählten Projektwurzeln beginnen; Home verbraucht
  je nach Inhalt erheblich Plattenplatz. Der Server startet mit 512 MiB
  Indexaufbau-Budget und 25 % CPU-Budget; dies ist kein hartes Prozess-RAM-Limit.
- Offline: Releasearchive vorher herunterladen und
  ./install.sh --asset-cache /pfad/zu/archiven verwenden. Fehlende Archive werden
  weiterhin online angefordert. Abhängigkeiten werden stets per SHA256 geprüft.

~~~sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
~~~

Integrationstests mit echten Binärdateien:

~~~sh
LOCAL_SEARCH_INTEGRATION=1 \
LOCAL_SEARCH_TGREP=/pfad/zu/tgrep \
LOCAL_SEARCH_RG=/pfad/zu/rg \
PYTHONPATH=src python3 -m unittest discover -s tests -v
~~~

Vollständige isolierte Installation inklusive Update und Deinstallation:
python3 scripts/smoke_install.py. Optionaler Test des vorhandenen lokalen Modells
mit ausschließlich synthetischem Quelltext: python3 scripts/smoke_ollama.py.

## Herkunft und Lizenz

MIT, siehe [LICENSE](LICENSE). Unabhängiges Integrationsprojekt, kein offizielles
Microsoft-, Anthropic- oder OpenAI-Produkt.

Autorschaft: Implementierung geschrieben mit OpenAI Astra. Review und
Überarbeitung durch Claude von Anthropic.
AI Operator: [H.G.O.D.](https://github.com/Jeuners).

- [Microsoft tgrep](https://github.com/microsoft/tgrep), MIT
- [ripgrep](https://github.com/BurntSushi/ripgrep), MIT oder Unlicense
- [Ollama API](https://docs.ollama.com/api/chat)
- [Claude Code Skills](https://code.claude.com/docs/en/skills)

Die Installer-Downloads enthalten offizielle Binärdateien; Quellcode und
Lizenztexte der Abhängigkeiten sind in deren verlinkten Repositories verfügbar.
