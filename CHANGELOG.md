# Changelog

## 0.1.86 - 2026-07-14

- Kontextabhängiger OpenAI-Assistent für Sammlung, Decks, Sets und lokale Scryfall-Daten.
- Der Assistent kann alternativ und vollständig optional mit einem lokalen Ollama-Modell ohne API-Kosten betrieben werden; die Standardinstallation bleibt KI-frei.
- Optionale deutsche und englische Oberfläche sowie Export fehlender Setkarten.
- Überarbeitete Symbole, aufklappbare Filter und eindeutiges Zurücksetzen-Symbol.
- Plus- und Minus-Steuerung direkt an Deckkarten sowie ein klareres Sideboard-Symbol.
- Das Installationsskript erkennt vorhandene Installationen, sichert die Datenbank und aktualisiert ausschließlich Programmdateien; Sammlung, Decks, Login und API-Schlüssel bleiben erhalten.

## 0.1.85 - 2026-07-13

- Das Repository ist auf den Linux-Serverbetrieb fokussiert und enthaelt keine veralteten Windows-Batches oder historischen Update-Pakete mehr.
- Betriebswerkzeuge liegen gesammelt unter `scripts/`, Anleitungen unter `docs/` und systemd-Beispiele unter `deploy/systemd/`.
- Scanner-Benchmarkdaten und erzeugte Release-ZIPs sind keine Bestandteile des veroeffentlichten Quellpakets mehr.
- Installation, externer Zugriff, Sicherheit und Aktualisierung sind fuer einen frischen eigenen ManaVault-Server neu dokumentiert.
- Die CI verhindert, dass ZIP-Dateien, Windows-Batches oder Datenbanken versehentlich ins Repository gelangen.

## 0.1.84 - 2026-07-13

- Die vollstaendige ManaVault-Oberflaeche kann ueber einen separaten Dienst mit Benutzername und Passwort extern genutzt werden.
- Der geschuetzte Dienst lauscht ausschliesslich auf `127.0.0.1:8002` und ist fuer einen eigenen Tailscale Funnel auf Port 10000 vorgesehen.
- Passwoerter werden mit Scrypt und zufaelligem Salt gehasht; das Klartextpasswort wird nicht gespeichert.
- Anmeldungen verwenden signierte, zeitlich begrenzte Secure-/HttpOnly-/SameSite-Cookies und begrenzen wiederholte Fehlversuche.
- Die oeffentliche schreibgeschuetzte Deckansicht auf Port 8443 bleibt ohne Login getrennt erhalten.
- Das Konfigurationsskript fuer oeffentliche QR-Adressen akzeptiert nun auch HTTPS-Adressen mit Portnummer.

## 0.1.83 - 2026-07-13

- Decks koennen mehrere benannte Varianten besitzen; nur die aktive Variante belegt Karten aus der Sammlung.
- Der Deckbuilder bietet Speichern, Verwerfen und `Als neue Variante` und bewahrt beim ersten Aufteilen den vorherigen Stand automatisch als `Original`.
- Varianten lassen sich auch mit fehlenden Karten aktivieren; nicht verfuegbare Karten bleiben sichtbar als fehlend markiert.
- Hauptdeck und Sideboard werden getrennt gespeichert, angezeigt, importiert und exportiert.
- Karten koennen im Deckbuilder zwischen Hauptdeck und Sideboard verschoben werden.
- Datenbackups und die schreibgeschuetzte Deckansicht enthalten Varianten- beziehungsweise Sideboard-Daten.

## 0.1.82 - 2026-07-12

- Der doppelte Kartenzaehler neben der Ueberschrift `Deckkarten` wurde im Deckbuilder und in der QR-Deckansicht entfernt.
- Die Kartenanzahl steht weiterhin einmal eindeutig im oberen Deckstatus.

## 0.1.81 - 2026-07-12

- QR-Deckseiten koennen ueber einen getrennten, ausschliesslich lesenden Dienst sicher extern freigegeben werden.
- Jedes freigegebene Deck erhaelt einen langen zufaelligen Link statt einer erratbaren fortlaufenden Decknummer.
- Der oeffentliche Dienst lauscht nur auf `127.0.0.1:8001` und stellt weder Sammlung noch Backups, Scanner oder Schreibfunktionen bereit.
- Cloudflare Tunnel kann ohne Portfreigabe auf diesen Nur-Lese-Dienst zeigen; die vollstaendige Verwaltung bleibt davon getrennt.
- Ein Konfigurationsskript speichert die dauerhafte externe Adresse, damit neue QR-Codes automatisch darauf verweisen.
- Freigabelinks koennen serverseitig erneuert oder widerrufen werden.

## 0.1.80 - 2026-07-12

- Offensichtliche Erklaertexte unter Sammlung, Stats, Decks, Planung, Historie und Daten wurden entfernt.
- Sammlungs-, Deckbuilder-, Deck- und Historienzaehler sind auf kurze Formen wie `120 Karten`, `1 Deck` und `0 Ereignisse` reduziert.
- Hinweise bei automatisch benoetigten Tokens und Zubehoer wurden auf die direkt nutzbaren Informationen gekuerzt.
- Leere Zustaende und Planungstexte sind kuerzer formuliert.
- Backup-, Scanner- und QR-Hinweise bleiben erhalten, wenn sie fuer Bedienung oder Datensicherheit relevant sind.

## 0.1.79 - 2026-07-12

