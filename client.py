# client.py
import socket
import json
import time
import threading
import subprocess 
import random
from flask import Flask, jsonify, request, send_from_directory, session

# Standardwerte, können zur Laufzeit geändert werden
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65432
FLASK_PORT = 5000
STATIC_FOLDER = 'static' 

# Das globale Dictionary, das die Daten für die UI bereithält
# Es wird von den Netzwerk-Threads aktualisiert und vom Flask-Server gelesen.
client_view_data = {
    "player_id": None, # Eindeutige ID des Spielers, vom Server zugewiesen
    "player_name": None, # Name des Spielers
    "role": None, # Aktuelle Rolle des Spielers (hider/seeker)
    "location": None, # Letzter bekannter Standort [latitude, longitude, accuracy]
    "confirmed_for_lobby": False, # Hat der Spieler den Lobby-Beitritt bestätigt?
    "player_is_ready": False, # Hat der Spieler in der Lobby "Bereit" geklickt?
    "player_status": "active", # Aktueller Ingame-Status (active, caught etc.)
    "is_socket_connected_to_server": False, # Ist die Socket-Verbindung zum Spielserver aktiv?
    "game_state": { # Informationen über den aktuellen Spielzustand
        "status": "disconnected", 
        "status_display": "Initialisiere Client...",
        "game_time_left": 0, 
        "hider_wait_time_left": 0, 
        "game_over_message": None
    },
    "lobby_players": {}, # Liste der Spieler in der Lobby
    "all_players_status": {}, # Status aller Spieler im Spiel (für All-Players-Liste)
    "current_task": None, # Aktuelle Aufgabe für Hider
    "hider_leaderboard": [], # Hider-Bestenliste
    "hider_locations": {}, # Sichtbare Hider-Standorte für Seeker
    "power_ups_available": [], # Verfügbare Power-Ups für Seeker
    "game_message": None, # Allgemeine Spielnachrichten (Erfolg)
    "error_message": None, # Allgemeine Fehlermeldungen
    "join_error": None, # Spezifische Fehlermeldung für den Join-Prozess
    "prefill_nickname": f"Spieler{random.randint(100,999)}", # Zufälliger Nickname für den ersten Start
    "hider_location_update_imminent": False, # Warnflag für Hider (Standort wird bald gesendet)
    "early_end_requests_count": 0, # Anzahl der Spieler, die frühes Ende wollen
    "total_active_players_for_early_end": 0, # Gesamtzahl der aktiven Spieler für Abstimmung
    "player_has_requested_early_end": False, # Hat dieser Spieler bereits das frühe Ende beantragt?
    "current_server_host": SERVER_HOST, # Aktueller Server-Host (für UI-Anzeige)
    "current_server_port": SERVER_PORT,  # Aktueller Server-Port (für UI-Anzeige)
    "task_skips_available": 0 # NEU: Anzahl der verfügbaren Aufgaben-Skips
}
client_data_lock = threading.Lock() # Lock für den Zugriff auf client_view_data
server_socket_global = None # Globale Variable für den Socket zum Spielserver
is_connected_to_server = False # Status der Server-Verbindung

# Spielzustands-Konstanten (zur besseren Lesbarkeit)
GAME_STATE_LOBBY = "lobby"
GAME_STATE_HIDER_WAIT = "hider_wait"
GAME_STATE_RUNNING = "running"
GAME_STATE_HIDER_WINS = "hider_wins"
GAME_STATE_SEEKER_WINS = "seeker_wins"


app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='') 
app.secret_key = "dein_super_geheimer_und_einzigartiger_schluessel_hier_aendern_DRINGEND" # Wichtig für Flask Sessions!

def show_termux_notification(title, content, notification_id=None):
    """
    Sendet eine Systembenachrichtigung über Termux-API (nur auf Android mit Termux-App).
    Ignoriert Fehler, wenn Termux-Tools nicht vorhanden sind.
    """
    try:
        command = ['termux-notification', '--title', title, '--content', content]
        if notification_id:
            command.extend(['--id', str(notification_id)])
        command.extend(['--vibrate', '500']) # Kurz vibrieren
        subprocess.run(command, check=False) # check=False, um Fehler beim Fehlen des Tools zu ignorieren
    except FileNotFoundError:
        print("CLIENT NOTIFY ERROR: 'termux-notification' nicht gefunden. Bitte Termux:API installieren.")
    except Exception as e:
        print(f"CLIENT NOTIFY ERROR: Unerwarteter Fehler bei Termux-Benachrichtigung: {e}")

