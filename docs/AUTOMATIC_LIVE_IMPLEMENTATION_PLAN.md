# Implementierungsplan: belastbarer vollautomatischer Live-Bot

## Zielbild

Der Bot bleibt dauerhaft im Live-Modus. Neue Strategien werden in einem begrenzten,
prüfbaren Regelraum erzeugt, historisch getestet und anschließend auf neuen Kerzen
in persistenten Shadow-Portfolios beobachtet. Nur bestandene Kandidaten erhalten
automatisch eine begrenzte Live-Freigabe. Reale Positionsgrößen werden erst nach
stabiler Canary-Phase erhöht. Kontenabgleich, Ausstiege und ungeklärte Orders haben
zu jedem Zeitpunkt Vorrang vor neuen Einstiegen.

Nicht-Ziele:

- keine freie Erzeugung oder Ausführung von beliebigem Python-Code;
- keine Freigabe aufgrund eines einzelnen Backtests;
- kein Erzwingen von Trades, wenn Markt, Daten oder Kosten ungeeignet sind;
- keine Aufweichung der Duplicate-Order- und Reconciliation-Sperren.

## Ausgangslage

- Live-Buch: aktiv, 72,99 EUR, keine offenen Positionen oder Orders.
- Strategie: `auto`.
- 29 lokal geprüfte Kandidaten (21 Baselines plus 8 begrenzte Ableitungen), alle
  anhand der aktuellen Daten und Kostenannahmen abgelehnt.
- Persistente Nonces, Preflight-Retry und idempotente Order-Intents sind vorhanden.
- Persistente Shadow-Ledger, automatische Canary-Promotion/Rückstufung und
  Forschungsstatus sind implementiert.
- Watchlist-Ausfälle behalten zeitlich begrenzt die letzte verifizierte Auswahl;
  symbolbezogene Entry-Prüfungen bleiben zwingend.
- Verifizierte Kraken-Taker-Gebühr wird persistent in Forschung und Live-Sizing genutzt.

## Umsetzungsstand

- Release A implementiert und lokal verifiziert:
  - Automatic hält eine repräsentative Monitoring-Watchlist unabhängig vom aktuellen
    positiven Auswahl-Momentum;
  - eine höchstens sechs Stunden alte, verifizierte Watchlist überbrückt einen kurzen
    vollständigen Refresh-Ausfall;
  - Auswahlstatus, Alter und letzter erfolgreicher Refresh werden gespeichert;
  - leere Auswahlfehler enthalten jetzt Exception-Typ und sicheren Detailtext;
  - die zuletzt verifizierte Kraken-Taker-Gebühr wird persistent gespeichert und in
    Live-Sizing, Forschung und Settings berücksichtigt;
  - Migration `l90227fees`, 186 Backend-Tests und Frontend-Produktionsbuild bestanden.
- Aktuell verifizierte Gebühr des verbundenen Kontos: 0,8 % für BTC/EUR bei dem von
  Kraken gemeldeten aktuellen Gebührenlevel.
- Releases B bis E implementiert und lokal verifiziert:
  - persistente, idempotente Shadow-Runs, Trades und Equity-Punkte;
  - adaptive Momentum-, Volatilitätstrend-, Breakout-/Liquiditäts- und defensive
    Mean-Reversion-Familien mit höchstens acht kontrollierten Ableitungen;
  - Development/Embargo/Validation/Embargo/Holdout plus Kostenstress;
  - `LIVE_APPROVED_CANARY` mit zwei Positionen und höchstens 25 % Gesamtexposition;
  - automatische Rückstufung bei Order-, Reconciliation-, Bilanz-, Kosten- oder
    Drawdown-Problemen und Vollfreigabe nach zehn profitablen Live-Ausstiegen;
  - Dashboard-Status sowie sichere Metadata-Export-/Import-Endpunkte.
- Verifikation: 191 Backend-Tests und Frontend-Produktionsbuild bestanden;
  Migration `m90227shadow` ist auf der aktuellen PostgreSQL-Datenbank aktiv.

## Reihenfolge und Abhängigkeiten

