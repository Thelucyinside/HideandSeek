#!/data/data/com.termux/files/usr/bin/env bash

# Dieses Skript stoppt sofort, wenn etwas schiefgeht.
set -e

# Farben für coole Nachrichten!
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # Keine Farbe

clear # Bildschirm erstmal sauber machen
echo -e "${GREEN}####################################################${NC}"
echo -e "${GREEN}#                                                  #${NC}"
echo -e "${GREEN}#  Willkommen zum Hide and Seek Client Installer!  #${NC}"
echo -e "${GREEN}#                                                  #${NC}"
echo -e "${GREEN}####################################################${NC}"
echo ""
echo -e "Hallo! Ich helfe dir, das Hide and Seek Spiel auf deinem Handy einzurichten."
echo -e "Das ist ganz einfach, keine Sorge! Folge einfach den Schritten."
echo ""
echo -e "${YELLOW}Drücke ENTER, um mit der Installation zu beginnen...${NC}"
read -r

# --- Wichtige Einstellungen (bitte vorab anpassen!) ---
# !!! ÄNDERE DIESE ZEILE ZU DEINEM AKTUELLEN GITHUB REPOSITORY !!!
# Beispiel: GITHUB_REPO_URL="https://github.com/DeinUsername/DeinCoolesSpiel.git"
GITHUB_REPO_URL="https://github.com/Thelucyinside/HideandSeek.git" # <--- HIER DEINE URL EINTRAGEN!L_DIR="$HOME/hide-and-seek-client"
GAME_INSTALL_DIR="$HOME/hide-and-seek-client" # Wo das Spiel gespeichert wird
START_COMMAND_NAME="start"            # So startest du das Spiel später
LOCAL_VERSION_FILE_NAME=".version_hs"         # Kleine Datei für die Versionsnummer
REMOTE_VERSION_FILE_NAME="VERSION.txt"        # Diese Datei muss in deinem GitHub-Repo sein

# Funktion, wenn etwas schiefgeht
handle_error() {
    echo ""
    echo -e "${RED}----------------------------------------------------${NC}"
    echo -e "${RED}Hoppla! Da ist etwas schiefgelaufen... Fehler:        ${NC}"
    echo -e "${RED}$1${NC}"
    echo -e "${RED}----------------------------------------------------${NC}"
    echo -e "${YELLOW}Die Installation konnte nicht abgeschlossen werden.${NC}"
    echo -e "${YELLOW}Versuch mal, Termux neu zu starten und das Skript nochmal auszuführen.${NC}"
    echo -e "${YELLOW}Wenn es immer noch nicht klappt, frag den Freund, der dir den Befehl gegeben hat, oder den Entwickler des Spiels um Hilfe.${NC}"
    exit 1
}

# Überprüfen, ob die GITHUB_REPO_URL angepasst wurde
if [[ "$GITHUB_REPO_URL" == "https://github.com/DEIN_BENUTZERNAME/DEIN_REPOSITORYNAME.git" ]]; then
    echo -e "${RED}ACHTUNG: Du musst die GITHUB_REPO_URL im Skript anpassen!${NC}"
    handle_error "Bitte den Entwickler bitten, die GitHub-URL im Installationsskript ('install_hide_and_seek_client.sh') zu korrigieren."
fi

echo ""
echo -e "${BLUE}Okay, los geht's!${NC}"
echo ""

# 1. Termux auf den neuesten Stand bringen und wichtige Werkzeuge installieren
echo -e "${YELLOW}Schritt 1: Termux vorbereiten und Werkzeuge installieren...${NC}"
echo "Ich frage jetzt Termux, ob es neue Updates für sich selbst hat..."
pkg update -y || handle_error "Konnte Termux' Software-Katalog nicht aktualisieren."
echo "Super! Jetzt installiere ich ein paar Werkzeuge, die wir brauchen:"
echo "  - ${GREEN}python:${NC} Die Programmiersprache, in der das Spiel geschrieben ist."
echo "  - ${GREEN}git:${NC} Damit laden wir das Spiel von GitHub herunter."
echo "  - ${GREEN}curl:${NC} Ein kleines Werkzeug, um Webseiten-Infos abzurufen (für Updates)."
echo "  - ${GREEN}termux-api:${NC} Damit das Spiel dir Benachrichtigungen auf deinem Handy zeigen kann."
pkg install -y python git curl termux-api || handle_error "Konnte die notwendigen Werkzeuge (python, git, curl, termux-api) nicht installieren."
echo -e "${GREEN}Alle Werkzeuge sind bereit!${NC}"
echo ""

