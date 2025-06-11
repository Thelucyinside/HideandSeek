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
    "player_status": "active", # active, caught, failed_task, failed_loc_update, offline (NEU)
    "user_has_initiated_connection": False, # NEU: Flag, der steuert, ob der Client überhaupt eine Verbindung aufbauen soll.
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
    "offline_action_queue": [],  # NEU: Liste für {action_for_server: {...}, ui_message_on_cache: "..."}
    "is_processing_offline_queue": False, # NEU: Flag für UI-Feedback
    "pre_cached_tasks": [], # NEU: Für Aufgaben-Pre-Caching
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
# ACHTUNG: Diesen Secret Key unbedingt ändern, wenn die App produktiv genutzt wird!
app.secret_key = "dein_super_geheimer_und_einzigartiger_schluessel_hier_aendern_DRINGEND_PYTHONANYWHERE"

def show_termux_notification(title, content, notification_id=None):
    """Zeigt eine Termux-Benachrichtigung an, falls Termux installiert ist."""
    try:
        command = ['termux-notification', '--title', title, '--content', content]
        if notification_id: command.extend(['--id', str(notification_id)])
        command.extend(['--vibrate', '500']) 
        subprocess.run(command, check=False) 
    except FileNotFoundError:
        pass 
    except Exception as e:
        print(f"CLIENT NOTIFICATION ERROR: {e}")

def send_message_to_server(data):
    """Sendet eine JSON-Nachricht an den globalen Spielserver-Socket."""
    global server_socket_global
    action_sent = data.get('action', 'NO_ACTION_SPECIFIED')
    socket_is_currently_connected = False
    with client_data_lock: 
        socket_is_currently_connected = client_view_data["is_socket_connected_to_server"]
    
    print(f"CLIENT SEND: Attempting to send action '{action_sent}'. Socket global: {'Exists' if server_socket_global else 'None'}, Connected-Flag: {socket_is_currently_connected}, Socket Obj: {server_socket_global}")

    if server_socket_global and socket_is_currently_connected:
        try:
            server_socket_global.sendall(json.dumps(data).encode('utf-8') + b'\n')
            print(f"CLIENT SEND: Action '{action_sent}' sent successfully.")
            return True
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"CLIENT SEND (ERROR): Senden von '{action_sent}' fehlgeschlagen, Verbindung verloren: {e}.")
            with client_data_lock: 
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Verbindung zum Server verloren (Senden)."
                client_view_data["error_message"] = "Verbindung zum Server verloren."
        except Exception as e:
            print(f"CLIENT SEND (UNEXPECTED ERROR): Senden von '{action_sent}' fehlgeschlagen: {e}.")
            traceback.print_exc()
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["error_message"] = "Unerwarteter Fehler beim Senden an Server."
    else:
        print(f"CLIENT SEND (NO CONN): Aktion '{action_sent}' nicht gesendet. Socket: {server_socket_global}, Connected-Flag: {socket_is_currently_connected}")
        with client_data_lock:
            client_view_data["is_socket_connected_to_server"] = False
            if not client_view_data.get("error_message"): 
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
    return False

