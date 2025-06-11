# client.py
import socket
import json
import time
import threading
import subprocess
import random
import traceback # Importiert für detailliertere Fehlermeldungen in Threads
from flask import Flask, jsonify, request, send_from_directory, session

# Standardwerte, können zur Laufzeit geändert werden
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65432
FLASK_PORT = 5000
STATIC_FOLDER = 'static'

# Das globale Dictionary, das die Daten für die UI bereithält
client_view_data = {
    "player_id": None,
    "player_name": None,
    "role": None,
    "location": None,
    "confirmed_for_lobby": False,
    "player_is_ready": False,
    "player_status": "active", # active, caught, failed_task, failed_loc_update, offline
    "user_has_initiated_connection": False, # Flag, der steuert, ob der Client überhaupt eine Verbindung aufbauen soll.
    "is_socket_connected_to_server": False, # Status der direkten Socket-Verbindung zum Spielserver
    "game_state": {
        "status": "disconnected",
        "status_display": "Initialisiere Client...",
        "game_time_left": 0,
        "hider_wait_time_left": 0,
        "game_over_message": None
    },
    "lobby_players": {}, # Nur im Lobby-Status relevant
    "all_players_status": {}, # Immer relevant für Gesamtübersicht
    "current_task": None, # Für Hider
    "hider_leaderboard": [], # Für Hider und am Spielende
    "hider_locations": {}, # Für Seeker
    "game_message": None, # Allgemeine Nachrichten vom Server
    "error_message": None, # Allgemeine Fehlermeldungen vom Server
    "join_error": None, # Spezifische Fehlermeldung für den Join-Prozess, die zum Join-Screen zurückführt
    "prefill_nickname": f"Spieler{random.randint(100,999)}", # Vorschlag für Nickname
    "hider_location_update_imminent": False, # Für Hider-Warnung
    "early_end_requests_count": 0,
    "total_active_players_for_early_end": 0,
    "player_has_requested_early_end": False,
    "current_server_host": SERVER_HOST, # Aktuell konfigurierter Server-Host
    "current_server_port": SERVER_PORT, # Aktuell konfigurierter Server-Port
    "task_skips_available": 0, # Für Hider
    "offline_action_queue": [],  # Liste für {action_for_server: {...}, ui_message_on_cache: "..."}
    "is_processing_offline_queue": False, # Flag für UI-Feedback
    "pre_cached_tasks": [], # Für Aufgaben-Pre-Caching
}
client_data_lock = threading.Lock() # Lock für den sicheren Zugriff auf client_view_data
server_socket_global = None # Der globale Socket zum Spielserver

# Spielzustände (Konstanten zur besseren Lesbarkeit)
GAME_STATE_LOBBY = "lobby"
GAME_STATE_HIDER_WAIT = "hider_wait"
GAME_STATE_RUNNING = "running"
GAME_STATE_HIDER_WINS = "hider_wins"
GAME_STATE_SEEKER_WINS = "seeker_wins"


app = Flask(__name__, static_folder=STATIC_FOLDER, static_url_path='')
app.secret_key = "dein_super_geheimer_und_einzigartiger_schluessel_hier_aendern_DRINGEND"

def show_termux_notification(title, content, notification_id=None):
    try:
        command = ['termux-notification', '--title', title, '--content', content]
        if notification_id: command.extend(['--id', str(notification_id)])
        command.extend(['--vibrate', '500'])
        subprocess.run(command, check=False)
    except FileNotFoundError: pass
    except Exception as e: print(f"CLIENT NOTIFICATION ERROR: {e}")