def send_message_to_server(data):
    """
    Sendet eine JSON-Nachricht über den globalen Socket an den Spielserver.
    """
    global server_socket_global, is_connected_to_server
    action_sent = data.get('action', 'NO_ACTION_SPECIFIED') # Aktion für Logging
    if server_socket_global and is_connected_to_server:
        try:
            server_socket_global.sendall(json.dumps(data).encode('utf-8') + b'\n') # Nachricht senden, mit Zeilenumbruch abschließen
            return True # Senden erfolgreich
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"CLIENT SEND (ERROR): Senden von '{action_sent}' fehlgeschlagen, Verbindung verloren: {e}.")
            is_connected_to_server = False # Verbindung ist nicht mehr aktiv
            with client_data_lock: # Daten für UI aktualisieren
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Verbindung zum Server verloren (Senden)."
                client_view_data["error_message"] = "Verbindung zum Server verloren."
    else:
        with client_data_lock:
            client_view_data["is_socket_connected_to_server"] = False
            if not client_view_data.get("error_message"): # Nur wenn kein anderer Fehler aktiv ist
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
    return False # Senden fehlgeschlagen

def network_communication_thread():
    """
    Thread, der die permanente Kommunikation mit dem Spielserver verwaltet.
    Stellt Verbindung her, empfängt Nachrichten und hält den Socket-Status aktuell.
    """
    global server_socket_global, is_connected_to_server, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = "" # Puffer für unvollständige Nachrichten
    while True: # Endlosschleife für Verbindungsmanagement und Empfang
        if not is_connected_to_server: # Wenn nicht verbunden, versuche Verbindung herzustellen
            try:
                current_host_to_connect = ""
                current_port_to_connect = 0
                with client_data_lock: # Aktuelle Server-Details aus client_view_data holen
                    client_view_data["is_socket_connected_to_server"] = False
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"): 
                         client_view_data["game_state"]["status_display"] = f"Verbinde mit Spielserver {SERVER_HOST}:{SERVER_PORT}..."
                    current_host_to_connect = SERVER_HOST
                    current_port_to_connect = SERVER_PORT
                
                print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}...")
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5) # 5 Sekunden Timeout für den Verbindungsversuch
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                temp_sock.settimeout(None) # Nach erfolgreicher Verbindung: kein Timeout mehr
                server_socket_global = temp_sock # Globalen Socket setzen
                is_connected_to_server = True # Status auf verbunden setzen
                print(f"CLIENT NET: Verbunden mit {current_host_to_connect}:{current_port_to_connect}! Socket: {server_socket_global.fileno() if server_socket_global else 'N/A'}")
                buffer = "" # Puffer leeren bei neuer Verbindung
                with client_data_lock: # UI-Status aktualisieren
                    client_view_data["is_socket_connected_to_server"] = True
                    client_view_data["error_message"] = None; client_view_data["join_error"] = None 
                    if client_view_data["game_state"].get("status") == "disconnected": 
                         client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Spielbeitritt..."
            except socket.timeout:
                print(f"CLIENT NET (CONNECT TIMEOUT) zu {current_host_to_connect}:{current_port_to_connect}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung."
                time.sleep(3); continue # 3 Sekunden warten vor nächstem Versuch
            except (ConnectionRefusedError, OSError) as e:
                print(f"CLIENT NET (CONNECT ERROR) zu {current_host_to_connect}:{current_port_to_connect}: {e}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen."
                time.sleep(3); continue
            except Exception as e_fatal_connect: 
                print(f"CLIENT NET (FATAL CONNECT) zu {current_host_to_connect}:{current_port_to_connect}: {e_fatal_connect}")
                time.sleep(3); continue
        
        # Empfangs-Schleife, wenn verbunden
        try:
            if not server_socket_global: is_connected_to_server = False; time.sleep(0.1); continue # Falls Socket während des Loops geschlossen wurde
            data_chunk = server_socket_global.recv(8192) # Daten empfangen
            if not data_chunk: # Server hat Verbindung geschlossen
                print("CLIENT NET (INFO): Leeres data_chunk. Server hat Verbindung geschlossen."); is_connected_to_server = False
                with client_data_lock: client_view_data["game_state"]["status_display"] = "Server hat Verbindung getrennt."
                continue
            buffer += data_chunk.decode('utf-8') # Daten zum Puffer hinzufügen

            # Nachrichten aus dem Puffer extrahieren (durch Zeilenumbruch getrennt)
            while '\n' in buffer:
                message_str, buffer = buffer.split('\n', 1)
                if not message_str.strip(): continue # Leere Nachrichten ignorieren
                message = json.loads(message_str) # JSON parsen

                with client_data_lock: # Daten für UI aktualisieren
                    client_view_data["is_socket_connected_to_server"] = True 
                    msg_type = message.get("type")

                    if msg_type == "game_update": # Haupt-Update vom Server
                        # Logik für Server-seitigen Spieler-Reset (z.B. nach LEAVE_GAME oder SERVER_RESET)
                        if "player_id" in message and message["player_id"] is None and client_view_data["player_id"] is not None:
                            print("CLIENT NET: Player_id wurde vom Server auf null gesetzt. Client wird zurückgesetzt.")
                            client_view_data["player_id"] = None
                            client_view_data["player_name"] = None 
                            client_view_data["role"] = None
                            client_view_data["confirmed_for_lobby"] = False
                            client_view_data["player_is_ready"] = False
                            # Behalte Session-Daten für Nickname/Rolle für das nächste Join-Formular
                        
                        elif "player_id" in message and message["player_id"] is not None:
                            client_view_data["player_id"] = message["player_id"]; client_view_data["join_error"] = None
                        
                        # Aktualisiere die client_view_data mit den neuen Daten vom Server
                        update_keys = [
                            "player_name", "role", "confirmed_for_lobby", "player_is_ready", 
                            "player_status", "location", "game_state", "lobby_players", 
                            "all_players_status", "current_task", "hider_leaderboard", 
                            "hider_locations", "power_ups_available", "hider_location_update_imminent",
                            "early_end_requests_count", "total_active_players_for_early_end",
                            "player_has_requested_early_end",
                            "task_skips_available" 
                        ]
                        for key in update_keys:
                            if key in message: client_view_data[key] = message[key]
                        
                        # Wenn der Server einen Reset durchgeführt hat, kann eine Fehlermeldung mitkommen
                        if message.get("error_message") and message["player_id"] is None:
                            client_view_data["error_message"] = message["error_message"]
                            client_view_data["join_error"] = message["error_message"] # Auch als Join-Error anzeigen

                    elif msg_type == "server_text_notification": # Allgemeine Server-Benachrichtigung (via Termux)
                        game_msg_text = message.get("message", "Server Nachricht")
                        show_termux_notification(title="Hide and Seek Info", content=game_msg_text, notification_id="server_info")
                        client_view_data["game_message"] = game_msg_text

                    elif msg_type == "game_event": # Spezielle Spiel-Events (via Termux)
                        event_name = message.get("event_name")
                        print(f"CLIENT NET: Game Event empfangen: {event_name}")
                        
                        if event_name == "hider_location_update_due":
                            show_termux_notification(
                                title="Hide and Seek: ACHTUNG!",
                                content="Hider: Standort bald benötigt! Öffne die App.",
                                notification_id="hider_warn"
                            )
                            client_view_data["hider_location_update_imminent"] = True

                        elif event_name == "seeker_locations_updated":
                             show_termux_notification(
                                title="Hide and Seek", content="Seeker: Hider-Standorte aktualisiert!",
                                notification_id="seeker_update" )
                        elif event_name == "game_started":
                            show_termux_notification(title="Hide and Seek", content="Das Spiel hat begonnen!", notification_id="game_start")
                        

                    elif msg_type == "error": # Fehlermeldungen vom Server
                        error_text = message.get("message", "Unbekannter Fehler vom Server")
                        client_view_data["error_message"] = error_text
                        critical_errors = ["Spiel läuft bereits", "Spiel voll", "Nicht authentifiziert", "Bitte neu beitreten", "Du bist nicht mehr Teil des aktuellen Spiels", "Server wurde von einem Spieler zurückgesetzt"]
                        if any(crit_err in error_text for crit_err in critical_errors):
                            client_view_data["join_error"] = error_text # Spezifischer Join-Fehler
                            if client_view_data["player_id"] is not None: # Wenn eine ID existierte, Client-Seite zurücksetzen
                                client_view_data["player_id"] = None 
                                client_view_data["player_name"] = None
                                client_view_data["role"] = None
                    
                    elif msg_type == "acknowledgement": # Bestätigung einer Aktion vom Server
                        ack_message = message.get("message", "Aktion bestätigt.")
                        client_view_data["game_message"] = ack_message
                        print(f"CLIENT NET: Acknowledgement vom Server: {ack_message}")

        except json.JSONDecodeError:
            print(f"CLIENT NET (JSON ERROR): Ungültiges JSON: '{message_str if 'message_str' in locals() else 'Buffer-Problem'}'. Puffer zurückgesetzt."); buffer = ""
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"CLIENT NET (CONN ERROR): Empfangsfehler: {e}."); is_connected_to_server = False # Verbindung unterbrochen
            with client_data_lock: client_view_data["game_state"]["status_display"] = "Verbindung getrennt (Empfang)."
        except Exception as e: 
            print(f"CLIENT NET (UNEXPECTED ERROR): In Netzwerk-Schleife: {e}"); import traceback; traceback.print_exc(); is_connected_to_server = False
        finally: 
            if not is_connected_to_server: # Wenn Verbindung getrennt ist, Socket schließen und Status aktualisieren
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                if server_socket_global:
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None

# Flask Routen für die Web-UI

@app.route('/') 
def index_page_route(): 
    """ Liefert die Haupt-HTML-Seite (index.html) aus. """
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/manifest.json')
def manifest_route(): 
    """ Liefert das PWA-Manifest aus. """
    return send_from_directory(app.static_folder, 'manifest.json')

@app.route('/sw.js')
def service_worker_route(): 
    """ Liefert den Service Worker aus. """
    return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')

@app.route('/offline.html')
def offline_route(): 
    """ Liefert die Offline-Fallback-Seite aus. """
    return send_from_directory(app.static_folder, 'offline.html')

@app.route('/icons/<path:filename>') 
def icons_route(filename): 
    """ Liefert die App-Icons aus. """
    return send_from_directory(app.static_folder, f'icons/{filename}')


@app.route('/status', methods=['GET'])
def get_status():
    """ 
    Gibt den aktuellen Zustand des Clients als JSON an die Web-UI zurück.
    Die UI pollt regelmäßig diesen Endpunkt.
    """
    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST # Sicherstellen, dass die UI den aktuellen Host/Port kennt
        client_view_data["current_server_port"] = SERVER_PORT
        
        data_to_send = client_view_data.copy()
        # Session-Daten für Prefill in der UI mitsenden
        data_to_send["session_nickname"] = session.get("nickname")
        data_to_send["session_role_choice"] = session.get("role_choice")
        return jsonify(data_to_send)

@app.route('/join_game', methods=['POST'])
def join_game_route():
    """ 
    Verarbeitet den Beitrittsanfrage des Spielers. 
    Kann die Serveradresse ändern und die Verbindung neu aufbauen.
    """
    global SERVER_HOST, SERVER_PORT, is_connected_to_server, server_socket_global
    data = request.get_json()
    if not data: return jsonify({"success": False, "message": "Keine Daten."}), 400

    nickname = data.get('nickname')
    role_choice = data.get('role')
    new_server_host = data.get('server_host')
    new_server_port_str = data.get('server_port')

    # Eingaben validieren
    if not nickname or not role_choice: return jsonify({"success": False, "message": "Name/Rolle fehlt."}), 400
    if not new_server_host or not new_server_port_str:
        return jsonify({"success": False, "message": "Serveradresse oder Port fehlt."}), 400

    try:
        new_server_port = int(new_server_port_str)
        if not (0 < new_server_port < 65536):
            raise ValueError("Port außerhalb des gültigen Bereichs")
    except ValueError:
        return jsonify({"success": False, "message": "Ungültiger Server-Port."}), 400

    # Nickname und Rolle in Flask-Session speichern für Prefill
    session["nickname"] = nickname
    session["role_choice"] = role_choice
    
    server_details_changed = False
    with client_data_lock:
        # Prüfen, ob sich Server-Host oder -Port geändert haben
        if SERVER_HOST != new_server_host or SERVER_PORT != new_server_port:
            print(f"CLIENT: Serverdetails geändert von {SERVER_HOST}:{SERVER_PORT} zu {new_server_host}:{new_server_port}")
            SERVER_HOST = new_server_host # Globalen Host aktualisieren
            SERVER_PORT = new_server_port # Globalen Port aktualisieren
            client_view_data["current_server_host"] = SERVER_HOST # UI-Status aktualisieren
            client_view_data["current_server_port"] = SERVER_PORT
            server_details_changed = True
        
        # client_view_data für den Join-Versuch zurücksetzen/vorbereiten
        client_view_data.update({
            "player_id": None, # ID muss vom Server neu vergeben werden
            "player_name": nickname, # Name für diesen Join-Versuch
            "role": role_choice,     # Rolle für diesen Join-Versuch
            "confirmed_for_lobby": False, "player_is_ready": False, "player_status": "active",
            "join_error": None, "error_message": None, "game_message": None,
            "current_task": None, "hider_leaderboard": [], "hider_locations": {},
            "power_ups_available": [], "hider_location_update_imminent": False,
            "early_end_requests_count": 0, "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False,
            "task_skips_available": 0 
        })
        # Sicherstellen, dass game_state existiert
        if "game_state" not in client_view_data or client_view_data["game_state"] is None: 
            client_view_data["game_state"] = {"status": "disconnected", "status_display": "Initialisiere..."}
        
        if server_details_changed:
            # Wenn Serverdetails geändert wurden, den Socket schließen, damit der Netzwerk-Thread sich neu verbindet
            client_view_data["game_state"]["status"] = "disconnected"
            client_view_data["game_state"]["status_display"] = f"Serveradresse aktualisiert. Verbinde mit {SERVER_HOST}:{SERVER_PORT}..."
            client_view_data["is_socket_connected_to_server"] = False
            is_connected_to_server = False 
            if server_socket_global:
                print("CLIENT: Schließe alte Socket-Verbindung aufgrund geänderter Serverdetails.")
                try:
                    server_socket_global.shutdown(socket.SHUT_RDWR) # Versuch eines sauberen Shutdowns
                    server_socket_global.close()
                except OSError as e:
                    print(f"CLIENT: Fehler beim Schließen des alten Sockets: {e}")
                server_socket_global = None
        else:
             client_view_data["game_state"]["status_display"] = f"Sende Beitrittsanfrage als {nickname}..."
    
    response_for_js = {"success": True, "message": "Beitrittsanfrage wird verarbeitet."}
    
    # Wenn Serverdetails geändert wurden, muss die UI auf den Neuaufbau der Verbindung warten
    if server_details_changed:
        response_for_js = {"success": True, "message": "Serveradresse geändert. Verbindung wird neu aufgebaut. Bitte warten."}
    else: # Wenn Serverdetails gleich geblieben sind, sofort versuchen, Join-Nachricht zu senden
        socket_conn_ok = False
        with client_data_lock: socket_conn_ok = client_view_data.get("is_socket_connected_to_server", False)

        if socket_conn_ok and is_connected_to_server:
            if not send_message_to_server({"action": "JOIN_GAME", "name": nickname, "role": role_choice}):
                response_for_js = {"success": False, "message": "Senden der Join-Anfrage fehlgeschlagen."}
                with client_data_lock: client_view_data["join_error"] = "Senden der Join-Anfrage fehlgeschlagen."
        else: # Keine Verbindung, aber der Netzwerk-Thread wird es versuchen
            with client_data_lock: 
                client_view_data["join_error"] = "Nicht mit Server verbunden für Join-Anfrage. Warte auf Verbindung..."
                client_view_data["game_state"]["status_display"] = f"Warte auf Verbindung zu {SERVER_HOST}:{SERVER_PORT} für Join als {nickname}..."
            response_for_js = {"success": True, "message": "Keine Serververbindung für Join-Anfrage. Warte auf automatische Verbindung..."} 
            
    with client_data_lock: 
        current_status = client_view_data.copy()
        current_status["session_nickname"] = session.get("nickname")
        current_status["session_role_choice"] = session.get("role_choice")
    current_status["join_attempt_response"] = response_for_js # Direkte Antwort für den fetch-Aufruf in der UI
    return jsonify(current_status)

@app.route('/update_location_from_browser', methods=['POST'])
def update_location_from_browser():
    """ 
    Empfängt Standortdaten vom Browser und leitet sie an den Spielserver weiter.
    """
    data = request.get_json()
    if not data: return jsonify({"success": False, "message": "Keine Daten."}), 400
    lat, lon, accuracy = data.get('lat'), data.get('lon'), data.get('accuracy')
    if lat is None or lon is None or accuracy is None:
        return jsonify({"success": False, "message": "Unvollständige Standortdaten."}), 400

    player_id_local, game_status_local, socket_ok_local = None, None, False
    with client_data_lock: # Aktuelle Spieler- und Verbindungsdaten abrufen
        player_id_local = client_view_data.get("player_id")
        game_status_local = client_view_data.get("game_state", {}).get("status")
        socket_ok_local = client_view_data.get("is_socket_connected_to_server", False)

    game_can_receive_loc = game_status_local in [GAME_STATE_LOBBY, GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]
    if player_id_local and game_can_receive_loc and socket_ok_local and is_connected_to_server:
        send_success = send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy})
        if send_success: 
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy] # Lokale Anzeige aktualisieren
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID vorhanden, Standort nicht gesendet."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    else: return jsonify({"success": False, "message": "Keine Serververbindung (Socket), Standort nicht gesendet."}), 503