```text
P0 Live-Betrieb stabilisieren
 ├─ P1 Watchlist/Marktdaten reparieren
 └─ P2 Gebührenwahrheit herstellen
       ↓
P3 Persistente Shadow-Ledger
       ↓
P4 Neue Strategiefamilien + begrenzte Generierung
       ↓
P5 Walk-forward-Auswertung und automatische Promotion
       ↓
P6 Canary-Live-Rollout und automatische Rückstufung
       ↓
P7 Dashboard, Betrieb und Deployment
```

## P0 – Release sichern und reproduzierbare Basis herstellen

### Umsetzung

1. Aktuellen Datenbankstand und aktive Konfiguration sichern.
2. Bestehende 12 Kandidaten inklusive Metriken als unveränderliche Generation 1
   kennzeichnen.
3. Eine eindeutige Strategieversion aus Code-Hash, Parametern, Risikokonfiguration
   und Datenfenster bilden.
4. Backend- und Frontend-Version im Laufzeitstatus anzeigen.
5. Keine Datenbankbereinigung oder Neubewertung bereits geprüfter Kandidaten ohne
   neue Strategieversion zulassen.

### Abnahme

- derselbe Code und dieselben Parameter ergeben dieselbe Kandidaten-ID;
- ein Kandidat wird pro Datenversion höchstens einmal historisch geprüft;
- Migration funktioniert auf frischer und bestehender Datenbank;
- bestehende Live-Bücher, Positionen und Orders bleiben unverändert.

## P1 – Watchlist- und `selection_unavailable`-Blocker beseitigen

### Problem

Discovery meldet aktuell 28 verwertbare Märkte und 10 modellqualifizierte Symbole,
aber `BotState.watchlist` ist leer. Der Bot erstellt Signale, setzt den Regime-Status
jedoch auf `insufficient` und pausiert alle neuen Entries.

### Umsetzung

1. Fehlerursache getrennt für Tageskerzen, Quotes, Markt-Metadaten und AssetSelector
   protokollieren; leere Exception-Texte durch Typ und sicheren Fehlercode ersetzen.
2. Watchlist atomar aktualisieren: erst nach vollständiger erfolgreicher Auswahl die
   bisherige Liste ersetzen.
3. Bei teilweisem Discovery-Fehler die letzte gute Watchlist höchstens sechs Stunden
   behalten. Jeder einzelne Entry benötigt trotzdem frische Quote, Stundenhistorie,
   Spread-, Turnover- und Ordergrößenprüfung.
4. Kernmärkte und Memecoin-Discovery getrennt behandeln. Ein Fehler im Meme-Katalog
   darf die geprüften Kernmärkte nicht entfernen.
5. `selection_available`, Alter der Watchlist und Datenabdeckung als getrennte Felder
   speichern und im Dashboard anzeigen.

### Betroffene Komponenten

- `backend/app/services/asset_selector.py`
- `backend/app/services/bot_service.py`
- `backend/app/services/market_data.py`
- `backend/app/services/meme_discovery.py`
- `frontend/src/pages/Dashboard.tsx`

### Tests

- erfolgreiche Auswahl ersetzt die alte Liste atomar;
- partieller Quote-/Tageskerzenfehler behält nur eine frische letzte gute Liste;
- abgelaufene Liste blockiert Entries;
- Memecoin-Ausfall entfernt keine Kernmärkte;
- jeder Entry bleibt an frische symbolbezogene Daten gebunden;
- leerer Watchlist-Fehler enthält einen verständlichen Fehlercode.

### Abnahme

- drei aufeinanderfolgende Live-Zyklen mit nichtleerer, stabiler Watchlist;
- Regime-Coverage mindestens 80 % der ausgewählten Märkte;
- keine neuen Entries bei veralteten oder unvollständigen Daten;
- Kontenabgleich und Ausstiege funktionieren auch bei Discovery-Ausfall.

## P2 – Gebühren und Ausführungskosten vereinheitlichen

### Umsetzung

1. Verifizierte Kraken-Taker-Gebühr mit Zeitstempel speichern.
2. Für Live-Sizing immer `max(konfigurierte Reserve, verifizierte Gebühr)` verwenden.
3. Für Forschung mindestens die verifizierte Gebühr oder den konservativen 0,4-%-Floor
   verwenden.
4. Einstellung `Fee = 0` nicht mehr als realistische Forschungsannahme darstellen.
5. Dashboard zeigt konfigurierte Reserve, Kraken-Gebühr und tatsächlich verwendeten
   Wert getrennt an.