def process_offline_queue():
    """
    Verarbeitet die gesammelten Offline-Aktionen und sendet sie an den Server.
    Wird in einem separaten Thread ausgeführt.
    """
    with client_data_lock:
        if not client_view_data.get("offline_action_queue") or client_view_data.get("is_processing_offline_queue"):
            return
        client_view_data["is_processing_offline_queue"] = True
        queue_to_process = list(client_view_data["offline_action_queue"])
        client_view_data["offline_action_queue"].clear() 

    print(f"CLIENT OFFLINE QUEUE: Starte Verarbeitung von {len(queue_to_process)} Offline-Aktionen.")
    successfully_sent_actions_count = 0
    failed_actions_to_re_queue = []

    for offline_action_package in queue_to_process:
        action_to_send_to_server = offline_action_package.get("action_for_server")
        if action_to_send_to_server:
            print(f"CLIENT OFFLINE QUEUE: Versuche Aktion zu senden: {action_to_send_to_server.get('action')}")
            if send_message_to_server(action_to_send_to_server):
                print(f"CLIENT OFFLINE QUEUE: Offline-Aktion '{action_to_send_to_server.get('action')}' erfolgreich an Server gesendet.")
                successfully_sent_actions_count += 1
            else:
                print(f"CLIENT OFFLINE QUEUE: Senden der Offline-Aktion '{action_to_send_to_server.get('action')}' fehlgeschlagen.")
                failed_actions_to_re_queue.append(offline_action_package)
                with client_data_lock:
                    if not client_view_data["is_socket_connected_to_server"]:
                        print("CLIENT OFFLINE QUEUE: Verbindung während Verarbeitung verloren. Breche ab.")
                        break 
        else:
            print(f"CLIENT ERROR: Ungültiges Offline-Aktions-Paket: {offline_action_package}")

    with client_data_lock:
        client_view_data["offline_action_queue"] = failed_actions_to_re_queue + client_view_data["offline_action_queue"]
        client_view_data["is_processing_offline_queue"] = False
        if not client_view_data["offline_action_queue"] and successfully_sent_actions_count > 0 :
             client_view_data["game_message"] = "Alle Offline-Aktionen erfolgreich synchronisiert."
        elif failed_actions_to_re_queue:
             client_view_data["error_message"] = f"{len(failed_actions_to_re_queue)} Offline-Aktion(en) konnte(n) nicht synchronisiert werden."
        else: 
            client_view_data["game_message"] = None 
    print(f"CLIENT OFFLINE QUEUE: Verarbeitung beendet. {successfully_sent_actions_count} gesendet. {len(client_view_data['offline_action_queue'])} verbleiben.")