def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True):
    """
    Generische Funktion zur Verarbeitung von Client-Aktionen.
    Leitet Anfragen von der UI an den Spielserver weiter.
    """
    action_payload = {"action": action_name}; player_id_for_action = None # Wird nur gesetzt, wenn requires_player_id True ist
    
    if requires_player_id:
        with client_data_lock: player_id_for_action = client_view_data.get("player_id")
        if not player_id_for_action:
            with client_data_lock: 
                temp_cvd = client_view_data.copy() 
                temp_cvd["session_nickname"] = session.get("nickname")
                temp_cvd["session_role_choice"] = session.get("role_choice")
            return jsonify({"success": False, "message": f"Aktion '{action_name}' nicht möglich (keine Spieler-ID).", **temp_cvd }), 403
    
    if payload_key:
        req_data = request.get_json()
        if req_data is None and payload_key != "ready_status": 
             return jsonify({"success": False, "message": "Keine JSON-Daten im Request-Body."}), 400
        val_from_req = req_data.get(payload_value_from_request or payload_key) if req_data else None
        if payload_key == "ready_status":
             if not isinstance(val_from_req, bool): return jsonify({"success": False, "message": "Ungültiger Wert für ready_status (muss boolean sein).)"}), 400
        elif val_from_req is None and payload_key != "force_server_reset": # force_server_reset braucht keinen Payload-Wert
            return jsonify({"success": False, "message": f"Fehlender Wert für '{payload_key}' im Request-Body."}), 400
        if val_from_req is not None or payload_key != "force_server_reset": # Nur setzen, wenn Wert da ist oder nicht force_server_reset
            action_payload[payload_key] = val_from_req
    
    success_sent = send_message_to_server(action_payload) 
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None 
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT
        response_data = client_view_data.copy(); 
        response_data["action_send_success"] = success_sent 
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