# 2. Spieldateien von GitHub herunterladen
echo -e "${YELLOW}Schritt 2: Das Spiel von GitHub herunterladen...${NC}"
echo "Ich verbinde mich jetzt mit GitHub und lade die Spieldateien herunter."
echo "Das Spiel wird hier gespeichert: ${GAME_INSTALL_DIR}"

if [ -d "$GAME_INSTALL_DIR" ]; then
    echo -e "${YELLOW}Oh, das Spiel scheint schonmal installiert worden zu sein (Ordner '$GAME_INSTALL_DIR' existiert).${NC}"
    echo -e "${YELLOW}Möchtest du alles Alte löschen und es frisch neu installieren? (ja/nein)${NC}"
    read -r choice
    if [[ "$choice" =~ ^[Jj][Aa]?$ ]]; then
        echo "Alles klar, ich lösche das alte Verzeichnis..."
        rm -rf "$GAME_INSTALL_DIR" || handle_error "Konnte den alten Spielordner nicht löschen."
        echo "Alter Spielordner gelöscht."
    else
        echo -e "${YELLOW}Okay, dann breche ich die Installation hier ab, um nichts kaputt zu machen.${NC}"
        echo "Du kannst das Spiel vielleicht schon mit '$START_COMMAND_NAME' starten."
        exit 0
    fi
fi

git clone "$GITHUB_REPO_URL" "$GAME_INSTALL_DIR" || handle_error "Konnte das Spiel nicht von GitHub herunterladen. Ist die Internetverbindung okay? Stimmt die Adresse im Skript ($GITHUB_REPO_URL)?"
cd "$GAME_INSTALL_DIR" || handle_error "Konnte nicht in den heruntergeladenen Spielordner wechseln."

# Überprüfen, ob die wichtigen Dateien da sind
if [ ! -f "client.py" ] || [ ! -d "static" ]; then
    handle_error "Im heruntergeladenen Ordner fehlen wichtige Dateien ('client.py' oder 'static/'). Das GitHub-Repo ist vielleicht nicht richtig eingerichtet."
fi
if [ ! -f "$REMOTE_VERSION_FILE_NAME" ]; then
    handle_error "Die Datei '$REMOTE_VERSION_FILE_NAME' (für Updates) fehlt im GitHub-Repo."
fi
cp "$REMOTE_VERSION_FILE_NAME" "$LOCAL_VERSION_FILE_NAME" || handle_error "Konnte die lokale Versionsinfo nicht speichern."

echo -e "${GREEN}Spiel erfolgreich heruntergeladen!${NC}"
echo ""

# 3. Python-Zusatzmodul Flask installieren
echo -e "${YELLOW}Schritt 3: Ein wichtiges Python-Modul (Flask) installieren...${NC}"
echo "Das Spiel braucht ein kleines Zusatz-Teil für Python, damit die Webseite funktioniert."
if command -v pip &> /dev/null; then
    pip install Flask || handle_error "Konnte Flask mit pip nicht installieren."
elif command -v pip3 &> /dev/null; then
    pip3 install Flask || handle_error "Konnte Flask mit pip3 nicht installieren."
else
    handle_error "'pip' wurde nicht gefunden. Da stimmt was mit der Python-Installation nicht."
fi
echo -e "${GREEN}Flask erfolgreich installiert! Fast geschafft!${NC}"
echo ""

# 4. Start-Skript erstellen (damit du es einfach starten kannst)
echo -e "${YELLOW}Schritt 4: Einen einfachen Startbefehl einrichten ('$START_COMMAND_NAME')...${NC}"
echo "Ich erstelle jetzt einen kurzen Befehl, damit du das Spiel später ganz einfach mit '$START_COMMAND_NAME' starten kannst."
START_SCRIPT_PATH="$PREFIX/bin/$START_COMMAND_NAME"

# GitHub URL für die rohe VERSION.txt Datei (für Updates)
# Annahme: master oder main branch
RAW_GITHUB_BASE_URL=$(echo "$GITHUB_REPO_URL" | sed 's|github.com|raw.githubusercontent.com|' | sed 's|\.git$||')
REMOTE_VERSION_CHECK_URL_MASTER="${RAW_GITHUB_BASE_URL}/master/${REMOTE_VERSION_FILE_NAME}"
REMOTE_VERSION_CHECK_URL_MAIN="${RAW_GITHUB_BASE_URL}/main/${REMOTE_VERSION_FILE_NAME}"

cat > "$START_SCRIPT_PATH" <<EOF
#!/data/data/com.termux/files/usr/bin/env bash
# Startskript für Hide and Seek Client (erstellt von install_hide_and_seek_client.sh)