6. Fehlende oder veraltete Gebührenabfrage blockiert neue Live-Entries, nicht Exits.

### Abnahme

- Laufzeit, Backtest und UI verwenden nachvollziehbar dieselbe Kostenbasis;
- kein Buy überschreitet Cash oder Investmentlimit inklusive Gebühren;
- vorhandene Fehlermeldung „Fee reserve below Kraken taker fee“ tritt nicht mehr als
  Konfigurationsblocker auf;
- Tests decken Quote- und Base-Fee sowie Gebührenstufen ab.

## P3 – Persistente Live-Shadow-Portfolios

### Datenmodell

Neue Tabellen beziehungsweise gleichwertige persistente Modelle:

- `shadow_runs`: Benutzer, Kandidat, Version, Start, Status, Startkapital;
- `shadow_positions`: Symbol, Menge, Einstieg, Gebühren, Eröffnungszeit;
- `shadow_trades`: deterministischer Intent, Seite, Menge, Preis, Kosten, PnL;
- `shadow_equity`: Kandidat, Kerzenzeit, Cash, Exposure, Equity, Drawdown;
- eindeutiger Schlüssel aus Kandidat und abgeschlossener Kerzenzeit.

### Umsetzung

1. Shadow-Schritt ausschließlich auf abgeschlossenen Stundenkerzen ausführen.
2. Nach Neustart exakt am letzten bestätigten Candle-Key fortsetzen.
3. Dieselben Signal-, Risiko-, Gebühren- und Exit-Funktionen wie Backtest und Live
   verwenden.
4. Keine Exchange-Orderfunktion aus Shadow-Code erreichbar machen.
5. Kandidatenversion nach Shadow-Start einfrieren; Code- oder Konfigurationsänderung
   startet einen neuen Lauf.

### Abnahme

- wiederholter Aufruf derselben Kerze erzeugt keinen zweiten Shadow-Trade;
- Neustart verändert Cash, Positionen oder PnL nicht;
- Shadow kann bei aktivem Live-Buch laufen;
- Shadow kann niemals einen `ExecutionOrder` erzeugen;
- Equity-Kurve und alle Trades sind im Nachhinein reproduzierbar.

## P4 – Neue, begrenzte Strategiefamilien

Die nächste Generation soll nicht nur Grenzwerte derselben Momentum-Idee variieren.
Jede Familie wird als feste, geprüfte Implementierung mit einem begrenzten
Parameterraum angelegt.

### Familien

1. **Cross-sectional Momentum**
   - rankt Coins relativ zum gesamten beobachteten Markt;
   - Entry nur für die stärksten liquiden Märkte;
   - Marktbreite muss positiv sein.

2. **Volatilitätsnormalisierter Trend**
   - 24-/72-Stunden-Trend;
   - Signalstärke und Positionsbudget werden durch realisierte Volatilität begrenzt;
   - kein Entry nach extremen Einzelstunden.

3. **Breakout mit Liquiditätsbeschleunigung**
   - Ausbruch über vorherige Hochs nur mit steigendem EUR-Turnover;
   - Spread- und Depth-Limits bleiben Ausführungsgates;
   - separate Parameter für Kerncoins und Memecoins.

4. **Seitwärtsmarkt-Mean-Reversion**
   - nur im nachgewiesenen defensiven/seitwärtigen Regime;
   - keine Mean-Reversion bei fallender Marktbreite;
   - enges Zeitlimit und eigener Exit.

5. **BTC-/ETH-Regimefilter**
   - Altcoin-Entries werden reduziert oder blockiert, wenn BTC und ETH unter ihrem
     mittelfristigen Trend liegen;
   - beeinflusst keine notwendigen Exits.

### Generatorregeln

- maximal 48 vorab definierte Kandidaten pro Generation;
- maximal drei historische Prüfungen pro Stunde;
- Parameter immer innerhalb statisch validierter Grenzen;
- keine Code-Erzeugung, Imports oder dynamische Ausführung;
- neue Generation erst mit neuer Datenperiode oder neuer Strategiefamilie;
- Ergebnisse aller Kandidaten, auch der abgelehnten, dauerhaft speichern.

### Abnahme