- Automatisch benoetigte Tokens und Zubehoer stehen im Deckbuilder nun unterhalb der eigentlichen Deckkarten und manuell hinzugefuegten Tokens.
- Der obere Statusbereich bleibt dadurch kompakt und auf Kartenbestand, Proxys, Fehlbestand und Konflikte konzentriert.
- Auf der schreibgeschuetzten QR-Deckseite erscheinen Deckkarten ebenfalls vor Token-Hinweisen und Zubehoer.

## 0.1.78 - 2026-07-12

- Die fuenf Aktionsbuttons einer Deckkachel werden auf schmalen Kacheln nicht mehr in eine einzige Reihe gequetscht.
- Deckaktionen erscheinen nun in einem luftigen Raster mit maximal drei Buttons pro Reihe.
- Alle Deckaktionsbuttons besitzen eine gut bedienbare Mindestgroesse und deutlichere Abstaende.

## 0.1.77 - 2026-07-12

- Hinweise auf automatisch benoetigte Tokens erscheinen nicht mehr in der allgemeinen Deckuebersicht.
- Der Token-Bedarf bleibt ausschliesslich innerhalb des geoeffneten Decks im Deckbuilder und auf der QR-Deckseite sichtbar.
- Offene Token-Empfehlungen werden als dezenter Hinweis statt als rote Warnung dargestellt.
- Die Formulierungen lauten neutral `offen` und `noch benoetigt` statt `fehlt`.

## 0.1.76 - 2026-07-12

- Deckbuilder und QR-Deckansicht besitzen nun einen automatisch erzeugten Bereich `Zubehoer`.
- ManaVault erkennt Faehigkeitsmarker wie Flugfaehigkeit, Todesberuehrung, Doppelschlag, Eile, Lebensverknuepfung oder Wachsamkeit.
- Weitere Marker wie `+1/+1`, Gift, Energie, Oel, Zeit, Loyalitaet, Verteidigung und Sagenmarker werden aus Regeltext und Kartentyp ermittelt.
- Weitere Spielhilfen wie W6/W20, Muenze, Monarch-, Initiative-, Tag/Nacht-, Dungeon-, Ring-, Attraction- und Sticker-Hilfen werden angezeigt.
- Jeder Hinweis nennt die Deckkarten, die das jeweilige Zubehoer benoetigen.
- Die Erkennung unterscheidet echte Marker von `counter` als englischem Spielverb und erzeugt dadurch keine falschen Marker fuer Gegenzauber.

## 0.1.75 - 2026-07-12

- ManaVault uebernimmt nun die direkten Scryfall-Beziehungen zwischen Deckkarten und den von ihnen erzeugten Token-Drucken.
- Eine Token-Beziehung gilt automatisch fuer alle Drucke derselben Oracle-Karte, auch wenn Scryfall sie nur an einem bestimmten Druck hinterlegt hat.
- Die Deckuebersicht zeigt pro Deck, wie viele benoetigte Token-Arten noch fehlen.
- Der Deckbuilder listet automatisch benoetigte Tokens mit Bild, Druckkennung, erzeugenden Karten und Original-/Proxy-/Fehlstatus auf.
- Fehlende empfohlene Tokens koennen direkt ueber `Zum Deck` hinzugefuegt werden.
- Die schreibgeschuetzte QR-Deckansicht zeigt die benoetigten Tokens ebenfalls an.
- Ein erneuter `--tokens-only`-Import baut die Token-Beziehungen auf, ohne den grossen Karten-Bulk erneut zu laden.

## 0.1.74 - 2026-07-12

- Token-Druckkennungen wie `T 0007 BLB EN` und `T0007 BLB EN` werden in Sammlung, Deckbuilder und Scanner direkt erkannt.
- Das fuehrende `T` grenzt einen Token eindeutig von einer normalen Karte mit derselben Set- und Sammlernummer ab.
- Normale Druckkennungen mit `C`, `U`, `R`, `M` oder `L` werden entsprechend von Tokens getrennt.
- Ohne Kennbuchstaben werden weiterhin alle passenden normalen Karten und Tokens angezeigt.
- Token-Kacheln zeigen ihre vollstaendige Druckkennung im Format `T 0007 BLB EN` an.

## 0.1.73 - 2026-07-12

- Das Deckkartenraster beruecksichtigt nun die Mindestbreite der Mengen-, Minus-, Deckblatt- und Loeschbuttons.
- Deckbilder und Bedienelemente ragen nicht mehr in benachbarte Karten hinein.
- Die rechte Deckbuilder-Ansicht verwendet wieder ein stabiles responsives Raster ohne horizontalen Seitenueberlauf.

## 0.1.72 - 2026-07-12

- Jedes Deck besitzt nun einen QR-Code-Button in der Deckuebersicht und im Deckbuilder.
- Der QR-Code verwendet die aktuell geoeffnete ManaVault-Adresse und kann dadurch gezielt auf die lokale IP oder die Tailscale-Adresse zeigen.
- QR-Codes lassen sich als druckbares Decketikett ausgeben oder als skalierbare SVG-Datei speichern.
- Neue schreibgeschuetzte Deckansichten unter `/deck/<id>` zeigen Format, Farben, Karten, Tokens, Deckwert sowie Original-, Proxy- und Fehlbestand.
- Die oeffentliche Deckansicht ist fuer Handybildschirme optimiert und enthaelt keine Bearbeitungsfunktionen.

## 0.1.71 - 2026-07-12

- Der Scryfall-Import laedt jetzt zusaetzlich alle eigenstaendigen Token-, doppelseitigen Token- und Emblem-Drucke samt Bildern und Sprachvarianten.
- Der neue schnelle Modus `--tokens-only` ergaenzt fehlende Token-Daten, ohne den mehrere Gigabyte grossen Karten-Bulk erneut zu laden.
- Ein normaler vollstaendiger Scryfall-Import aktualisiert Karten und Token-Drucke kuenftig gemeinsam.