GAME_DIR="$GAME_INSTALL_DIR"
LOCAL_VERSION_FILE="\$GAME_DIR/$LOCAL_VERSION_FILE_NAME"
REMOTE_VERSION_FILE_ON_SERVER="$REMOTE_VERSION_FILE_NAME" # Name der Datei auf dem Server
CLIENT_SCRIPT="client.py"

# Farben
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "\${BLUE}=====================================\${NC}"
echo -e "\${BLUE}  Hide and Seek Client wird gestartet \${NC}"
echo -e "\${BLUE}=====================================\${NC}"
echo ""

cd "\$GAME_DIR" || { echo -e "\${RED}FEHLER: Ich kann den Spielordner nicht finden: '\$GAME_DIR'\${NC}"; exit 1; }

echo -e "\${YELLOW}Moment, ich schaue schnell nach, ob es eine neue Version vom Spiel gibt...${NC}"

# Lokale Version holen
if [ ! -f "\$LOCAL_VERSION_FILE" ]; then
    echo -e "\${YELLOW}Info: Konnte deine installierte Version nicht finden. Update-Check übersprungen.${NC}"
    # Versuche, die aktuelle Version aus dem Git Repo zu holen, falls die lokale Datei fehlt
    if [ -f "\$REMOTE_VERSION_FILE_ON_SERVER" ]; then
        cp "\$REMOTE_VERSION_FILE_ON_SERVER" "\$LOCAL_VERSION_FILE"
        echo "Lokale Versionsinfo wurde wiederhergestellt."
    fi
fi
LOCAL_VERSION=\$(cat "\$LOCAL_VERSION_FILE" 2>/dev/null)

# Neueste Version von GitHub holen (probiert master und main branch)
REMOTE_VERSION=\$(curl -sSL "$REMOTE_VERSION_CHECK_URL_MASTER")
if [ -z "\$REMOTE_VERSION" ] || [[ "\$REMOTE_VERSION" == *"404: Not Found"* ]]; then # Check ob master 404 liefert
    REMOTE_VERSION=\$(curl -sSL "$REMOTE_VERSION_CHECK_URL_MAIN")
fi

if [ -z "\$REMOTE_VERSION" ] || [[ "\$REMOTE_VERSION" == *"404: Not Found"* ]]; then
    echo -e "\${YELLOW}Konnte die neueste Version nicht von GitHub abrufen. Vielleicht keine Internetverbindung?${NC}"
    echo -e "\${YELLOW}Ich überspringe den Update-Check für dieses Mal.${NC}"
elif [ -z "\$LOCAL_VERSION" ]; then
    echo -e "\${YELLOW}Deine installierte Version ist nicht bekannt. Es ist eine gute Idee, zu aktualisieren!${NC}"
    # Hier könnte man direkt ein Update anbieten
elif [ "\$LOCAL_VERSION" != "\$REMOTE_VERSION" ]; then
    echo -e "\${GREEN}Juhu! Eine neue Version vom Spiel ist da!${NC}"
    echo "Deine Version:      \$LOCAL_VERSION"
    echo "Neueste Version:  \$REMOTE_VERSION"
    echo ""
    echo -e "\${YELLOW}Möchtest du das Spiel jetzt aktualisieren? (ja/nein)${NC}"
    read -r confirm_update
    if [[ "\$confirm_update" =~ ^[Jj][Aa]?$ ]]; then
        echo "Super! Ich aktualisiere das Spiel..."
        git pull origin master || git pull origin main || git pull # Probiert master, dann main, dann default
        if [ \$? -eq 0 ]; then
            if [ -f "\$REMOTE_VERSION_FILE_ON_SERVER" ]; then
                 cp "\$REMOTE_VERSION_FILE_ON_SERVER" "\$LOCAL_VERSION_FILE" # Lokale Version aktualisieren
                 echo -e "\${GREEN}Update erfolgreich auf Version \$REMOTE_VERSION!${NC}"
            else
                 echo -e "\${RED}Update fertig, aber die Versionsdatei ('\$REMOTE_VERSION_FILE_ON_SERVER') fehlt im Update. Deine Versionsanzeige ist vielleicht nicht aktuell.${NC}"
            fi
        else
            echo -e "\${RED}Das Update hat leider nicht geklappt. Ich starte das Spiel mit deiner aktuellen Version.${NC}"
        fi
    else
        echo "Okay, kein Update. Ich starte das Spiel mit Version \$LOCAL_VERSION."
    fi