- jede Familie hat Unit-Tests für BUY, HOLD, SELL und unzureichende Daten;
- Runtime, Backtest und Shadow liefern auf identischen Daten dieselbe Entscheidung;
- Kandidaten dürfen keine zukünftigen Kerzen, aktuelle Candle-Highs oder spätere
  Liquiditätsdaten verwenden;
- kein Kandidat kann seinen eigenen Freigabestatus setzen.

## P5 – Walk-forward-Auswertung und automatische Promotion

### Historische Stufen

1. Entwicklung: Strategieparameter werden ausschließlich hier verglichen.
2. Validierung: Auswahl der robusten Kandidaten ohne weitere Parameteränderung.
3. Embargo: mindestens Prognosehorizont zwischen angrenzenden Fenstern.
4. Unberührter Holdout: einmalige finale Prüfung pro Kandidatenversion.
5. Kosten-Stress: doppelte Gebühren und Slippage.
6. Benchmarks: Cash, Standard-Momentum, BTC und Equal-weight Buy-and-hold.

### Historische Mindestgates

- positive Netto-Expectancy in Entwicklung, Validierung und Holdout;
- positiver Stress-Return und positive Stress-Expectancy;
- Vorteil gegenüber Standard-Momentum im Holdout;
- Drawdown maximal 8 %;
- mindestens 30 geschlossene Validierungs- und Holdout-Trades zusammen;
- kein einzelner Monat oder fünf Trades erklären den Großteil des Gesamtgewinns;
- keine ungelösten Datenwarnungen.

### Shadow-Mindestgates für `LIVE_APPROVED_CANARY`

- mindestens sieben neue Forward-Tage;
- mindestens 30 geschlossene Shadow-Trades;
- positive Netto-Expectancy und Gesamtrendite;
- besser als paralleles Standard-Momentum;
- doppelter Kosten-Stress positiv;
- maximal 5 % Shadow-Drawdown;
- kein Risk-Halt, Versionswechsel oder Datenloch;
- nach 30 Tagen ohne Erfüllung automatische Ablehnung.

### Schutz vor Mehrfachtests

- Anzahl getesteter Kandidaten im Bericht ausweisen;
- Auswahl nur innerhalb einer vorab definierten Generation;
- Holdout nicht zur Erzeugung der nächsten Parameter verwenden;
- neue Generation benötigt ein neues, späteres Holdout-Fenster;
- Promotion speichert vollständige Gründe und Metriken unveränderlich.

### Abnahme

- absichtlich schwache, überoptimierte und kostenempfindliche Fixtures werden abgelehnt;
- nur ein Kandidat mit allen Gates erhält `LIVE_APPROVED_CANARY`;
- Promotion ist idempotent und transaktional;
- Änderung von Code, Parametern oder Risiko entzieht die Freigabe für neue Entries.

## P6 – Begrenzter Canary-Live-Rollout

### Zustände

```text
REJECTED
  ↑
HISTORICAL_TEST → SHADOW_ACTIVE → LIVE_APPROVED_CANARY → LIVE_APPROVED
                         ↓                   ↓
                      REJECTED          LIVE_SUSPENDED
```

### Canary-Regeln

- höchstens eine gleichzeitige Canary-Position;
- Orderbudget auf Exchange-Minimum plus Sicherheitsreserve begrenzen und zusätzlich
  durch ein konfigurierbares Canary-Maximum deckeln;
- höchstens zwei Positionen und 25 % Gesamtexposition während der Canary-Phase;
- bestehende normale Live-Risikolimits bleiben als strengere Obergrenzen aktiv;
- keine Skalierung vor mindestens zehn vollständig reconcilierten Live-Roundtrips;
- Live-Kosten, Fill-Rate und Slippage gegen Shadow-Annahme vergleichen.

### Automatische Rückstufung

Sofort `LIVE_SUSPENDED` für neue Entries bei:

- ungeklärter oder unbekannter Order;
- Konten- oder Holdings-Differenz;
- Überschreitung des Drawdown-Limits;
- tatsächlichen Kosten deutlich über der Forschungsannahme;
- Datenlücke, veralteter Watchlist oder Regime-Coverage unter 80 %;
- statistisch oder wirtschaftlich relevanter Abweichung zwischen Shadow und Live.