## 0.1.70 - 2026-07-12

- Tokens werden anhand von Scryfall-Layout und offizieller Typzeile dauerhaft von normalen Karten unterschieden.
- Im Deckbuilder erscheinen Deckkarten und Tokens in getrennten Bereichen; Tokens sind bereits in der linken Suche deutlich markiert.
- Tokens koennen wie normale Karten als Original oder Proxy angelegt, einem Deck zugewiesen und einzeln reduziert werden.
- Token-Mengen zaehlen nicht mehr zur Deckkartenzahl, zum Deckwert, zur Einkaufsliste oder zur allgemeinen Planung.
- Der Deckstatus zeigt Originale, Proxies und fehlende Exemplare fuer Tokens separat an.
- Decklisten-Exporte fuehren Tokens in einem eigenen Abschnitt auf.

## 0.1.69 - 2026-07-12

- Jede Deckkarte besitzt nun einen Minus-Button, der genau ein Exemplar aus der Deckliste entfernt.
- Beim Reduzieren einer vollstaendig zugewiesenen Kartenposition wird genau eine physische Kopie wieder freigegeben; Proxies werden dabei zuerst freigegeben.
- Der Papierkorb entfernt weiterhin die komplette Kartenposition auf einmal.

## 0.1.68 - 2026-07-12

- Deckstatus und Kartenanzahlen stehen im rechten Deckbuilder-Bereich nun oberhalb der Deckkarten.
- Der rechte Deckbereich bleibt auf grossen Bildschirmen sichtbar und scrollt unabhaengig von einer langen Kartenliste auf der linken Seite.

## 0.1.67 - 2026-07-12

- Schnelles Hinzufuegen im Deckbuilder zeigt auf der Kartenkachel nun ebenfalls `+1`, `+2`, `+3` usw. an.
- Der Zaehler funktioniert fuer vorhandene Karten, neu erstellte Originale und nach der Proxy-/Planungsentscheidung.

## 0.1.66 - 2026-07-12

- Die reine Sammlungsansicht ist nicht mehr auf die ersten 500 Kartendrucke begrenzt.
- `Mehr Karten laden` wird nun auch ohne aktivierte Scryfall-Ansicht angeboten und laedt jeweils die naechste Seite der eigenen Sammlung.

## 0.1.65 - 2026-07-12

- Kartenkacheln bleiben auch bei Kartennamen mit einem einzelnen extrem langen Wort innerhalb ihrer Spalte.
- Lange Kartennamen werden bei Bedarf sicher umgebrochen, ohne benachbarte Karten zu ueberdecken.

## 0.1.64 - 2026-07-12

- Kennungen mit Gesamtzahl wie `193/274 C M21 DE` priorisieren wieder korrekt die `193`; der Set-Code `M21` wird nicht mehr als Seltenheit `M` plus Nummer `21` missverstanden.
- Bleiben nach einer sicheren Kennung mehrere echte Druckvarianten uebrig, zeigt der Scanner alle Varianten sichtbar zur Auswahl an.
- Eine bereits ausgewaehlte Variante bleibt stehen, wenn sie weiterhin zu den erkannten Moeglichkeiten gehoert.

## 0.1.63 - 2026-07-12

- Drei echte Fehlscan-Reports wurden in den dauerhaften Regressionstest aufgenommen; alle bisherigen 11 Testkarten werden korrekt erkannt.
- Zusammengeklebte Set- und Sprachcodes wie `M21DE` werden als `M21` und `DE` getrennt ausgewertet.
- Die Konturerkennung bewertet jetzt auch die Dunkelheit des Aussenrandes und unterscheidet dadurch schwarzen Kartenrand, innere Druckflaeche, weisse Huelle und Ablage.
- Name plus eindeutiger Set-Code darf eine beschaedigte Sammlernummer absichern, wenn innerhalb dieses Sets nur ein passender Druck existiert.
- Dadurch werden unter anderem `ECL #164 DE` und `FDN #99 DE` trotz abgeschnittener beziehungsweise als `66000` gelesener Kennungsziffern korrekt bestimmt.
- Durchschnittliche Erkennungszeit ueber alle 11 Testbilder liegt weiterhin bei rund 1,41 Sekunden.

## 0.1.62 - 2026-07-12

- Neuer Button `Fehlscan speichern` sichert das zuletzt gescannte Kamerabild samt OCR-Ausgabe, Kandidaten, Konturwerten und ManaVault-Version.
- Der korrekte Kartenname oder die Druckkennung kann beim Melden optional als Referenz eingetragen werden.
- Reports bleiben lokal unter `data/scanner-reports` und enthalten jeweils eine JPG- sowie eine JSON-Datei.
- Alle gespeicherten Scanner-Reports koennen direkt als ZIP heruntergeladen und zur weiteren Optimierung bereitgestellt werden.

## 0.1.61 - 2026-07-12

- Nach einer eindeutigen Erkennung werden keine teuren Server-Scans derselben unveraenderten Karte mehr gestartet.
- Der Browser ueberwacht den Kartenbereich lokal alle 150 Millisekunden und startet bei einem stabilen Bildwechsel sofort eine neue OCR.
- Ein einzelner Kontrollscan alle 5 Sekunden verhindert, dass ein Kartenwechsel wegen ungewoehnlicher Lichtverhaeltnisse uebersehen wird.
- Solange noch keine Karte eindeutig erkannt wurde, laeuft weiterhin Scan direkt nach Scan.
- Dadurch ist beim Kartenwechsel normalerweise keine alte OCR mehr aktiv, vor der sich das neue Bild einreihen muss.