# Spezifische Routen, die handle_generic_action verwenden
@app.route('/confirm_lobby_join', methods=['POST'])
def confirm_lobby_join_route(): 
    return handle_generic_action("CONFIRM_LOBBY_JOIN")

@app.route('/set_ready', methods=['POST'])
def set_ready_route(): 
    return handle_generic_action("SET_READY", "ready_status", "ready_status")

@app.route('/complete_task', methods=['POST'])
def complete_task_route(): 
    return handle_generic_action("TASK_COMPLETE")

@app.route('/catch_hider', methods=['POST'])
def catch_hider_route(): 
    return handle_generic_action("CATCH_HIDER", "hider_id_to_catch", "hider_id_to_catch")

@app.route('/use_powerup', methods=['POST'])
def use_powerup_route(): 
    return handle_generic_action("USE_POWERUP", "powerup_id", "powerup_id")

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    """ 
    Ermöglicht dem Spieler, das Spiel zu verlassen und zum Join-Bildschirm zurückzukehren.
    Setzt den Client-Zustand zurück.
    """
    action_sent_successfully = False
    message_to_user = "Versuche, Spiel zu verlassen..."
    
    original_player_id_if_any = None
    with client_data_lock:
        original_player_id_if_any = client_view_data.get("player_id")
    
    with client_data_lock:
        client_view_data.update({
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False, "player_status": "active",
            "current_task": None, "hider_leaderboard": [], "hider_locations": {},
            "power_ups_available": [], "game_message": None, "error_message": None, 
            "join_error": None, "hider_location_update_imminent": False,
            "early_end_requests_count": 0, "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False,
            "task_skips_available": 0 
        })
        
        if "game_state" in client_view_data and client_view_data["game_state"] is not None:
            client_view_data["game_state"]["status"] = GAME_STATE_LOBBY 
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None 

    if original_player_id_if_any and send_message_to_server({"action": "LEAVE_GAME_AND_GO_TO_JOIN"}):
        action_sent_successfully = True
        message_to_user = "Anfrage zum Verlassen an Server gesendet. Du bist nun ausgeloggt."
        session.pop("nickname", None) 
        session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user 
    elif original_player_id_if_any: 
        message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden. Clientseitig zurückgesetzt. Prüfe Verbindung."
        with client_data_lock: client_view_data["error_message"] = message_to_user
    else: 
        action_sent_successfully = True 
        message_to_user = "Client zurückgesetzt zum Join-Screen (war nicht aktiv im Spiel)."
        session.pop("nickname", None) 
        session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user


    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT
        response_payload = client_view_data.copy()
        response_payload["leave_request_info"] = {
            "sent_successfully": action_sent_successfully,
            "message": message_to_user
        }
        response_payload["session_nickname"] = session.get("nickname") 
        response_payload["session_role_choice"] = session.get("role_choice")
    return jsonify(response_payload)