else
    echo -e "\${GREEN}Du hast schon die aktuellste Version (\$LOCAL_VERSION). Perfekt!${NC}"
fi

echo ""
echo -e "\${GREEN}Alles klar, das Spiel (client.py) wird jetzt gestartet...${NC}"
echo "Wenn das Spiel läuft, öffne deinen Internet-Browser und gib ein:"
echo -e "\${YELLOW}  http://localhost:5000${NC}"
echo ""
echo "Hab viel Spaß!"
echo "----------------------------------------------------"
# Stelle sicher, dass Python das Skript findet und ausführt
if [ -f "\$CLIENT_SCRIPT" ]; then
    python "\$CLIENT_SCRIPT"
else
    echo -e "\${RED}FEHLER: Die Spieldatei '$CLIENT_SCRIPT' wurde nicht im Ordner '\$GAME_DIR' gefunden!${NC}"
    exit 1
fi
echo "----------------------------------------------------"
echo -e "\${GREEN}Das Hide and Seek Spiel wurde beendet.${NC}"
EOF

chmod +x "$START_SCRIPT_PATH" || handle_error "Konnte den Startbefehl nicht ausführbar machen."

echo -e "${GREEN}Startbefehl '$START_COMMAND_NAME' wurde erfolgreich eingerichtet!${NC}"
echo ""

# --- Finale Anleitungen ---
echo -e "${GREEN}#######################################################${NC}"
echo -e "${GREEN}#                                                     #${NC}"
echo -e "${GREEN}#  GESCHAFFT! Die Installation ist FERTIG!            #${NC}"
echo -e "${GREEN}#                                                     #${NC}"
echo -e "${GREEN}#######################################################${NC}"
echo ""
echo "Du bist jetzt bereit, Hide and Seek zu spielen!"
echo ""
echo -e "So startest du das Spiel (einfach in Termux eingeben und ENTER drücken):"
echo -e "  ${YELLOW}$START_COMMAND_NAME${NC}"
echo ""
echo "Das Spiel wird dann im Hintergrund gestartet und du siehst ein paar Meldungen."
echo ""
echo -e "${BLUE}--- WICHTIG FÜR BENACHRICHTIGUNGEN ---${NC}"
echo "Damit das Spiel dir Nachrichten (z.B. Warnungen) auf deinem Handy zeigen kann,"
echo "brauchst du noch eine kleine Zusatz-App:"
echo ""
echo -e "1. ${YELLOW}Installiere die App 'Termux:API'${NC} aus dem App Store."
echo "   (Am besten von F-Droid, da die Version im Google Play Store oft veraltet ist)."
echo "   Suche einfach nach 'Termux:API'."
echo "2. Nachdem du die App installiert hast, öffne sie einmal und folge den Anweisungen dort,"
echo "   um ihr die nötigen Rechte zu geben (vor allem für Benachrichtigungen)."
echo -e "${GREEN}Das war's schon für die Benachrichtigungen!${NC}"
echo ""
echo -e "${BLUE}--- WIE DU DAS SPIEL IM BROWSER ÖFFNEST (ALS APP!) ---${NC}"
echo "Wenn du das Spiel mit '$START_COMMAND_NAME' gestartet hast:"
echo ""
echo "1. Öffne deinen ${YELLOW}Internet-Browser${NC} auf dem Handy (z.B. Chrome, Firefox)."
echo "2. Gib in die Adresszeile oben ein: ${YELLOW}http://localhost:5000${NC} und drücke Enter."
echo "   (Kein www davor, einfach nur das!)"
echo "3. Die Spiel-Webseite sollte jetzt laden."
echo ""
echo -e "   ${GREEN}COOLER TIPP:${NC} Du kannst die Webseite wie eine richtige App auf deinem"
echo "   Startbildschirm speichern! So geht's meistens:"
echo "   a. Wenn die Seite geladen ist, tippe auf das ${YELLOW}Menü-Symbol${NC} im Browser"
echo "      (oft drei Punkte oder drei Striche oben rechts)."
echo "   b. Suche nach einer Option wie ${YELLOW}'Zum Startbildschirm hinzufügen'${NC},"
echo "      ${YELLOW}'App installieren'${NC} oder ${YELLOW}'Seite hinzufügen zu...'${NC}."
echo "   c. Folge den Anweisungen. Danach hast du ein Spiel-Icon auf deinem Handy!"
echo ""
echo "Viel Spaß beim Verstecken und Suchen!"
echo -e "${GREEN}Dein Hide and Seek Installations-Helfer :)${NC}"

exit 0