## 0.1.60 - 2026-07-12

- Maximales Serientempo: Der naechste automatische Scan startet 60 Millisekunden nach Abschluss des vorherigen Scans.
- Es laufen weiterhin niemals mehrere OCR-Anfragen parallel; die Serverleistung bestimmt automatisch den effektiven Takt.
- Ein manueller Scan waehrend einer laufenden Erkennung wird vorgemerkt und unmittelbar als naechster Durchlauf ausgefuehrt.
- Der bisherige feste 3-Sekunden-Takt und die zusaetzliche Kartenwechsel-Abfrage entfallen.

## 0.1.59 - 2026-07-12

- Kartenname und gesamte untere Kennungszeile werden in einem gemeinsamen RapidOCR-Durchlauf erkannt statt nacheinander.
- Der schnelle gemeinsame OCR-Pfad erkennt alle acht lokalen Original-Testkarten inklusive Retro-Druck.
- Ein lokaler Kartenwechsel kann den Scan bereits nach kurzer Bildruhe ausloesen; der feste 3-Sekunden-Scan bleibt als Sicherheitsnetz bestehen.
- Wiederholte oder zeitlich ueberlappende Scan-Anfragen werden weiterhin unterdrueckt.

## 0.1.58 - 2026-07-12

- Scanner prueft das Kamerabild fest alle 3 Sekunden und bleibt auch bei angezeigter Mengenwahl aktiv.
- Nur ein eindeutiger neuer Druck ersetzt die aktuell angezeigte Karte und setzt deren Menge auf 1.
- Fehlende, unsichere oder mehrdeutige Erkennungen veraendern die bisherige Auswahl nicht.
- Technische Such-, Kontur- und Wiederholungszustaende werden dem Bediener nicht mehr angezeigt.
- Der manuelle Button startet weiterhin sofort einen zusaetzlichen Scan.
- Nur waehrend des eigentlichen Speicherns wird die Scan-Schleife kurz pausiert.

## 0.1.57 - 2026-07-12

- Dead-End bei `Treffer bestaetigen` behoben: Der Scan-Button bleibt anklickbar und fuehrt jederzeit zur Mengenwahl zurueck.
- Ist der Scanner pausiert, aber keine Auswahl mehr vorhanden, setzt der Button den Serienmodus ohne Neuladen zurueck.
- Scrollen zur Mengen- oder Druckauswahl ist gegen Browserfehler abgesichert.
- Nach einem fehlgeschlagenen Speichervorgang bleiben Mengenwahl und Wiederholungsbutton bedienbar.

## 0.1.56 - 2026-07-12

- Automatischer Serienmodus scannt jetzt fest alle 5 Sekunden, solange kein Mengen- oder Auswahlfenster offen ist.
- Ein bereits bestaetigter identischer Druck wird automatisch uebersprungen, statt dasselbe Mengenfenster erneut zu oeffnen.
- Der sichtbare Button startet jederzeit sofort einen Scan und darf bewusst auch denselben Druck erneut erfassen.
- Die vorherige empfindliche Bildwechsel-Schwelle ist fuer das automatische Ausloesen nicht mehr erforderlich.

## 0.1.55 - 2026-07-12

- Der manuelle Button `Karte jetzt scannen` bleibt waehrend des gesamten Kamerabetriebs sichtbar.
- Bei einem automatischen Treffer wird der Button waehrend der Mengenwahl nur deaktiviert und zeigt `Treffer bestaetigen`.
- Nach dem Hinzufuegen oder Verwerfen ist der Scan-Button sofort wieder aktiv.

## 0.1.54 - 2026-07-12

- Neuer schneller Serienmodus: Kamera bleibt offen und erkennt automatisch, wenn eine andere Karte eingelegt wurde.
- Eine lokale Bildsignatur reagiert auf den Kartenwechsel, ignoriert aber kleine Helligkeits- und Autofokusaenderungen.
- OCR startet automatisch, sobald die neue Karte kurz ruhig liegt; `Karte jetzt scannen` bleibt als manueller Sofortstart erhalten.
- Eindeutige Treffer springen ohne zusaetzlichen Auswahlschritt direkt zur Mengenwahl mit Minus, Plus und Bestaetigung.
- Nach dem Hinzufuegen ist derselbe Kamerastream sofort fuer die naechste Karte bereit.
- Die Sammlung wird nach dem Speichern im Hintergrund aktualisiert, waehrend der Scanner bereits auf die naechste Karte wartet.
- Dieselbe bereits bestaetigte Karte wird nicht erneut gescannt; erst eine sichtbar andere Karte startet den naechsten Durchlauf.
- Mehrdeutige Drucke zeigen weiterhin eine kurze Auswahl, statt einen Druck zu erraten.

## 0.1.53 - 2026-07-12

- Kritischen Linux-Fehler behoben: OpenCV war nicht als eigene Server-Abhaengigkeit abgesichert, wodurch die Kartenkonturerkennung auf dem Server nicht laufen konnte.
- Linux-Scanner-Installation installiert OpenCV sowie dessen benoetigte Linux-Laufzeitbibliotheken und prueft den Import anschliessend ausdruecklich.
- Ein fehlendes OpenCV wird in der Oberflaeche als konkrete Server-Fehlermeldung angezeigt und nicht mehr faelschlich als nicht gefundene Kartenkontur.

## 0.1.52 - 2026-07-12