def send_message_to_server(data):
    global server_socket_global
    action_sent = data.get('action', 'NO_ACTION_SPECIFIED')
    socket_is_currently_connected = False
    current_socket_ref = server_socket_global # Kopiere Referenz für den Fall, dass sie global geändert wird

    with client_data_lock:
        socket_is_currently_connected = client_view_data["is_socket_connected_to_server"]

    if current_socket_ref and socket_is_currently_connected:
        try:
            print(f"CLIENT SEND: Sende Aktion '{action_sent}' an Server. Socket: {current_socket_ref}, Connected-Flag: {socket_is_currently_connected}")
            current_socket_ref.sendall(json.dumps(data).encode('utf-8') + b'\n')
            return True
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"CLIENT SEND (ERROR): Senden von '{action_sent}' fehlgeschlagen, Verbindung verloren: {e}. Socket: {current_socket_ref}")
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Verbindung zum Server verloren (Senden)."
                client_view_data["error_message"] = "Verbindung zum Server verloren."
        except Exception as e:
            print(f"CLIENT SEND (UNEXPECTED ERROR): Senden von '{action_sent}' fehlgeschlagen: {e}. Socket: {current_socket_ref}")
            traceback.print_exc()
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["error_message"] = "Unerwarteter Fehler beim Senden an Server."
    else:
        with client_data_lock:
            client_view_data["is_socket_connected_to_server"] = False # Sicherstellen, dass es False ist
            if not client_view_data.get("error_message"):
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
        print(f"CLIENT SEND (NO CONN): Aktion '{action_sent}' nicht gesendet. Socket: {current_socket_ref}, Connected-Flag: {socket_is_currently_connected}")
    return False

def process_offline_queue():
    print("CLIENT OFFLINE QUEUE: Thread gestartet.")
    queue_to_process = []
    with client_data_lock:
        if not client_view_data.get("offline_action_queue") or client_view_data.get("is_processing_offline_queue"):
            if client_view_data.get("is_processing_offline_queue"):
                 print("CLIENT OFFLINE QUEUE: Bereits am Verarbeiten, Thread beendet sich.")
            else:
                 print("CLIENT OFFLINE QUEUE: Queue leer oder nicht initialisiert, Thread beendet sich.")
            return

        client_view_data["is_processing_offline_queue"] = True
        # Kopiere die Queue, um sie außerhalb des Locks zu verarbeiten
        queue_to_process = list(client_view_data["offline_action_queue"])
        client_view_data["offline_action_queue"].clear()

    print(f"CLIENT OFFLINE QUEUE: Starte Verarbeitung von {len(queue_to_process)} Offline-Aktionen.")
    successfully_sent_actions_count = 0
    failed_actions_to_re_queue = []

    for offline_action_package in queue_to_process:
        action_to_send_to_server = offline_action_package.get("action_for_server")
        if action_to_send_to_server:
            action_name_log = action_to_send_to_server.get('action', 'UNKNOWN_OFFLINE_ACTION')
            print(f"CLIENT OFFLINE QUEUE: Versuche Aktion zu senden: {action_name_log}")
            if send_message_to_server(action_to_send_to_server):
                print(f"CLIENT OFFLINE QUEUE: Aktion '{action_name_log}' erfolgreich an Server gesendet.")
                successfully_sent_actions_count += 1
            else:
                print(f"CLIENT OFFLINE QUEUE: Senden der Aktion '{action_name_log}' fehlgeschlagen.")
                failed_actions_to_re_queue.append(offline_action_package)
                with client_data_lock:
                    if not client_view_data["is_socket_connected_to_server"]:
                        print("CLIENT OFFLINE QUEUE: Verbindung während Verarbeitung verloren. Breche ab.")
                        break
        else:
            print(f"CLIENT ERROR: Ungültiges Offline-Aktions-Paket: {offline_action_package}")

    with client_data_lock:
        # Füge fehlgeschlagene Aktionen wieder vorne an die (möglicherweise inzwischen neu gefüllte) Queue an
        client_view_data["offline_action_queue"] = failed_actions_to_re_queue + client_view_data["offline_action_queue"]
        client_view_data["is_processing_offline_queue"] = False
        remaining_count = len(client_view_data["offline_action_queue"])
        print(f"CLIENT OFFLINE QUEUE: Verarbeitung beendet. {successfully_sent_actions_count} gesendet. {remaining_count} verbleiben.")

        if not client_view_data["offline_action_queue"] and successfully_sent_actions_count > 0 :
             client_view_data["game_message"] = "Alle Offline-Aktionen erfolgreich synchronisiert."
        elif failed_actions_to_re_queue: # Es gab Fehler beim Senden dieser Runde
             client_view_data["error_message"] = f"{len(failed_actions_to_re_queue)} Offline-Aktion(en) konnte(n) nicht synchronisiert werden. Erneuter Versuch bei nächster Gelegenheit."
        elif successfully_sent_actions_count == 0 and not queue_to_process : # Keine Aktionen in der initialen Queue
            pass # Nichts zu tun, keine Nachricht
        else: # Keine Fehler, aber auch nichts gesendet oder Queue war initial leer
            client_view_data["game_message"] = None

