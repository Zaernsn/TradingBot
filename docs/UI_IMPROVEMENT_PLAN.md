# UI-Verbesserungsplan für den Trading-Bot

## Zielbild

Die Oberfläche soll innerhalb weniger Sekunden vier Fragen beantworten:

1. Ist mein Konto sicher und synchronisiert?
2. Darf der Bot aktuell neue Live-Käufe ausführen?
3. Falls nein: Was blockiert ihn und was muss ich tun?
4. Was hat der Bot zuletzt entschieden oder ausgeführt?

Die UI darf technische Diagnosewerte zeigen, soll sie aber immer zuerst in
verständliche Sprache übersetzen. Änderungen an der Oberfläche dürfen keine
Order-, Risiko-, Reconciliation- oder Freigaberegel umgehen.

## Aktuelle Hauptprobleme

- Dashboard, Kraken-Konto, Strategieforschung, Watchlist und Aktivität konkurrieren
  auf einer langen Seite um Aufmerksamkeit.
- Statusfelder wie `development_expectancy_positive` werden ungefiltert angezeigt.
- `NO LIVE CANDIDATE` erklärt nicht sofort, ob Forschung läuft, alle Kandidaten
  abgelehnt wurden oder Daten fehlen.
- Die wichtigen Zustände Live-Modus, Bot läuft, Konto synchron, Strategie freigegeben
  und neuer Kauf möglich werden nicht als zusammenhängende Kette dargestellt.
- Settings enthält sehr viele Kontrollen auf einer Seite; Abhängigkeiten und wirksame
  Grenzwerte sind schwer zu erkennen.
- Emergency Stop ist sichtbar, aber die genaue Wirkung – keine neuen Orders,
  bestehende Positionen bleiben erhalten – sollte vor der Bestätigung erklärt werden.
- Desktop ist funktionsreich, mobile Priorisierung und Tabellenbedienung benötigen
  einen eigenen Abnahmeschritt.

## Informationsarchitektur

### 1. Dashboard – Betrieb

Oberhalb des Folds erscheinen nur:

- Live-/Paper-Modus;
- Bot läuft/gestoppt;
- Kraken synchron/nicht synchron;
- Cash, Equity und offene Positionen;
- Status „Neue Käufe möglich“ mit einem eindeutigen Ja/Nein;
- wichtigste nächste Aktion.

Darunter folgen in dieser Reihenfolge:

1. Sicherheits- und Blockerübersicht;
2. offene Positionen und aktive Schutzregeln;
3. Watchlist und aktuelle Signale;
4. letzte Orders und Trades;
5. Kraken-Kontoverlauf.

### 2. Strategy Lab – Forschung

Die Strategieforschung erhält eine eigene Seite statt einer einzelnen Dashboard-Karte:

- Pipeline: Historisch → Holdout → Shadow → Canary → Live;
- Kandidatenanzahl je Status;
- aktiver oder nächster Kandidat;
- Shadow-Tage und geschlossene Trades als Fortschrittsbalken;
- übersetzte bestandene und fehlgeschlagene Prüfungen;
- Kennzahlen je Zeitraum mit Kosten und Benchmark;
- Metadata-Export und sicherer Import mit Hinweis `IMPORTED_UNVERIFIED`;
- Historie von Promotion, Ablehnung und Suspension.

### 3. Settings – Konfiguration

Settings wird in geführte Bereiche geteilt:

- Strategie und Marktuniversum;
- Positionsgröße und Exposure;
- Stops, Drawdown und Tageslimits;
- Gebühren, Slippage und Liquidität;
- Kraken-Verbindung;
- Live-Aktivierung und Recovery;
- Daten-/Metadata-Verwaltung.

Oben bleibt eine kompakte Zusammenfassung der tatsächlich wirksamen Limits. Canary
zeigt beispielsweise: „maximal 2 Positionen, zusammen 25 % = derzeit ca. 18,25 €“.

## Release UI-A – verständliche Statussprache

### Umsetzung

- Zentrale Mapping-Datei für Statuscodes, Prüfnamen, Titel, Erklärung und empfohlene
  Aktion erstellen.
- Rohwerte nur in einem aufklappbaren Diagnosebereich anzeigen.
- Beispielsweise:
  - `development_expectancy_positive` → „Im Entwicklungszeitraum durchschnittlich
    unprofitabel“;
  - `holdout_closed_trades_at_least_30` → „Nur 2 von 30 erforderlichen Test-Trades“;
  - `profit_concentration_within_80pct` → „Ergebnis hängt zu stark von wenigen
    Gewinnern ab“.
- Zustände farblich und textlich unterscheiden: Information, wartet, Aktion nötig,
  blockiert, kritisch.
- Farbe niemals als einziges Unterscheidungsmerkmal verwenden.

### Abnahme

- keine technischen Snake-Case-Bezeichner in der Standardansicht;
- jeder Blocker enthält Bedeutung, aktuellen Wert, Zielwert und nächste Aktion;
- Screenreader liest Status und Dringlichkeit verständlich vor.

## Release UI-B – Live-Readiness und Sicherheitszentrum

### Umsetzung

- Eine horizontale Readiness-Kette anzeigen:
  `Kraken verbunden → Konto abgeglichen → Bot läuft → Daten frisch → Kandidat
  freigegeben → Kauf möglich`.
- Der erste fehlgeschlagene Schritt wird hervorgehoben; nachgelagerte Schritte werden
  als „wartet“ statt als zusätzlicher Fehler dargestellt.
- Reconciliation-, UNKNOWN-Order- und Bilanzabweichungen erhalten einen festen,
  nicht wegscrollbaren Sicherheitshinweis.