- Live-Scanner zeigt auf unterstuetzten Handykameras eine Zoom-Steuerung mit Regler sowie Plus-/Minus-Tasten.
- Verfuegbarer Zoombereich und Schrittweite werden direkt von der Kamera uebernommen.
- Auf Geraeten ohne steuerbaren Kamera-Zoom bleibt die Bedienung automatisch ausgeblendet.
- Bei mehreren Handyobjektiven kann die Kamera direkt im Scanner ausgewaehlt werden; ManaVault merkt sich die Auswahl.
- Ist ein zuvor gewaehltes Objektiv nicht mehr vorhanden, faellt der Scanner automatisch auf die rueckseitige Standardkamera zurueck.
- Zusaetzliche Hell-Dunkel-Segmentierung erkennt schwarze Kartenraender auf weissem Hintergrund auch bei weicher oder bewegungsunscharfer Kante.
- Deutlich kleinere Karten im Kamerabild werden als Konturkandidaten zugelassen; der Zoom ist keine Voraussetzung fuer die Erkennung.

## 0.1.51 - 2026-07-12

- Live-Scanner anhand acht unveraenderter Handyfotos als reproduzierbaren Testsatz optimiert; alle acht Drucke werden mit Set, Sammlernummer und Sprache korrekt erkannt.
- Moderne, alte und Retro-Kennungsformate werden getrennt ausgewertet; Staerke/Widerstand wie `2/1` wird nicht mehr mit einer rechts stehenden Sammlernummer verwechselt.
- Kartenname und Sammlernummer koennen alte Drucke auch dann eindeutig bestimmen, wenn auf der Karte selbst kein Set-Code steht.
- Seltenheitsbuchstabe und Sammlernummer werden gegen zufaellige Zahlen im Regeltext und Copyright-Jahre priorisiert.
- Sprachcodes werden nur noch an echten Kennungspositionen erkannt; Woerter wie `deinem` erzeugen kein falsches `DE` mehr.
- Fehlende lokalisierte Scryfall-Zeilen blockieren einen exakten Set-/Nummer-/Sprach-Treffer nicht mehr; die erkannte Sprache wird beim Hinzufuegen gespeichert.
- Teure Vollbild-OCR-Wiederholungen nach bereits gefundener Kartenkontur entfallen.

## 0.1.50 - 2026-07-11

- Direkt aufeinanderfolgende identische Historienaktionen werden zusammengefasst.
- Mehrfaches Hinzufuegen erscheint beispielsweise als ein Eintrag `5x Hinzugefuegt`.
- Gruppierung beruecksichtigt Karte, Aktion, Ziel sowie Original oder Proxy.

## 0.1.49 - 2026-07-11

- Schnelles mehrfaches Hinzufuegen zeigt pro Karte einen temporaeren Zaehler wie `+1`, `+2`, `+3`.
- Der Zaehler misst nur die aktuelle Klickserie und ist unabhaengig vom vorhandenen Bestand.
- Nach kurzer Pause blendet der Zaehler automatisch weich aus.

## 0.1.48 - 2026-07-11

- Manuelle Aktualisieren-Buttons bei Planung und Historie entfernt.
- Beide Seiten laden ihre Daten bei jedem Oeffnen automatisch neu.

## 0.1.47 - 2026-07-11

- Neue Historie fuer alle Aenderungen an Kartenkopien.
- Hinzufuegen, Loeschen, Verschieben sowie Deckzuweisung und Deckentnahme werden mit Zeitpunkt protokolliert.
- Historie kann nach Kartenname und Aktion gefiltert werden.
- ManaVault-Datenbackups enthalten nun auch die Historie; alte Backups bleiben importierbar.

## 0.1.46 - 2026-07-11

- Geteilte Manasymbole wie Schwarz/Gruen werden auf Kartenkacheln wieder korrekt angezeigt.
- Die Korrektur gilt ebenfalls fuer Hybrid- und Phyrexian-Manakosten.

## 0.1.45 - 2026-07-11

- Kartenkacheln reservieren den Platz fuer Anzahl und Preis jetzt immer.
- Beim ersten Hinzufuegen einer Karte verschieben sich Inhalt und Aktionsbuttons nicht mehr.

## 0.1.44 - 2026-07-11

- Kartensuche akzeptiert jetzt gedruckte Kennungen wie `C 0088 DSK DE`.
- Kennungen koennen auch ohne Seltenheitscode oder Sprache eingegeben werden, beispielsweise `DSK 88`.
- Scanner-Suchfeld weist sichtbar auf die Suche nach Kartenname oder Druckkennung hin.

## 0.1.43 - 2026-07-11

- Versionsnummer wird dezent unten rechts in der Oberflaeche angezeigt.
- Die Sammlung startet ohne aktives Ziel-Deck.
- Ohne ausgewaehltes Ziel-Deck wird die Aktion "Ins Deck" in der Sammlung ausgeblendet.

## 0.1.42 - 2026-07-11

- Konturerkennung akzeptiert neben geschlossenen Vierecken nun auch gedrehte Mindest-Rechtecke aus unvollstaendigen Kartenkanten.
- Scanner bleibt nicht mehr endlos bei `Kartenkontur suchen` stehen.
- Wenn keine brauchbare Kontur gefunden wird, analysiert RapidOCR das gesamte Kamerabild ohne feste Positionsvorgabe.
- Vollbild-Fallback verbindet gezielt eine echte Set-Code-Zeile mit der zugehoerigen Kennungszeile.
- Staerke/Widerstand wie `1/2` wird dabei nicht als Sammlernummer behandelt.
- Vollbild-Treffer werden zusaetzlich ueber den Kartennamen und den lokalen Scryfall-Katalog bestaetigt.
- Hochsichere rahmenlose Treffer koennen nach einem Durchlauf uebernommen werden.
- Auf weissem Hintergrund mit mehreren Verschiebungen und Perspektiven erfolgreich getestet.