def network_communication_thread():
    global server_socket_global, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = ""
    print("CLIENT NET: Netzwerk-Kommunikations-Thread gestartet.")

    while True:
        user_wants_to_connect = False
        with client_data_lock:
            user_wants_to_connect = client_view_data.get("user_has_initiated_connection", False)
        
        if not user_wants_to_connect:
            with client_data_lock:
                if client_view_data["is_socket_connected_to_server"] or server_socket_global: # Nur Log wenn nötig
                    print("CLIENT NET: Benutzer will keine Verbindung, schließe ggf. Socket.")
                if client_view_data["is_socket_connected_to_server"]:
                    client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Bereit zum Verbinden mit einem Server."
            
            if server_socket_global:
                try: server_socket_global.close()
                except: pass
                server_socket_global = None
            time.sleep(1); continue

        socket_should_be_connected = False
        current_host_to_connect = SERVER_HOST # Default
        current_port_to_connect = SERVER_PORT # Default
        with client_data_lock:
            socket_should_be_connected = client_view_data["is_socket_connected_to_server"]
            current_host_to_connect = client_view_data["current_server_host"]
            current_port_to_connect = client_view_data["current_server_port"]

        if not socket_should_be_connected:
            print(f"CLIENT NET: Socket nicht verbunden oder soll neu verbunden werden. Aktueller Host: {current_host_to_connect}:{current_port_to_connect}")
            # Vorherigen Socket schließen, falls vorhanden und nicht schon durch `user_wants_to_connect=False` Block passiert
            if server_socket_global:
                print(f"CLIENT NET: Schließe alten globalen Socket {server_socket_global} vor Neuverbindung.")
                try: server_socket_global.close()
                except Exception as e_close_old: print(f"CLIENT NET WARN: Fehler beim Schließen des alten Sockets: {e_close_old}")
                server_socket_global = None

            try:
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"):
                         client_view_data["game_state"]["status_display"] = f"Verbinde mit Spielserver {current_host_to_connect}:{current_port_to_connect}..."
                
                print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}")
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5)
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                print(f"CLIENT NET: Erfolgreich verbunden mit {current_host_to_connect}:{current_port_to_connect}. Socket: {temp_sock}")
                temp_sock.settimeout(None)
                server_socket_global = temp_sock # Globalen Socket setzen
                buffer = ""

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True # WICHTIG: Sofort setzen!
                    client_view_data["error_message"] = None
                    client_view_data["game_state"]["status_display"] = "Verbunden. Initialisiere Sitzung..."

                    # MODIFIZIERT: Offline-Queue Verarbeitung hier zentralisieren
                    if client_view_data.get("offline_action_queue") and \
                       not client_view_data.get("is_processing_offline_queue"):
                        print("CLIENT NET: Verbindung hergestellt, starte Verarbeitung der Offline-Queue...")
                        threading.Thread(target=process_offline_queue, daemon=True).start()
                    
                    # REJOIN LOGIC
                    if client_view_data.get("player_id") and client_view_data.get("player_name"):
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": client_view_data["player_id"],
                            "name": client_view_data["player_name"]
                        }
                        try:
                            # Direkt senden, da send_message_to_server auf client_view_data basiert, das gerade gelockt ist.
                            # und wir hier den Socket direkt haben.
                            server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                            client_view_data["game_state"]["status_display"] = f"Sende Rejoin-Anfrage als {client_view_data['player_name']}..."
                            print(f"CLIENT NET: REJOIN_GAME für {client_view_data['player_name']} ({client_view_data['player_id']}) gesendet.")
                        except Exception as e_rejoin:
                            print(f"CLIENT NET: Senden von REJOIN_GAME fehlgeschlagen: {e_rejoin}. Versuche Neuverbindung.")
                            traceback.print_exc()
                            client_view_data["is_socket_connected_to_server"] = False
                            client_view_data["error_message"] = "Senden der Rejoin-Anfrage fehlgeschlagen."
                            # server_socket_global wird im nächsten Durchlauf geschlossen, wenn is_socket_connected_to_server false ist.
                    else:
                        if client_view_data["game_state"].get("status") == "disconnected": # Nur wenn vorher getrennt
                             client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Spielbeitritt..."

            except socket.timeout:
                print(f"CLIENT NET: Timeout bei Verbindung zu {current_host_to_connect}:{current_port_to_connect}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung."
                time.sleep(3); continue
            except (ConnectionRefusedError, OSError) as e:
                print(f"CLIENT NET: Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__} - {e}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen."
                time.sleep(3); continue
            except Exception as e_conn:
                print(f"CLIENT NET (CONNECT ERROR - UNEXPECTED): {e_conn}")
                traceback.print_exc()
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Unbekannter Verbindungsfehler: {type(e_conn).__name__}"
                time.sleep(3); continue
        
        # Erneute Prüfung des Verbindungsstatus nach dem Verbindungsblock
        with client_data_lock:
            if not client_view_data["is_socket_connected_to_server"]:
                print("CLIENT NET: Socket nach Verbindungsversuch immer noch als 'nicht verbunden' markiert. Schließe ggf. Socket.")
                if server_socket_global:
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None
                time.sleep(0.1) # Kurze Pause vor erneutem Versuch im Hauptloop
                continue

        # --- Nachrichten-Empfangs-Logik ---
        try:
            if not server_socket_global:
                print("CLIENT NET (RECEIVE PRE-CHECK): server_socket_global ist None, obwohl es verbunden sein sollte.")
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                time.sleep(0.1); continue

            # print("CLIENT NET: Warte auf Daten vom Server...") # Kann sehr gesprächig sein
            data_chunk = server_socket_global.recv(8192)
            if not data_chunk:
                print("CLIENT NET: Server hat Verbindung getrennt (leere Daten erhalten).")
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False
                    client_view_data["game_state"]["status_display"] = "Server hat Verbindung getrennt."
                    client_view_data["error_message"] = "Server hat die Verbindung beendet."
                continue
            buffer += data_chunk.decode('utf-8')

            while '\n' in buffer:
                message_str, buffer = buffer.split('\n', 1)
                if not message_str.strip(): continue
                message = json.loads(message_str)
                # print(f"CLIENT NET: Nachricht vom Server empfangen: {message.get('type', 'NO_TYPE')}") # Zu gesprächig

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True # Nachricht erhalten -> Verbindung ist aktiv
                    msg_type = message.get("type")

                    if msg_type == "game_update":
                        if "player_id" in message and message["player_id"] is None:
                            if client_view_data["player_id"] is not None:
                                print(f"CLIENT: Server hat player_id=None gesendet. Resette Client-Spielerdaten.")
                            client_view_data["player_id"] = None; client_view_data["player_name"] = None
                            client_view_data["role"] = None; client_view_data["confirmed_for_lobby"] = False
                            client_view_data["player_is_ready"] = False
                            client_view_data["offline_action_queue"].clear()
                            client_view_data["is_processing_offline_queue"] = False # Reset flag

                            if message.get("join_error"): client_view_data["join_error"] = message["join_error"]
                            if message.get("error_message"): client_view_data["error_message"] = message["error_message"]
                        elif "player_id" in message and message["player_id"] is not None:
                            if client_view_data["player_id"] != message["player_id"]:
                                print(f"CLIENT: Eigene Player ID vom Server erhalten/geändert zu: {message['player_id']}")
                            client_view_data["player_id"] = message["player_id"]
                            client_view_data["join_error"] = None

                        update_keys = [
                            "player_name", "role", "confirmed_for_lobby", "player_is_ready",
                            "player_status", "location", "game_state", "lobby_players",
                            "all_players_status", "current_task", "hider_leaderboard",
                            "hider_locations", "hider_location_update_imminent",
                            "early_end_requests_count", "total_active_players_for_early_end",
                            "player_has_requested_early_end", "task_skips_available", "pre_cached_tasks"
                        ]
                        for key in update_keys:
                            if key in message: client_view_data[key] = message[key]
                        
                        # Nach einem erfolgreichen Game-Update, prüfe erneut Offline-Queue
                        if client_view_data.get("player_id") and \
                           client_view_data.get("offline_action_queue") and \
                           not client_view_data.get("is_processing_offline_queue"):
                            print("CLIENT NET: Game Update erhalten, starte Verarbeitung der Offline-Queue (falls noch nötig)...")
                            threading.Thread(target=process_offline_queue, daemon=True).start()

                    elif msg_type == "server_text_notification": #... (Rest bleibt gleich)
                        game_msg_text = message.get("message", "Server Nachricht")
                        show_termux_notification(title="Hide and Seek Info", content=game_msg_text, notification_id="server_info")
                        client_view_data["game_message"] = game_msg_text
                    elif msg_type == "game_event": #... (Rest bleibt gleich)
                        event_name = message.get("event_name")
                        if event_name == "hider_location_update_due":
                            show_termux_notification(title="Hide and Seek: ACHTUNG!", content="Hider: Standort bald benötigt! Öffne die App.", notification_id="hider_warn")
                            client_view_data["hider_location_update_imminent"] = True
                        elif event_name == "seeker_locations_updated":
                             show_termux_notification(title="Hide and Seek", content="Seeker: Hider-Standorte aktualisiert!", notification_id="seeker_update" )
                        elif event_name == "game_started":
                            show_termux_notification(title="Hide and Seek", content="Das Spiel hat begonnen!", notification_id="game_start")
                    elif msg_type == "error": #... (Rest bleibt gleich)
                        error_text = message.get("message", "Unbekannter Fehler vom Server")
                        client_view_data["error_message"] = error_text
                        critical_errors = [
                            "Spiel läuft bereits", "Spiel voll", "Nicht authentifiziert",
                            "Bitte neu beitreten", "Du bist nicht mehr Teil des aktuellen Spiels",
                            "Server wurde von einem Spieler zurückgesetzt", "Rejoin fehlgeschlagen",
                            "Name", "bereits vergeben"
                        ]
                        if any(crit_err in error_text for crit_err in critical_errors):
                            client_view_data["join_error"] = error_text
                            if client_view_data["player_id"] is not None:
                                print(f"CLIENT: Kritischer Fehler vom Server '{error_text}'. Resette player_id.")
                                client_view_data["player_id"] = None; client_view_data["player_name"] = None
                                client_view_data["role"] = None; client_view_data["confirmed_for_lobby"] = False
                                client_view_data["player_is_ready"] = False
                                client_view_data["offline_action_queue"].clear()
                                client_view_data["is_processing_offline_queue"] = False
                    elif msg_type == "acknowledgement": #... (Rest bleibt gleich)
                        ack_message = message.get("message", "Aktion bestätigt.")
                        client_view_data["game_message"] = ack_message

        except json.JSONDecodeError: #... (Rest bleibt gleich)
            print(f"CLIENT NET (JSON DECODE ERROR): Buffer war '{buffer[:200]}...'")
            with client_data_lock: client_view_data["error_message"] = "Fehlerhafte Daten vom Server empfangen."
            buffer = "" 
        except (ConnectionResetError, BrokenPipeError, OSError) as e_recv: #... (Rest bleibt gleich)
            print(f"CLIENT NET (RECEIVE ERROR - COMM): Verbindung getrennt (Empfang): {e_recv}")
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = f"Verbindung getrennt (Empfang): {type(e_recv).__name__}"
        except Exception as e_recv_main: #... (Rest bleibt gleich)
            print(f"CLIENT NET (RECEIVE ERROR - UNEXPECTED): Unerwarteter Fehler beim Empfang: {e_recv_main}")
            traceback.print_exc()
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["error_message"] = "Interner Client-Fehler beim Empfang von Serverdaten."
        finally: #... (Rest bleibt gleich)
            is_still_connected_after_loop = False
            with client_data_lock:
                is_still_connected_after_loop = client_view_data["is_socket_connected_to_server"]

            if not is_still_connected_after_loop:
                if server_socket_global:
                    print(f"CLIENT NET (FINALLY): Verbindung verloren oder Fehler. Schließe Socket {server_socket_global}.")
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None
                time.sleep(1)


# --- Flask Webserver Routen ---
@app.route('/')
def index_page_route(): return send_from_directory(app.static_folder, 'index.html')
@app.route('/manifest.json')
def manifest_route(): return send_from_directory(app.static_folder, 'manifest.json')
@app.route('/sw.js')
def service_worker_route(): return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')
@app.route('/offline.html')
def offline_route(): return send_from_directory(app.static_folder, 'offline.html')
@app.route('/icons/<path:filename>')
def icons_route(filename): return send_from_directory(app.static_folder, f'icons/{filename}')

@app.route('/status', methods=['GET'])
def get_status():
    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT
        data_to_send = client_view_data.copy()
        data_to_send["session_nickname"] = session.get("nickname")
        data_to_send["session_role_choice"] = session.get("role_choice")
        return jsonify(data_to_send)

@app.route('/connect_to_server', methods=['POST'])
def connect_to_server_route():
    global SERVER_HOST, SERVER_PORT, server_socket_global
    data = request.get_json()
    if not data or 'server_address' not in data:
        return jsonify({"success": False, "message": "Server-Adresse fehlt."}), 400
    server_address = data['server_address'].strip()
    if not server_address:
        return jsonify({"success": False, "message": "Server-Adresse darf nicht leer sein."}), 400
    print(f"CLIENT FLASK: /connect_to_server. Neue Adresse: {server_address}")

    try:
        if ':' in server_address: host, port_str = server_address.rsplit(':', 1); port = int(port_str)
        else: host = server_address; port = 65432 
    except ValueError: return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed = False
    with client_data_lock:
        if SERVER_HOST != host or SERVER_PORT != port:
            print(f"CLIENT FLASK: Serverdetails geändert von {SERVER_HOST}:{SERVER_PORT} zu {host}:{port}")
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True
        
        client_view_data.update({
            "user_has_initiated_connection": True, 
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False,
            "join_error": None, "error_message": None, "game_message": "Verbinde mit " + server_address,
            "is_socket_connected_to_server": False # Signal an Netzwerk-Thread: Neu verbinden
        })
        print(f"CLIENT FLASK: Flags für Netzwerk-Thread gesetzt: user_has_initiated_connection=True, is_socket_connected_to_server=False")


    if server_details_changed and server_socket_global:
        print(f"CLIENT FLASK: Serverdetails geändert, schließe alten Socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e: print(f"CLIENT FLASK WARN: Fehler beim Schließen des alten Sockets nach Adressänderung: {e}")
        finally: server_socket_global = None # Sicherstellen, dass es None ist

    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)


@app.route('/register_player_details', methods=['POST'])
def register_player_details_route():
    data = request.get_json() #... (Rest bleibt gleich)
    nickname, role_choice = data.get('nickname'), data.get('role')
    if not nickname or not role_choice: return jsonify({"success": False, "message": "Name oder Rolle fehlt."}), 400
    session["nickname"], session["role_choice"] = nickname, role_choice
    with client_data_lock: client_view_data["player_name"] = nickname
    socket_conn_ok = False
    with client_data_lock: socket_conn_ok = client_view_data.get("is_socket_connected_to_server", False)
    if socket_conn_ok:
        if not send_message_to_server({"action": "JOIN_GAME", "name": nickname, "role_preference": role_choice}):
            with client_data_lock: client_view_data["join_error"] = "Senden der Join-Anfrage fehlgeschlagen."
    else:
        with client_data_lock: client_view_data["join_error"] = "Nicht mit Server verbunden. Bitte zuerst verbinden."
    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/update_location_from_browser', methods=['POST'])
def update_location_from_browser(): #... (Rest bleibt gleich)
    data = request.get_json()
    if not data: return jsonify({"success": False, "message": "Keine Daten."}), 400
    lat, lon, accuracy = data.get('lat'), data.get('lon'), data.get('accuracy')
    if lat is None or lon is None or accuracy is None: return jsonify({"success": False, "message": "Unvollständige Standortdaten."}), 400
    player_id_local, game_status_local, socket_ok_local = None, None, False
    with client_data_lock:
        player_id_local = client_view_data.get("player_id")
        game_status_local = client_view_data.get("game_state", {}).get("status")
        socket_ok_local = client_view_data.get("is_socket_connected_to_server", False)
    game_can_receive_loc = game_status_local in [GAME_STATE_LOBBY, GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]
    if player_id_local and game_can_receive_loc and socket_ok_local:
        send_success = send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy})
        if send_success:
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy]
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID bekannt. Bitte zuerst beitreten."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    else: return jsonify({"success": False, "message": "Keine aktive Socket-Verbindung zum Spielserver."}), 503