- Emergency Stop öffnet einen Bestätigungsdialog mit präzisen Folgen.
- „Bot stoppen“ und „Emergency Stop“ visuell und sprachlich klar trennen.

### Abnahme

- Nutzer erkennt in höchstens zehn Sekunden, ob neue Live-Käufe möglich sind;
- kritische Finanzzustände können nicht durch normale Warnungen verdeckt werden;
- keine UI-Aktion verändert stillschweigend den Handelsmodus oder liquidiert Bestände.

## Release UI-C – Strategy Lab und Canary-Transparenz

### Umsetzung

- Neue Route `/strategy-lab` und Navigationseintrag hinzufügen.
- Statusübersicht mit Karten für Baselines, abgeleitete Kandidaten, Shadow, Canary,
  Live, abgelehnt und suspendiert.
- Kandidatendetail zeigt Development, Validation, Holdout, Stress und Benchmark in
  einer vergleichbaren Tabelle.
- Canary-Karte zeigt:
  - maximal zwei Positionen;
  - 25 % gesamte Canary-Exposure;
  - aktuellen EUR-Grenzwert;
  - aktuell belegtes und verbleibendes Budget;
  - Fortschritt zu zehn abgeglichenen profitablen Ausstiegen;
  - Gründe für eine mögliche Suspension.
- Metadata-Export als Download und Import über Dateiauswahl; vor Import Vorschau und
  deutlicher Hinweis, dass keine Live-Freigabe übernommen wird.

### Abnahme

- historische Ablehnung ist von laufender Shadow-Beobachtung klar unterscheidbar;
- alle Promotion-Gates sind mit Ist-/Sollwert sichtbar;
- Import kann niemals als lokale oder Live-Freigabe erscheinen.

## Release UI-D – Settings vereinfachen

### Umsetzung

- Lange Settings-Komponente in kleinere Abschnittskomponenten zerlegen.
- Grundansicht zeigt empfohlene Einstellungen; Expertenwerte liegen unter
  „Erweiterte Einstellungen“.
- Prozentwerte zusätzlich als EUR-Auswirkung auf Basis der aktuellen Equity zeigen.
- Abhängigkeiten direkt berechnen: wirksames Positionslimit ist das Minimum aus
  Positions-, Exposure-, Canary-, Cash-, Memecoin- und Investmentlimit.
- Vor dem Speichern eine Änderungszusammenfassung anzeigen, insbesondere bei höheren
  Risikolimits.
- Ungespeicherte Änderungen, Speichern-Erfolg und Backend-Validierungsfehler pro Feld
  darstellen.

### Abnahme

- Nutzer kann erkennen, welches Limit eine Order tatsächlich begrenzt;
- riskantere Änderungen benötigen eine bewusste Bestätigung;
- Navigation und Fokus bleiben nach Validierungsfehlern erhalten.

## Release UI-E – responsive Qualität, Barrierefreiheit und Tests

### Umsetzung

- Mobile Karten statt horizontal überlaufender Tabellen; Detailzeilen aufklappbar.
- Einheitliche Lade-, Leer-, Fehler- und veraltete-Datenzustände.
- Zeitstempel immer mit Zeitzone beziehungsweise „vor X Minuten“ plus exaktem Tooltip.
- Tastaturbedienung, sichtbare Fokusrahmen, semantische Überschriften, Dialogfokus und
  ausreichende Kontraste prüfen.
- Frontend-Tests für Statusübersetzung, Readiness-Kette, Canary-Budget, Emergency-
  Dialog, Metadata-Import und responsive Hauptansichten ergänzen.
- Produktionsbuild und visuelle Prüfung bei 360, 768, 1280 und 1600 Pixel Breite.

### Abnahme

- keine kritische Aktion nur per Farbe oder Hover verständlich;
- keine abgeschnittenen Beträge, Statuswerte oder Aktionsknöpfe auf Mobilgeräten;
- automatisierte Tests und Produktionsbuild sind grün.

## Empfohlene Reihenfolge

1. UI-A: Statusübersetzung und konkrete Ist-/Sollwerte.
2. UI-B: Readiness-Kette und Sicherheitsmeldungen.
3. UI-C: eigene Strategy-Lab-Seite.
4. UI-D: Settings aufteilen und wirksame Limits erklären.
5. UI-E: Responsive, Accessibility und visuelle Regression.

## Technische Arbeitspakete

- `frontend/src/lib/statusCopy.ts`: zentrale Übersetzungen und Handlungshinweise;
- `frontend/src/components/LiveReadiness.tsx`: Readiness-Kette;
- `frontend/src/components/SafetyBanner.tsx`: kritische Betriebszustände;
- `frontend/src/pages/StrategyLab.tsx`: Forschungs- und Canary-Ansicht;
- `frontend/src/components/CandidateDetails.tsx`: Prüfungen und Kennzahlen;
- `frontend/src/components/EffectiveLimits.tsx`: wirksame EUR-/Prozentlimits;
- `frontend/src/pages/Settings.tsx`: Zerlegung in Abschnittskomponenten;
- `frontend/src/services/api.ts`: strukturierte Research-/Readiness-Daten;
- Backend-Statusantworten: Istwert, Sollwert, Schweregrad und sichere Aktion ergänzen,
  ohne Order- oder Freigabelogik ins Frontend zu verschieben.

## Definition of Done

- Die Oberfläche beantwortet klar, warum der Bot handelt oder nicht handelt.
- Kritische Live-Probleme sind deutlich von normalen Forschungsablehnungen getrennt.
- Canary-Limits und tatsächlich verbleibendes Budget sind transparent.
- Keine UI-Änderung schwächt serverseitige Sicherheitsregeln.
- Desktop und Mobile bestehen Funktions-, Accessibility- und Produktionsbuildtests.