def network_communication_thread():
    """
    Dieser Thread verwaltet die persistente Socket-Verbindung zum Spielserver.
    """
    global server_socket_global, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = "" 
    print("CLIENT NET: Network communication thread started.")
    while True:
        user_wants_to_connect = False
        with client_data_lock:
            user_wants_to_connect = client_view_data.get("user_has_initiated_connection", False)
        
        if not user_wants_to_connect:
            # print("CLIENT NET: User does not want to connect. Thread idling.") # Kann zu verbose sein
            with client_data_lock:
                if client_view_data["is_socket_connected_to_server"]:
                    client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Bereit zum Verbinden mit einem Server."
            
            if server_socket_global:
                print(f"CLIENT NET: User does not want to connect, closing existing socket {server_socket_global}")
                try: server_socket_global.close()
                except: pass
                server_socket_global = None

            time.sleep(1) 
            continue 

        socket_should_be_connected = False # Lokale Variable für diesen Schleifendurchlauf
        with client_data_lock:
            socket_should_be_connected = client_view_data["is_socket_connected_to_server"]
            current_host_to_connect = client_view_data["current_server_host"]
            current_port_to_connect = client_view_data["current_server_port"]

        if not socket_should_be_connected:
            try:
                with client_data_lock: 
                    client_view_data["is_socket_connected_to_server"] = False 
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"):
                         client_view_data["game_state"]["status_display"] = f"Versuche zu verbinden mit {current_host_to_connect}:{current_port_to_connect}..."

                print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}")
                
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5) 
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                print(f"CLIENT NET: Erfolgreich verbunden mit {current_host_to_connect}:{current_port_to_connect}. Socket: {temp_sock}")
                temp_sock.settimeout(None) 
                server_socket_global = temp_sock # Globalen Socket setzen
                buffer = "" 

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True # SOFORT True setzen
                    client_view_data["error_message"] = None 
                    client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Server-Antwort."

                    # Offline-Queue-Verarbeitung NACHDEM is_socket_connected_to_server True ist
                    if client_view_data.get("offline_action_queue") and \
                       not client_view_data.get("is_processing_offline_queue"):
                        print("CLIENT NET: Verbindung hergestellt, starte Verarbeitung der Offline-Queue...")
                        threading.Thread(target=process_offline_queue, daemon=True).start()

                    # --- REJOIN LOGIC ---
                    if client_view_data.get("player_id") and client_view_data.get("player_name"):
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": client_view_data["player_id"],
                            "name": client_view_data["player_name"]
                        }
                        try:
                            print(f"CLIENT NET: Sende REJOIN_GAME als {client_view_data['player_name']} ({client_view_data['player_id']}).")
                            server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                            client_view_data["game_state"]["status_display"] = f"Sende Rejoin-Anfrage als {client_view_data['player_name']}..."
                            print(f"CLIENT NET: REJOIN_GAME für {client_view_data['player_name']} ({client_view_data['player_id']}) gesendet.")
                        except Exception as e_rejoin:
                            print(f"CLIENT NET: Senden von REJOIN_GAME fehlgeschlagen: {e_rejoin}. Versuche Neuverbindung.")
                            traceback.print_exc()
                            client_view_data["is_socket_connected_to_server"] = False 
                            client_view_data["error_message"] = "Senden der Rejoin-Anfrage fehlgeschlagen."
                    else: 
                        print("CLIENT NET: Keine Spieler-ID/Name für Rejoin vorhanden. Warte auf JOIN oder Server-Update.")
                        # if client_view_data["game_state"].get("status") == "disconnected":
                        #      client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Spielbeitritt..."


            except socket.timeout:
                print(f"CLIENT NET (CONNECT TIMEOUT): Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung.")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung."
                time.sleep(3); continue 
            except (ConnectionRefusedError, OSError) as e:
                print(f"CLIENT NET (CONNECT FAIL): Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__} - {e}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__}"
                time.sleep(3); continue
            except Exception as e_conn:
                print(f"CLIENT NET (CONNECT ERROR - UNEXPECTED): {e_conn}")
                traceback.print_exc()
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Unbekannter Verbindungsfehler: {type(e_conn).__name__}"
                time.sleep(3); continue
        
        # Erneute Prüfung nach Verbindungsaufbau-Block (falls Rejoin send fehlschlug)
        with client_data_lock:
            if not client_view_data["is_socket_connected_to_server"]:
                if server_socket_global:
                    print(f"CLIENT NET: Socket-Verbindung im Aufbau-Block als 'nicht verbunden' markiert. Schließe Socket {server_socket_global}.")
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None
                time.sleep(0.1)
                continue

        try:
            if not server_socket_global: 
                print("CLIENT NET (RECEIVE ERROR): server_socket_global ist None trotz is_socket_connected_to_server=True. Setze auf False.")
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                time.sleep(0.1); continue

            data_chunk = server_socket_global.recv(8192) 
            if not data_chunk: 
                peer_name_log = "N/A"
                try: peer_name_log = server_socket_global.getpeername() if server_socket_global else 'N/A_NO_SOCK_ON_EMPTY_RECV'
                except: pass # Ignore if getpeername fails (socket already closed etc)
                print(f"CLIENT NET: Server hat Verbindung getrennt (leere Daten erhalten von {peer_name_log}).")
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
                # print(f"CLIENT NET: Nachricht vom Server empfangen: {message.get('type', 'NO_TYPE')}") # Kann sehr verbose sein

                with client_data_lock: 
                    client_view_data["is_socket_connected_to_server"] = True 
                    msg_type = message.get("type")

                    if msg_type == "game_update":
                        if "player_id" in message and message["player_id"] is None:
                            if client_view_data["player_id"] is not None:
                                print(f"CLIENT NET: Server hat player_id=None gesendet. Resette Client-Spielerdaten.")
                            client_view_data["player_id"] = None
                            # ... (rest der player_id=None Logik) ...
                        # ... (rest der game_update Logik) ...

                        # NEU: Starte Verarbeitung der Offline-Queue, wenn Spieler-ID vorhanden und Queue nicht leer
                        # Dies ist ein Fallback, falls die Queue nach dem initialen Connect nicht abgearbeitet wurde oder neue Items enthält.
                        if client_view_data.get("player_id") and \
                           client_view_data.get("offline_action_queue") and \
                           not client_view_data.get("is_processing_offline_queue"):
                            print("CLIENT NET (game_update): Starte Verarbeitung der Offline-Queue (z.B. nach erfolgreichem Rejoin oder wenn neue Items da sind).")
                            threading.Thread(target=process_offline_queue, daemon=True).start()

                    # ... (restliche msg_type Handler) ...

        except json.JSONDecodeError:
            print(f"CLIENT NET (JSON DECODE ERROR): Buffer war '{buffer[:200]}...'")
            # ...
        except (ConnectionResetError, BrokenPipeError, OSError) as e_recv:
            print(f"CLIENT NET (RECEIVE ERROR - COMM): Verbindung getrennt (Empfang): {e_recv}")
            # ...
        except Exception as e_recv_main:
            print(f"CLIENT NET (RECEIVE ERROR - UNEXPECTED): Unerwarteter Fehler beim Empfang: {e_recv_main}")
            traceback.print_exc()
            # ...
        finally:
            is_still_connected_after_loop = False
            with client_data_lock:
                is_still_connected_after_loop = client_view_data["is_socket_connected_to_server"]
            print(f"CLIENT NET: Entering finally block of receive loop. is_still_connected_after_loop: {is_still_connected_after_loop}")

            if not is_still_connected_after_loop: 
                if server_socket_global:
                    print(f"CLIENT NET: Closing socket {server_socket_global} in finally block of receive loop.")
                    try: server_socket_global.close() 
                    except: pass
                    server_socket_global = None 
                else:
                    print("CLIENT NET: No global socket to close in finally block of receive loop.")
                time.sleep(1) 


# --- Flask Webserver Routen ---

@app.route('/')
def index_page_route(): return send_from_directory(app.static_folder, 'index.html')

# ... (andere statische Routen bleiben gleich) ...
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
        # ... (Inhalt bleibt gleich) ...
        return jsonify(client_view_data) # Gekürzt für Lesbarkeit

@app.route('/connect_to_server', methods=['POST'])
def connect_to_server_route():
    global SERVER_HOST, SERVER_PORT, server_socket_global
    data = request.get_json()
    print(f"CLIENT FLASK: /connect_to_server. Received data: {data}")
    if not data or 'server_address' not in data:
        return jsonify({"success": False, "message": "Server-Adresse fehlt."}), 400

    server_address = data['server_address'].strip()
    print(f"CLIENT FLASK: /connect_to_server. Attempting to connect to: {server_address}")
    if not server_address:
        return jsonify({"success": False, "message": "Server-Adresse darf nicht leer sein."}), 400

    try:
        if ':' in server_address:
            host, port_str = server_address.rsplit(':', 1)
            port = int(port_str)
        else:
            host = server_address
            port = 65432 
    except ValueError:
        return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed = False
    with client_data_lock:
        old_host, old_port = SERVER_HOST, SERVER_PORT
        if SERVER_HOST != host or SERVER_PORT != port:
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True
            print(f"CLIENT FLASK: Serverdetails geändert von {old_host}:{old_port} zu {host}:{port}")

        client_view_data.update({
            "user_has_initiated_connection": True, 
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False,
            "join_error": None, "error_message": None, 
            "game_message": "Verbinde mit " + server_address,
            "is_socket_connected_to_server": False, 
            # Offline-Queue hier *nicht* leeren, könnte wichtige Aktionen enthalten.
            # Nur leeren, wenn es explizit gewünscht ist (z.B. bei Reset).
        })
        print(f"CLIENT FLASK: Flags für Netzwerk-Thread gesetzt: user_has_initiated_connection=True, is_socket_connected_to_server=False")

    # Wichtig: Socket schließen, damit Netzwerk-Thread ihn neu aufbaut
    if server_socket_global:
        if server_details_changed:
            print(f"CLIENT FLASK: Server details changed, shutting down old socket: {server_socket_global}")
        else: # Auch wenn Adresse gleich, expliziter Connect-Klick soll neu verbinden
            print(f"CLIENT FLASK: Re-connecting to same server, shutting down existing socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e:
            print(f"CLIENT FLASK: Error shutting down socket: {e}")
        server_socket_global = None

    with client_data_lock:
        response_data = client_view_data.copy()
        # ... (session data)
    return jsonify(response_data)


@app.route('/register_player_details', methods=['POST'])
def register_player_details_route():
    # ... (Inhalt bleibt größtenteils gleich, ggf. Logging hinzufügen) ...
    print("CLIENT FLASK: /register_player_details called.")
    data = request.get_json()
    nickname, role_choice = data.get('nickname'), data.get('role')

    if not nickname or not role_choice:
        return jsonify({"success": False, "message": "Name oder Rolle fehlt."}), 400

    session["nickname"], session["role_choice"] = nickname, role_choice

    with client_data_lock:
        client_view_data["player_name"] = nickname 

    socket_conn_ok = False
    with client_data_lock:
        socket_conn_ok = client_view_data.get("is_socket_connected_to_server", False)
    
    print(f"CLIENT FLASK (Register): Socket connection OK: {socket_conn_ok} before sending JOIN_GAME.")

    if socket_conn_ok:
        if not send_message_to_server({"action": "JOIN_GAME", "name": nickname, "role_preference": role_choice}):
            with client_data_lock: client_view_data["join_error"] = "Senden der Join-Anfrage fehlgeschlagen."
    else:
        with client_data_lock: client_view_data["join_error"] = "Nicht mit Server verbunden. Bitte zuerst verbinden."

    with client_data_lock:
        # ...
        return jsonify(client_view_data.copy()) # Gekürzt

@app.route('/update_location_from_browser', methods=['POST'])
def update_location_from_browser():
    # ... (Inhalt bleibt gleich, ggf. Logging hinzufügen) ...
    return jsonify({"success": True, "message": "Standort an Server gesendet."}) # Gekürzt

def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True):
    # ... (Inhalt bleibt gleich, ggf. Logging hinzufügen) ...
    print(f"CLIENT FLASK: Handling generic action: {action_name}")
    return jsonify(client_view_data.copy()) # Gekürzt

# --- Flask Routen für Spielaktionen ---
@app.route('/set_ready', methods=['POST'])
def set_ready_route(): return handle_generic_action("SET_READY", "ready_status", "ready_status")

@app.route('/complete_task', methods=['POST'])
def complete_task_route():
    # ... (Inhalt bleibt gleich, ggf. Logging hinzufügen) ...
    print("CLIENT FLASK: /complete_task called.")
    return jsonify(client_view_data.copy()) # Gekürzt

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
    print(f"CLIENT FLASK: /force_server_reset_from_ui. Received data: {data}")

    if not data or 'server_address' not in data:
        return jsonify({"success": False, "message": "Server-Adresse für Reset fehlt."}), 400
    server_address = data['server_address'].strip()
    print(f"CLIENT FLASK: /force_server_reset_from_ui. Target address: {server_address}")
    if not server_address:
        return jsonify({"success": False, "message": "Server-Adresse darf nicht leer sein."}), 400

    try:
        if ':' in server_address:
            host, port_str = server_address.rsplit(':', 1)
            port = int(port_str)
        else:
            host = server_address
            port = 65432 
    except ValueError:
        return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed = False
    with client_data_lock:
        old_host, old_port = SERVER_HOST, SERVER_PORT 
        if SERVER_HOST != host or SERVER_PORT != port:
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True
            print(f"CLIENT FLASK (Reset): Serverdetails geändert von {old_host}:{old_port} zu {host}:{port}")
        
        client_view_data["user_has_initiated_connection"] = True
        client_view_data["is_socket_connected_to_server"] = False 
        client_view_data["game_message"] = f"Reset-Befehl für {server_address} in Warteschlange. Verbinde..."
        
        # Lokale Spielerdaten zurücksetzen, da ein Server-Reset die aktuelle Sitzung ungültig macht
        client_view_data["player_id"] = None
        client_view_data["player_name"] = None
        client_view_data["role"] = None
        client_view_data["confirmed_for_lobby"] = False
        client_view_data["player_is_ready"] = False
        client_view_data["join_error"] = None # Alte Fehler löschen
        client_view_data["error_message"] = None

        print(f"CLIENT FLASK (Reset): Network flags set for reconnect. Player data reset locally.")

    # Socket schließen, um Reconnect durch network_communication_thread zu erzwingen
    if server_socket_global:
        if server_details_changed:
             print(f"CLIENT FLASK (Reset): Server details changed, shutting down old socket: {server_socket_global}")
        else:
             print(f"CLIENT FLASK (Reset): Forcing reconnect for reset, shutting down existing socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e:
            print(f"CLIENT FLASK (Reset): Error shutting down socket: {e}")
        server_socket_global = None

    with client_data_lock:
        reset_action = {
            "action_for_server": {"action": "FORCE_SERVER_RESET_FROM_CLIENT"},
            "ui_message_on_cache": f"Reset-Befehl für {server_address} in Warteschlange..."
        }
        client_view_data["offline_action_queue"].clear() 
        client_view_data["offline_action_queue"].append(reset_action)
        print("CLIENT FLASK (Reset): Reset-Aktion zur Offline-Queue hinzugefügt. NICHT direkt gestartet.")
        # KEIN direkter Start von process_offline_queue mehr von hier!
    
    with client_data_lock:
        response_data = client_view_data.copy()
        # ... (session data)
    return jsonify(response_data)

@app.route('/return_to_registration', methods=['POST'])
def return_to_registration_route():
    print("CLIENT FLASK: /return_to_registration called.")
    return handle_generic_action("RETURN_TO_REGISTRATION")

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    print("CLIENT FLASK: /leave_game_and_go_to_join_screen called.")
    action_sent_successfully = False; message_to_user = "Versuche, Spiel zu verlassen..."
    original_player_id_if_any = None
    
    # Temporär Socket-Status vor dem Lock holen, um ihn an send_message_to_server weiterzugeben
    # Dies ist ein Workaround, da send_message_to_server seinen eigenen Lock hat.
    # Besser wäre es, wenn send_message_to_server den Socket-Status als Parameter akzeptiert.
    # Für jetzt: Wir verlassen uns darauf, dass der Zustand zwischen diesen Zeilen relativ stabil ist.
    current_socket_is_connected_for_send = False
    with client_data_lock:
        original_player_id_if_any = client_view_data.get("player_id")
        current_socket_is_connected_for_send = client_view_data.get("is_socket_connected_to_server", False)
        
    # Lokalen Client-Zustand sofort zurücksetzen
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
            "offline_action_queue": [], 
            "is_processing_offline_queue": False, 
            "pre_cached_tasks": [], 
        })
        if "game_state" in client_view_data and client_view_data["game_state"] is not None:
            client_view_data["game_state"]["status"] = GAME_STATE_LOBBY 
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None
        client_view_data["is_socket_connected_to_server"] = False 
        print(f"CLIENT FLASK (Leave): Lokaler Client-Zustand zurückgesetzt. user_has_initiated_connection=False. Player ID war: {original_player_id_if_any}")

    # Versuche, den Server zu informieren
    # Hier verwenden wir den *vorher* gelesenen current_socket_is_connected_for_send
    if original_player_id_if_any and server_socket_global and current_socket_is_connected_for_send:
        print(f"CLIENT FLASK (Leave): Versuche, LEAVE_GAME an Server zu senden für Player ID: {original_player_id_if_any}")
        if send_message_to_server({"action": "LEAVE_GAME_AND_GO_TO_JOIN"}): # send_message_to_server wird intern den Lock nehmen
            action_sent_successfully = True; message_to_user = "Anfrage zum Verlassen an Server gesendet."
            session.pop("nickname", None); session.pop("role_choice", None) 
            with client_data_lock: client_view_data["game_message"] = message_to_user
        else:
            message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden (Sendefehler). Clientseitig zurückgesetzt."
            with client_data_lock: client_view_data["error_message"] = message_to_user
            print(f"CLIENT FLASK (Leave): Senden von LEAVE_GAME an Server fehlgeschlagen.")
    elif original_player_id_if_any:
        message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden (Socket nicht bereit). Clientseitig zurückgesetzt."
        with client_data_lock: client_view_data["error_message"] = message_to_user
        print(f"CLIENT FLASK (Leave): Kein Socket oder nicht verbunden, um LEAVE_GAME zu senden.")
    else:
        action_sent_successfully = True; message_to_user = "Client zurückgesetzt (war nicht aktiv im Spiel)."
        session.pop("nickname", None); session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user

    with client_data_lock:
        # ... (response payload)
        return jsonify(client_view_data.copy()) # Gekürzt


if __name__ == '__main__':
    import traceback
    print("CLIENT: Initialisiere Client...")

    with client_data_lock:
        client_view_data["game_state"]["status_display"] = "Initialisiere Client Flask-App..."
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT

    print("CLIENT: Starte Netzwerk-Kommunikations-Thread...")
    threading.Thread(target=network_communication_thread, daemon=True).start()

    print(f"CLIENT: Starte Flask-App auf Port {FLASK_PORT}...")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
    print("CLIENT: Flask-App beendet.")