def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True): #... (Rest bleibt gleich)
    action_payload = {"action": action_name}; player_id_for_action = None
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
        if req_data is None and payload_key != "ready_status": return jsonify({"success": False, "message": "Keine JSON-Daten im Request."}), 400
        val_from_req = req_data.get(payload_value_from_request or payload_key) if req_data else None
        if payload_key == "ready_status":
             if not isinstance(val_from_req, bool): return jsonify({"success": False, "message": "Ungültiger Wert für ready_status (muss boolean sein)."}), 400
        elif val_from_req is None and payload_key != "force_server_reset_from_ui":
            return jsonify({"success": False, "message": f"Fehlender Wert für '{payload_key}' in Request-Daten."}), 400
        if val_from_req is not None or payload_key == "force_server_reset_from_ui":
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

@app.route('/set_ready', methods=['POST'])
def set_ready_route(): return handle_generic_action("SET_READY", "ready_status", "ready_status")
@app.route('/complete_task', methods=['POST'])
def complete_task_route(): #... (Rest bleibt gleich)
    player_id_local, current_task_local, socket_ok_local, is_hider_active = None, None, False, False
    with client_data_lock:
        player_id_local = client_view_data.get("player_id")
        current_task_local = client_view_data.get("current_task")
        socket_ok_local = client_view_data.get("is_socket_connected_to_server", False)
        is_hider_active = (client_view_data.get("role") == "hider" and client_view_data.get("player_status") == "active")
    if not player_id_local or not is_hider_active:
        with client_data_lock: temp_cvd = client_view_data.copy()
        temp_cvd["session_nickname"] = session.get("nickname"); temp_cvd["session_role_choice"] = session.get("role_choice")
        return jsonify({"success": False, "message": "Aktion nicht möglich (kein aktiver Hider oder keine Spieler-ID).", **temp_cvd}), 403
    if not current_task_local or not current_task_local.get("id"):
        with client_data_lock: temp_cvd = client_view_data.copy()
        temp_cvd["session_nickname"] = session.get("nickname"); temp_cvd["session_role_choice"] = session.get("role_choice")
        return jsonify({"success": False, "message": "Keine aktive Aufgabe zum Erledigen vorhanden.", **temp_cvd}), 400
    task_id_to_complete = current_task_local["id"]
    task_description_for_ui_msg = current_task_local.get("description", "Unbekannte Aufgabe")
    if socket_ok_local:
        action_payload_for_server = {"action": "TASK_COMPLETE", "task_id": task_id_to_complete}
        success_sent = send_message_to_server(action_payload_for_server)
        with client_data_lock:
            if success_sent: client_view_data["error_message"] = None
            response_data = client_view_data.copy()
            response_data["action_send_success"] = success_sent
            response_data["session_nickname"] = session.get("nickname"); response_data["session_role_choice"] = session.get("role_choice")
        return jsonify(response_data)
    else:
        offline_action_for_server = {"action": "TASK_COMPLETE_OFFLINE", "task_id": task_id_to_complete, "completed_at_timestamp_offline": time.time()}
        offline_package = {"action_for_server": offline_action_for_server, "ui_message_on_cache": f"Aufgabe '{task_description_for_ui_msg}' offline als erledigt markiert. Wird bei Verbindung gesendet."}
        with client_data_lock:
            client_view_data["offline_action_queue"].append(offline_package)
            client_view_data["game_message"] = offline_package["ui_message_on_cache"]
            client_view_data["current_task"] = None
            response_data = client_view_data.copy()
            response_data["action_send_success"] = True
            response_data["session_nickname"] = session.get("nickname"); response_data["session_role_choice"] = session.get("role_choice")
        print(f"CLIENT: Aufgabe '{task_description_for_ui_msg}' (ID: {task_id_to_complete}) offline erledigt, zur Queue hinzugefügt.")
        return jsonify(response_data)