@app.route('/request_early_round_end_action', methods=['POST'])
def request_early_round_end_action_route():
    """ Route für die Anfrage eines frühen Rundenendes. """
    return handle_generic_action("REQUEST_EARLY_ROUND_END")

@app.route('/skip_task', methods=['POST']) 
def skip_task_route():
    """ Route für die Aufgaben-Skip-Funktion des Hiders. """
    return handle_generic_action("SKIP_TASK")

@app.route('/force_server_reset_from_ui', methods=['POST']) # NEUE ROUTE FÜR SERVER-RESET
def force_server_reset_route():
    """ Route für den erzwungenen Server-Reset durch einen Client (UI-Button). """
    # Diese Aktion erfordert keine player_id, da sie global wirken soll.
    # Es wird keine payload_key oder payload_value_from_request benötigt.
    return handle_generic_action("FORCE_SERVER_RESET_FROM_CLIENT", requires_player_id=False)


if __name__ == '__main__':
    print("Hide and Seek Client startet...")
    with client_data_lock: 
        client_view_data["game_state"]["status"] = "disconnected"
        client_view_data["game_state"]["status_display"] = "Initialisiere Client Flask-App..."
        client_view_data["is_socket_connected_to_server"] = False
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT 
    
    threading.Thread(target=network_communication_thread, daemon=True).start()
    print("CLIENT: Network Communication Thread gestartet.")
    
    print(f"Flask Webserver startet auf http://0.0.0.0:{FLASK_PORT}")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