Exits und Reconciliation bleiben bei jeder Rückstufung aktiv.

### Abnahme

- Canary kann maximal den explizit konfigurierten Betrag einsetzen;
- Duplicate-Intent-Test verhindert eine zweite Übermittlung derselben Order;
- Timeout nach Submission erzeugt niemals eine automatische Zweitorder;
- Suspension stoppt Entries, aber niemals einen erforderlichen Exit;
- Skalierung und Rückstufung sind im Audit-Log sichtbar.

## P7 – Dashboard und Betrieb

### Dashboard

- aktive Strategie, Regime und Gründe für Cash/HOLD;
- Generation: geprüft / abgelehnt / Shadow / Live-approved;
- Kandidaten-Detail: Entwicklung, Validierung, Holdout, Stress und Benchmarks;
- Shadow-Tage, Trades, Rendite, Expectancy und Drawdown;
- Live-Canary-Budget und aktueller Freigabestatus;
- Watchlist-Alter, Coverage und letzter erfolgreicher Auswahlzeitpunkt;
- konfigurierte und verifizierte Gebühren;
- klare Warnung bei manuellen Trades auf demselben Kraken-Konto.

### Betrieb

- strukturierte Fehlercodes statt leerer Fehlermeldungen;
- Metriken für Zyklusdauer, Kraken-Rate-Limits, Nonce-Retries, Quote-Ausfälle und
  Reconciliation-Sperren;
- Alarm nur bei notwendiger Aktion oder Zustandsänderung;
- täglicher Kandidaten-/Shadow-Bericht ohne automatische Änderung von Risikolimits.

### Abnahme

- ein Nutzer kann ohne Datenbankzugriff erkennen, warum kein Trade erfolgt;
- jede Promotion und Suspension ist mit Zeitpunkt und Gründen sichtbar;
- Backend-Ausfall und Neustart verlieren keinen Shadow- oder Orderzustand.

## Release-Aufteilung

### Release A – Live-Betrieb reparieren

- P0, P1 und P2;
- Ziel: stabile Watchlist, konsistente Kosten, weiterhin keine ungeprüften Entries.

### Release B – Persistentes Shadow-System

- P3 und Dashboard-Grundstatus;
- Ziel: restart-sichere virtuelle Forward-Trades im Live-Modus.

### Release C – Strategiegeneration und Walk-forward

- P4 und historische Teile aus P5;
- Ziel: unabhängige Strategiefamilien statt zwölf Varianten derselben Idee.

### Release D – Automatische Promotion und Canary

- restliches P5 und P6;
- Ziel: automatisches, begrenztes Live-Onboarding mit Rückstufung.

### Release E – Betriebshärtung

- P7, Performance, Observability und Dokumentation;
- Ziel: verständlicher und wartbarer Dauerbetrieb.

## Verifikation pro Release

Jedes Release muss vor Deployment bestehen:

1. vollständige Backend-Test-Suite;
2. Frontend-Typecheck und Produktions-Build;
3. Migrationstest von leerer und bestehender Datenbank;
4. `git diff --check`;
5. deterministischer Backtest auf fixiertem Fixture;
6. Restart-/Idempotenztest für Shadow und Live-Order-Intents;
7. kein echter Kraken-Ordertest ohne separate ausdrückliche Freigabe;
8. dokumentierter Rollback ohne Verlust von Order- oder Shadow-Ledger.

## Definition of Done für das Gesamtsystem

- der Live-Bot besitzt eine nichtleere, frische und nachvollziehbare Watchlist;
- mindestens zwei unabhängige Strategiefamilien sind implementiert und getestet;
- Shadow-Ausführung ist persistent, deterministisch und restart-sicher;
- `LIVE_APPROVED` kann nur über vollständige historische und Forward-Gates entstehen;
- Canary begrenzt reales Risiko und kann automatisch suspendiert werden;
- manuelle Kraken-Aktivität wird erkannt und niemals still als Bot-PnL verbucht;
- Nutzer sieht für jeden Kandidaten und jeden verhinderten Trade den konkreten Grund;
- alle Tests, Builds und Migrationen sind grün;
- Profitabilität wird nicht behauptet, sondern ausschließlich aus gespeicherter
  Out-of-sample-, Shadow- und Live-Evidenz berichtet.