@app.route('/catch_hider', methods=['POST'])
def catch_hider_route(): return handle_generic_action("CATCH_HIDER", "hider_id_to_catch", "hider_id_to_catch")
@app.route('/request_early_round_end_action', methods=['POST'])
def request_early_round_end_action_route(): return handle_generic_action("REQUEST_EARLY_ROUND_END")
@app.route('/skip_task', methods=['POST'])
def skip_task_route(): return handle_generic_action("SKIP_TASK")

@app.route('/force_server_reset_from_ui', methods=['POST'])
def force_server_reset_route():
    global SERVER_HOST, SERVER_PORT, server_socket_global
    data = request.get_json()
    if not data or 'server_address' not in data:
        return jsonify({"success": False, "message": "Server-Adresse für Reset fehlt."}), 400
    server_address = data['server_address'].strip()
    if not server_address:
        return jsonify({"success": False, "message": "Server-Adresse darf nicht leer sein."}), 400
    print(f"CLIENT FLASK: /force_server_reset_from_ui. Adresse: {server_address}")

    try:
        if ':' in server_address: host, port_str = server_address.rsplit(':', 1); port = int(port_str)
        else: host = server_address; port = 65432
    except ValueError: return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed = False
    with client_data_lock:
        if SERVER_HOST != host or SERVER_PORT != port:
            print(f"CLIENT FLASK (Reset): Serverdetails geändert von {SERVER_HOST}:{SERVER_PORT} zu {host}:{port}")
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True
        
        client_view_data["user_has_initiated_connection"] = True
        client_view_data["is_socket_connected_to_server"] = False # Signalisiert dem Netzwerk-Thread, neu zu verbinden
        # UI-Nachricht wird später vom Hinzufügen zur Queue gesetzt
        print(f"CLIENT FLASK (Reset): Flags für Netzwerk-Thread gesetzt: user_initiated_conn=True, is_socket_conn=False")


    if server_details_changed and server_socket_global:
        print(f"CLIENT FLASK (Reset): Serverdetails geändert, schließe alten Socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e: print(f"CLIENT FLASK WARN (Reset): Fehler beim Schließen des alten Sockets: {e}")
        finally: server_socket_global = None

    with client_data_lock:
        reset_action = {
            "action_for_server": {"action": "FORCE_SERVER_RESET_FROM_CLIENT"},
            "ui_message_on_cache": f"Reset-Befehl für {server_address} in Warteschlange. Wird bei nächster Verbindung gesendet."
        }
        client_view_data["offline_action_queue"].clear() 
        client_view_data["offline_action_queue"].append(reset_action)
        client_view_data["game_message"] = reset_action["ui_message_on_cache"] # UI Feedback
        # Wichtig: is_processing_offline_queue NICHT hier auf True setzen oder process_offline_queue starten.
        # Der network_communication_thread erledigt das.
        print("CLIENT FLASK (Reset): Reset-Aktion zur Offline-Queue hinzugefügt. Netzwerk-Thread wird Verarbeitung bei Verbindung starten.")

    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/return_to_registration', methods=['POST'])
def return_to_registration_route(): return handle_generic_action("RETURN_TO_REGISTRATION")
@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route(): #... (Rest bleibt gleich)
    action_sent_successfully = False; message_to_user = "Versuche, Spiel zu verlassen..."
    original_player_id_if_any = None
    with client_data_lock: original_player_id_if_any = client_view_data.get("player_id")
    with client_data_lock:
        client_view_data.update({
            "user_has_initiated_connection": False, 
            "player_id": None, "player_name": None, "role": None, 
            "confirmed_for_lobby": False, "player_is_ready": False, "player_status": "active",
            "current_task": None, "hider_leaderboard": [], "hider_locations": {},
            "game_message": None, "error_message": None, "join_error": None, 
            "hider_location_update_imminent": False,
            "early_end_requests_count": 0, "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False, "task_skips_available": 0,
            "offline_action_queue": [], "is_processing_offline_queue": False, "pre_cached_tasks": [],
        })
        if "game_state" in client_view_data and client_view_data["game_state"] is not None:
            client_view_data["game_state"]["status"] = GAME_STATE_LOBBY
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None
        client_view_data["is_socket_connected_to_server"] = False
    if original_player_id_if_any and send_message_to_server({"action": "LEAVE_GAME_AND_GO_TO_JOIN"}):
        action_sent_successfully = True; message_to_user = "Anfrage zum Verlassen an Server gesendet."
        session.pop("nickname", None); session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user
    elif original_player_id_if_any:
        message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden. Clientseitig zurückgesetzt."
        with client_data_lock: client_view_data["error_message"] = message_to_user
    else:
        action_sent_successfully = True; message_to_user = "Client zurückgesetzt (war nicht aktiv im Spiel)."
        session.pop("nickname", None); session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user
    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT
        response_payload = client_view_data.copy()
        response_payload["leave_request_info"] = {"sent_successfully": action_sent_successfully, "message": message_to_user}
        response_payload["session_nickname"] = session.get("nickname")
        response_payload["session_role_choice"] = session.get("role_choice")
    return jsonify(response_payload)


if __name__ == '__main__':
    print("CLIENT: Starte Netzwerk-Kommunikations-Thread...")
    threading.Thread(target=network_communication_thread, daemon=True).start()
    
    print(f"CLIENT: Starte Flask-App auf Port {FLASK_PORT}...")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