## 0.1.41 - 2026-07-11

- Scanner analysiert jetzt das vollstaendige Kamerabild statt fester Prozent-Ausschnitte.
- OpenCV erkennt automatisch ein konvexes Kartenviereck im MTG-Seitenverhaeltnis.
- Erkannte Karten werden gedreht, perspektivisch entzerrt und auf ein einheitliches Kartenformat gebracht.
- Name und Bottom-Strip werden erst aus der normalisierten Karte ausgeschnitten und mit RapidOCR gelesen.
- Mehrere Kantenstaerken und Konturvarianten machen die Erkennung auf ruhigem, insbesondere weissem Hintergrund robust.
- Ohne sicher erkannte Kartenkontur wird kein Druck geraten.
- Copyright-Zahlen werden bei der Sammlernummer prioritaetskorrekt behandelt.
- Fehlende lokalisierte Scryfall-Namen koennen eine eindeutige fremdsprachige Druckkennung nicht mehr faelschlich verwerfen.
- Kamerarahmen dient nur noch als grobe Orientierung; pixelgenaue Positionierung ist nicht mehr erforderlich.

## 0.1.40 - 2026-07-11

- Kamerastream bleibt nach Erkennung und Hinzufuegen geoeffnet; nur die OCR pausiert und wird fortgesetzt.
- Verzogenes beziehungsweise langgezogenes Kamerafenster beim Scannen der naechsten Karte behoben.
- Live-Modus verwendet nur noch einen schnellen RapidOCR-Bottom-Strip-Durchlauf statt der langsamen Tesseract-Kaskade.
- Kartenname wird mit RapidOCR als unabhaengige Kreuzpruefung gelesen; falsche, aber formal gueltige Set-/Nummer-Treffer werden verworfen.
- Hochsichere, eindeutige und namensbestaetigte Treffer werden nach einem Frame angenommen.
- Unsichere oder mehrdeutige Treffer benoetigen weiterhin mehrere Bestaetigungen beziehungsweise eine Auswahl.
- Kamera fordert hoehere Aufloesung an; OCR-Ausschnitte werden vor der Uebertragung hochwertig vergroessert.
- Spracherkennung verarbeitet auch Schreibweisen wie `MH1·EN` und mit dem Kuenstlernamen verbundenes `ENSIMON`.

## 0.1.39 - 2026-07-11

- Primaere Scanner-OCR von Tesseract auf RapidOCR mit mobilem PP-OCRv6-Modell umgestellt.
- Neue Engine ist fuer Kamerabilder und Szenentext ausgelegt und verarbeitet die komplette Bottom-Strip-Kennung inklusive Kuenstlername robust.
- RapidOCR-Ergebnis wird strikt gegen Set, Sammlernummer und Sprache im lokalen Scryfall-Katalog validiert.
- Tesseract bleibt nur als technischer Fallback erhalten.
- Reale Kennungszeile aus dem gemeldeten Screenshot wurde erfolgreich als `025/254 C MH1 EN` und damit `MH1 #25` erkannt.

## 0.1.38 - 2026-07-11

- Kennungserkennung fuer verschiedene MTG-Kartenrahmen grundlegend ueberarbeitet.
- Moderne zweizeilige und aeltere einzeilige Kennungsformate werden parallel aus getrennten Bildausschnitten gelesen.
- Formate wie `025/254 C MH1 EN` verwenden nur die Zahl vor dem Schraegstrich als Sammlernummer.
- Breiter Altformat-Ausschnitt erfasst Set-Kuerzel und Sprache auch dann, wenn sie weiter rechts stehen.
- OCR nutzt vergroesserte Bilder, mehrere Schwellwerte, passende Einzeilen-/Blockmodi, weisse Raender und deaktivierte Woerterbuecher fuer Codes.
- Mehrere OCR-Varianten stimmen serverseitig ueber den wahrscheinlichsten Druck ab.
- Live-Modus bestaetigt weiterhin erst nach wiederholten Treffern ueber mehrere Kameraframes.

## 0.1.37 - 2026-07-11

- Live-Scanner kann die Taschenlampe kompatibler Smartphones ein- und ausschalten.
- Licht-Button wird nur angezeigt, wenn Kamera und Browser die Funktion bereitstellen.
- Beim Schliessen oder Pausieren des Scanners wird das Licht automatisch ausgeschaltet.

## 0.1.36 - 2026-07-11

- Verwechslungen von `A` und `E` in kleinen Set-Kuerzeln werden als mehrdeutig behandelt.
- Wenn beide Varianten echte Set-Codes sind, zeigt der Scanner beide Drucke zur Auswahl statt einen falschen Druck als eindeutig zu melden.
- Betrifft insbesondere die sehr aehnlichen Avatar-Codes `TLA` und `TLE`.

## 0.1.35 - 2026-07-11

- Druckkennungsfenster weiter verengt und nach unten auf die tatsaechlichen Kennungszeilen verschoben.
- Kuenstlername liegt nun vollstaendig ausserhalb des OCR-Bereichs.
- Namensfenster auf die eigentliche Titelleiste verkleinert und Abstand der beiden Markierungen korrigiert.

## 0.1.34 - 2026-07-11

- Sprachvarianten sind in der Scanner-Auswahl eindeutig beschriftet.
- Englischer Druck wird beispielsweise als `SOS #12`, deutscher Druck als `SOS #12 DE` angezeigt.
- Sprachkennzeichnung erscheint ebenfalls nach der Auswahl und in der Erkennungsmeldung.

## 0.1.33 - 2026-07-11

