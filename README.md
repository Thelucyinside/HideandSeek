# Hide and Seek: reales Multiplayer-Spiel mit Smartphones

Willkommen zum Client für das "Hide and Seek" Multiplayer-Spiel! Dieses Projekt ermöglicht es dir, das klassische Versteckspiel in der realen Welt mit deinen Freunden zu spielen, wobei jeder sein Smartphone benutzt.

<!-- Optional: Füge hier einen Link zu einem Screenshot oder Logo ein, wenn du eines hast -->
<!-- Beispiel: ![Hide and Seek Logo](https://raw.githubusercontent.com/Thelucyinside/HideandSeek/refs/heads/main/static/icon-512x512.png) -->

## Spielkonzept (Kurzfassung)

*   **Zwei Rollen:** Hider (Verstecker) und Seeker (Sucher).
*   **Hider:** Versuchen sich in einem festgelegten realen Spielbereich zu verstecken und Aufgaben zu erfüllen (z.B. "Mache ein Foto von X"), um Punkte zu sammeln. Sie werden gewarnt, bevor ihr Standort an die Seeker gesendet wird.
*   **Seeker:** Versuchen, die Hider zu finden. Sie erhalten periodisch (basierend auf GPS-Daten) die Standorte der Hider.
*   **Spielziel:** Hider gewinnen, wenn sie bis zum Ende unentdeckt bleiben oder genug Punkte haben. Seeker gewinnen, wenn sie alle Hider fangen.
*   **Besonderheiten:** Spieler können gemeinsam entscheiden, eine Runde vorzeitig zu beenden.

## Features des Clients

*   Einfache Installation auf Android-Geräten mit Termux.
*   Webbasierte Benutzeroberfläche (PWA), die wie eine native App installiert werden kann.
*   Automatische Update-Prüfung beim Start.
*   Benachrichtigungen über wichtige Spielereignisse (erfordert Termux:API).
*   Standortfreigabe über Browser-Geolocation.

## Installation (für Android mit Termux)

Die Installation ist super einfach! Du brauchst nur die [Termux App](https://f-droid.org/de/packages/com.termux/) auf deinem Android-Gerät.

1.  **Öffne Termux.**
2.  **Kopiere den folgenden Befehl vollständig**, füge ihn in Termux ein und drücke Enter:

    ```bash
    curl -L https://raw.github.com/Thelucyinside/HideandSeek/main/install_hide_and_seek_client.sh | bash
    ```

3.  **Folge den Anweisungen des Installationsskripts.** Es wird dich durch den Prozess führen.

Nach der Installation kannst du das Spiel jederzeit mit folgendem Befehl in Termux starten:

```bash
start