- Druckkennungs-Ausschnitt endet nun vor dem Kuenstlernamen.
- OCR erhaelt nur noch Seltenheit, Sammlernummer, Set-Kuerzel und Sprache.

## 0.1.32 - 2026-07-11

- OCR-Ausschnitt auf die zwei Kennungszeilen unten links verengt; Regeltext und Kuenstlername werden nicht mehr mitgelesen.
- Live-Erkennung verwendet eine Mehrheitsentscheidung aus den letzten Frames statt direkt auf wechselnde Einzelwerte zu reagieren.
- Unsichere Namens-Fallbacks koennen im Live-Modus keinen falschen Treffer mehr ausloesen.
- Statusanzeige bleibt ruhig, bis eine belastbare Druckkennung vorliegt.

## 0.1.31 - 2026-07-11

- Druckkennungs-OCR akzeptiert nun typische Lesefehler wie `C0012` statt `C 0012` und `S0S` statt `SOS`.
- Kartenecke wird mit mehreren Kontrast- und Segmentierungsvarianten ausgewertet.
- Unsichere Namenszuordnungen werden nicht mehr als scheinbar passende Karten angezeigt.
- Erkannter Rohtext der Kartenecke wird im Scannerstatus sichtbar gemacht.

## 0.1.30 - 2026-07-11

- Set-Kuerzel, Sammlernummer und Sprache unten links sind jetzt die primaere Live-Erkennung.
- Damit wird direkt der konkrete Kartendruck statt nur eines moeglicherweise mehrdeutigen Namens gefunden.
- Die Namenszeile bleibt als Fallback fuer alte oder schlecht lesbare Karten erhalten.
- Kartenrahmen und Bildausschnitt verwenden nun dieselbe Geometrie bei Hoch- und Querformat-Sensoren.
- Der tatsaechlich ausgewertete Ausschnitt wird unter dem Livebild zur Kontrolle angezeigt.

## 0.1.29 - 2026-07-11

- Echter Live-Kameramodus fuer den mobilen Kartenscanner hinzugefuegt.
- Der markierte Namensbereich wird regelmaessig an die lokale Server-OCR gesendet.
- Deutsche und englische Kartennamen werden unabhaengig von der Browser-Texterkennung erkannt.
- Nach zwei stabilen Treffern pausiert die Kamera automatisch und zeigt passende Drucke.
- Nach dem Hinzufuegen startet die Kamera direkt fuer die naechste Karte neu.
- Fotoaufnahme und manuelle Namenssuche bleiben als Fallback erhalten.

## 0.1.28 - 2026-07-11

- Mobiler Kamera-Dialog zum schnellen Erfassen von Karten hinzugefuegt.
- Automatisch gelesener Kartenname kann gesucht und der genaue Druck ausgewaehlt werden.
- Mengenwahl mit Plus/Minus und gemeinsamer Bestaetigung fuer bis zu 100 Copies.
- Manuelle Namenssuche dient als Fallback, wenn der Browser keine Texterkennung anbietet.

## 0.1.27 - 2026-07-11

- Set-Uebersicht zeigt nur noch Sets, aus denen mindestens eine Original- oder Proxy-Copy vorhanden ist.

## 0.1.26 - 2026-07-11

- Stats um Set-Uebersicht erweitert: Fortschritt pro Set, Originale, Proxies und fehlende Drucke.
- Fehlende Set-Beispiele koennen direkt in der Stats-Seite aufgeklappt werden.
- Digitale Arena-/Alchemy-Varianten mit A-Sammlernummer werden in der Set-Vollstaendigkeit ausgeblendet.

## 0.1.25 - 2026-07-11

- Aktive Deckblatt-Karte zeigt im Deckbuilder jetzt einen gefuellten Stern.
- Deckblatt-Button wird bei aktiver Deckblatt-Karte farblich hervorgehoben.

## 0.1.24 - 2026-07-11

- Deckbuilder-Kartenaktionen auf ein 2x2-Layout umgestellt, damit vier Buttons nicht zusammengedrueckt werden.
- Kombi-Aktion Original + ins Deck optisch lesbarer gemacht.

## 0.1.23 - 2026-07-11

- Deckbuilder-Karten erhalten einen Button fuer Original hinzufuegen und direkt ins aktuelle Deck legen.
- Neue Original-Copy wird dabei sofort dem gerade bearbeiteten Deck zugewiesen.
- Deckliste und Zaehler werden danach direkt aktualisiert.

## 0.1.22 - 2026-07-11

- Deckbuilder-Filterleiste auf flexibles, sauber umbrechendes Layout umgestellt.
- Sprachfilter auch im Deckbuilder ergaenzt.
- Filterleisten fuer Sammlung, Decks und Deckbuilder optisch vereinheitlicht.

## 0.1.21 - 2026-07-11

- Deck-Uebersicht als Kachel/Galerie-Ansicht mit Deckblatt-Bild umgesetzt.
- Im Deckbuilder kann eine Karte als Deckblatt gesetzt werden.
- Deckblatt-Karte wird im Deckbuilder markiert.
- Wird die Deckblatt-Karte aus dem Deck entfernt, wird das Deckblatt automatisch geleert.

## 0.1.20 - 2026-07-11

- Deck-Uebersicht mit Suche, Formatfilter, Typfilter, Farbfilter und Sortierung ergaenzt.
- Deck-Karten zeigen Farben, wichtigste Typen und Decklistenwert in der Uebersicht.
- Sammlungsfilter um Sprachfilter erweitert: Deutsch + Englisch, nur Deutsch, nur Englisch oder alle Sprachen.
- Sprachfilter kann auch bei globaler Scryfall-Suche genutzt werden.

## 0.1.19 - 2026-07-11

- Deck-Werte vereinfacht: Deckliste, Originale und fehlender Wert; Proxy-Wert wird nicht mehr angezeigt.
- Fehlender Deckwert wird rot hervorgehoben.
- Preis-Fallback fuer deutsche Karten verbessert: gleicher englischer Druck ueber Set und Sammlernummer wird bevorzugt.
- Datenbank-Indizes fuer schnellere Preis-Fallbacks ergaenzt.

## 0.1.18 - 2026-07-11

- Bugfix: Beim Entfernen einer Karte aus einem Deck werden zugewiesene Kopien wieder freigegeben.
- Decklisten-Ersetzen gibt alte Deck-Kopien ebenfalls wieder fuer andere Decks frei.
- Deckbuilder-Zahlen werden nach dem Entfernen direkt aktualisiert.

## 0.1.17 - 2026-07-11

- Kleines ManaVault-Datenbackup ergaenzt: Sammlung, Kopien und Decks ohne Scryfall-Katalog.
- Datenbackup-Import stellt die eigenen Daten wieder her; Scryfall kann danach frisch geladen werden.
- Vollbackup bleibt separat fuer komplette `.sqlite3`-Kopien inklusive Scryfall verfuegbar.

## 0.1.16 - 2026-07-11

- Deck-Werte in Stats ergaenzt: Decklistenwert, Originalwert, Proxywert und fehlender Wert je Deck.

## 0.1.15 - 2026-07-10

- Alte Box/Binder-Orte werden im Kartendetail nicht mehr angezeigt.
- Nicht zu Decks zugewiesene Copies werden dort als Sammlung zusammengefasst.
- Fundorte-Ueberschrift im Kartendetail in Status umbenannt.

## 0.1.14 - 2026-07-10

- Orte-Tab und Box/Binder-Verwaltung aus der Oberflaeche entfernt.
- Kartendetails zeigen nur noch Sammlung, Deck oder geplant/fehlt als relevante Zustaende.
- Einzelne Copies koennen weiterhin direkt aus der Sammlung einem Deck zugeordnet werden.

## 0.1.13 - 2026-07-10

- Backup-Tab in Daten umbenannt.
- Datenbank-Export und -Import als zusammengehoerige Sicherungsgruppe nebeneinander angeordnet.
- Sammlungsexport und Scryfall-Datenpflege optisch getrennt.

## 0.1.12 - 2026-07-10

- Preis- und Sammlungswertanzeige im Kartendetail ergaenzt.
- Deutsche Karten zeigen dort nun ebenfalls den englischen Preis-Fallback.

## 0.1.11 - 2026-07-10

- Alte Deckbuilder-Overlay-, Import- und Checkbox-CSS-Reste entfernt.
- Nicht mehr genutzte globale Scryfall-State-Felder entfernt.
- Copy-Zaehler werden nach Deck-Aktionen in Sammlung und Deckbuilder aktualisiert.

## 0.1.10 - 2026-07-10

- Karten-Hovervorschau auch fuer Karten im Deckbuilder-Deckbereich aktiviert.

## 0.1.9 - 2026-07-10

- Deckbuilder nutzt fuer "Ins Deck" immer das gerade bearbeitete Deck.
- Aktives Ziel-Deck der Sammlung ist vom bearbeiteten Builder-Deck getrennt.
- Entscheidungsdialog merkt sich das Zieldeck, mit dem er geoeffnet wurde.

## 0.1.8 - 2026-07-10

- Deckbuilder bekommt eigene Suche und alle Kartenfilter fuer die linke Sammlungsseite.
- Builder-Suche kann zwischen Sammlung und Scryfall-Daten wechseln.

## 0.1.7 - 2026-07-10

- Aktives Ziel-Deck in der Sammlung eingefuehrt.
- Der "Ins Deck"-Button fuegt Karten direkt in das oben ausgewaehlte Deck ein.

## 0.1.6 - 2026-07-10

- Format-Legalitaetsfilter repariert, z.B. Standard legal, Pioneer legal und Commander legal.

## 0.1.5 - 2026-07-10

- Deckbuilder auf das aktuell geoeffnete Deck fokussiert.
- Deck-Export in die Deckliste verschoben.
- Neues Deck und Textimport aus dem Deckbuilder entfernt.

## 0.1.4 - 2026-07-10

- Deckbuilder vom Overlay in eine eigene volle Arbeitsseite verschoben.
- Deck-Tab bleibt aktiv, waehrend der Deckbuilder geoeffnet ist.

## 0.1.3 - 2026-07-10

- Globale Scryfall-Suche deutlich beschleunigt: Mengen werden nur noch fuer die angezeigten Karten berechnet.

## 0.1.2 - 2026-07-10

- Globale Scryfall-Suche repariert, wenn Preisdaten bereits intern geladen wurden.
- Suchmodus sichtbarer gemacht: der Schalter zeigt jetzt Sammlung oder Scryfall.

## 0.1.1 - 2026-07-10

- Sammlung-Export in den Backup-Bereich verschoben.
- Stats laden automatisch beim Oeffnen der Stats-Seite.
- Deckbuilder als grosses Bearbeitungsfenster mit Sammlung links, Deck rechts und ziehbarer Trennlinie aufgebaut.
- Filterleiste und mobile Darstellung geglaettet.

## 0.1.0 - 2026-07-09

- Initial local versioned ManaVault snapshot.
- Collection search, filters, deckbuilder, locations, backup/import/export, Linux service scripts, mobile layout, collection stats, and Scryfall import status are included.
- Local data files are intentionally excluded from version control.
