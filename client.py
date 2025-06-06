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
client_view_data = {
    "player_id": None,
    "player_name": None,
    "role": None,
    "location": None,
    "confirmed_for_lobby": False,
    "player_is_ready": False,
    "player_status": "active",
    "is_socket_connected_to_server": False,
    "game_state": {
        "status": "disconnected", 
        "status_display": "Initialisiere Client...",
        "game_time_left": 0, 
        "hider_wait_time_left": 0, 
        "game_over_message": None
    },
    "lobby_players": {},
    "all_players_status": {},
    "current_task": None,
    "hider_leaderboard": [],
    "hider_locations": {},
    # "power_ups_available" wurde entfernt
    "game_message": None,
    "error_message": None,
    "join_error": None,
    "prefill_nickname": f"Spieler{random.randint(100,999)}",
    "hider_location_update_imminent": False,
    "early_end_requests_count": 0,
    "total_active_players_for_early_end": 0,
    "player_has_requested_early_end": False,
    "current_server_host": SERVER_HOST,
    "current_server_port": SERVER_PORT,
    "task_skips_available": 0
}
client_data_lock = threading.Lock()
server_socket_global = None
is_connected_to_server = False

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
    except FileNotFoundError: pass # Ignoriere, wenn termux-notification nicht da ist
    except Exception: pass # Ignoriere andere Fehler

def send_message_to_server(data):
    global server_socket_global, is_connected_to_server
    action_sent = data.get('action', 'NO_ACTION_SPECIFIED')
    if server_socket_global and is_connected_to_server:
        try:
            server_socket_global.sendall(json.dumps(data).encode('utf-8') + b'\n')
            return True
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"CLIENT SEND (ERROR): Senden von '{action_sent}' fehlgeschlagen, Verbindung verloren: {e}.")
            is_connected_to_server = False
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Verbindung zum Server verloren (Senden)."
                client_view_data["error_message"] = "Verbindung zum Server verloren."
    else:
        with client_data_lock:
            client_view_data["is_socket_connected_to_server"] = False
            if not client_view_data.get("error_message"):
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
    return False

def network_communication_thread():
    global server_socket_global, is_connected_to_server, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = ""
    while True:
        if not is_connected_to_server:
            try:
                current_host_to_connect, current_port_to_connect = "", 0
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"): 
                         client_view_data["game_state"]["status_display"] = f"Verbinde mit Spielserver {SERVER_HOST}:{SERVER_PORT}..."
                    current_host_to_connect, current_port_to_connect = SERVER_HOST, SERVER_PORT
                
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5)
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                temp_sock.settimeout(None)
                server_socket_global = temp_sock
                is_connected_to_server = True
                buffer = ""
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True
                    client_view_data["error_message"] = None # Clear previous errors
                    client_view_data["join_error"] = None   # Clear previous join errors

                    current_player_id = client_view_data.get("player_id")
                    current_player_name = client_view_data.get("player_name")

                    if current_player_id and current_player_name:
                        # Attempt to rejoin if we have an existing player identity
                        client_view_data["game_state"]["status_display"] = f"Verbunden mit {SERVER_HOST}:{SERVER_PORT}. Re-synchronisiere als {current_player_name}..."
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": current_player_id,
                            "name": current_player_name
                        }
                        try:
                            if server_socket_global: # Ensure socket is still valid
                                server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                                print(f"CLIENT REJOIN: Sent REJOIN_GAME for Player ID: {current_player_id}, Name: {current_player_name}")
                            else:
                                # This case should ideally not be hit if connect just succeeded and assigned to server_socket_global
                                print(f"CLIENT REJOIN (ERROR): server_socket_global is None before sending REJOIN_GAME for Player ID: {current_player_id}.")
                                raise OSError("Socket not available for REJOIN_GAME")
                        except Exception as e:
                            print(f"CLIENT REJOIN (ERROR): Failed to send REJOIN_GAME for Player ID: {current_player_id} to {SERVER_HOST}:{SERVER_PORT}. Error: {e}")
                            is_connected_to_server = False
                            client_view_data["is_socket_connected_to_server"] = False
                            client_view_data["game_state"]["status_display"] = f"Rejoin-Anfrage an {SERVER_HOST}:{SERVER_PORT} fehlgeschlagen."
                            # The main loop will then try to reconnect.
                    elif client_view_data["game_state"].get("status") == "disconnected" or not client_view_data.get("player_id"):
                        # Fresh connection, or player_id was cleared (e.g. by changing server)
                        client_view_data["game_state"]["status_display"] = f"Verbunden mit {SERVER_HOST}:{SERVER_PORT}. Warte auf Spielbeitritt..."
            except socket.timeout:
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung."
                time.sleep(3); continue
            except (ConnectionRefusedError, OSError):
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen."
                time.sleep(3); continue
            except Exception: 
                time.sleep(3); continue
        
        try:
            if not server_socket_global: is_connected_to_server = False; time.sleep(0.1); continue
            data_chunk = server_socket_global.recv(8192)
            if not data_chunk:
                is_connected_to_server = False
                with client_data_lock: client_view_data["game_state"]["status_display"] = "Server hat Verbindung getrennt."
                continue
            buffer += data_chunk.decode('utf-8')

            while '\n' in buffer:
                message_str, buffer = buffer.split('\n', 1)
                if not message_str.strip(): continue
                message = json.loads(message_str)

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True 
                    msg_type = message.get("type")

                    if msg_type == "game_update":
                        if "player_id" in message and message["player_id"] is None and client_view_data["player_id"] is not None:
                            client_view_data["player_id"] = None; client_view_data["player_name"] = None 
                            client_view_data["role"] = None; client_view_data["confirmed_for_lobby"] = False
                            client_view_data["player_is_ready"] = False
                        elif "player_id" in message and message["player_id"] is not None:
                            client_view_data["player_id"] = message["player_id"]; client_view_data["join_error"] = None
                        
                        update_keys = [
                            "player_name", "role", "confirmed_for_lobby", "player_is_ready", 
                            "player_status", "location", "game_state", "lobby_players", 
                            "all_players_status", "current_task", "hider_leaderboard", 
                            "hider_locations", # "power_ups_available" wurde entfernt
                            "hider_location_update_imminent",
                            "early_end_requests_count", "total_active_players_for_early_end",
                            "player_has_requested_early_end", "task_skips_available" 
                        ]
                        for key in update_keys:
                            if key in message: client_view_data[key] = message[key]
                        
                        if message.get("error_message") and message["player_id"] is None:
                            client_view_data["error_message"] = message["error_message"]
                            client_view_data["join_error"] = message["error_message"]

                    elif msg_type == "server_text_notification":
                        game_msg_text = message.get("message", "Server Nachricht")
                        show_termux_notification(title="Hide and Seek Info", content=game_msg_text, notification_id="server_info")
                        client_view_data["game_message"] = game_msg_text

                    elif msg_type == "game_event":
                        event_name = message.get("event_name")
                        if event_name == "hider_location_update_due":
                            show_termux_notification(title="Hide and Seek: ACHTUNG!", content="Hider: Standort bald benötigt! Öffne die App.", notification_id="hider_warn")
                            client_view_data["hider_location_update_imminent"] = True
                        elif event_name == "seeker_locations_updated":
                             show_termux_notification(title="Hide and Seek", content="Seeker: Hider-Standorte aktualisiert!", notification_id="seeker_update" )
                        elif event_name == "game_started":
                            show_termux_notification(title="Hide and Seek", content="Das Spiel hat begonnen!", notification_id="game_start")
                        
                    elif msg_type == "error":
                        error_text = message.get("message", "Unbekannter Fehler vom Server")
                        client_view_data["error_message"] = error_text
                        critical_errors = ["Spiel läuft bereits", "Spiel voll", "Nicht authentifiziert", "Bitte neu beitreten", "Du bist nicht mehr Teil des aktuellen Spiels", "Server wurde von einem Spieler zurückgesetzt"]
                        if any(crit_err in error_text for crit_err in critical_errors):
                            client_view_data["join_error"] = error_text
                            if client_view_data["player_id"] is not None:
                                client_view_data["player_id"] = None; client_view_data["player_name"] = None
                                client_view_data["role"] = None
                    
                    elif msg_type == "acknowledgement":
                        ack_message = message.get("message", "Aktion bestätigt.")
                        client_view_data["game_message"] = ack_message

        except json.JSONDecodeError: buffer = ""
        except (ConnectionResetError, BrokenPipeError, OSError):
            is_connected_to_server = False
            with client_data_lock: client_view_data["game_state"]["status_display"] = "Verbindung getrennt (Empfang)."
        except Exception: is_connected_to_server = False
        finally: 
            if not is_connected_to_server:
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                if server_socket_global:
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None

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

@app.route('/join_game', methods=['POST'])
def join_game_route():
    global SERVER_HOST, SERVER_PORT, is_connected_to_server, server_socket_global
    data = request.get_json();
    if not data: return jsonify({"success": False, "message": "Keine Daten."}), 400

    nickname, role_choice = data.get('nickname'), data.get('role')
    new_server_host, new_server_port_str = data.get('server_host'), data.get('server_port')

    if not nickname or not role_choice: return jsonify({"success": False, "message": "Name/Rolle fehlt."}), 400
    if not new_server_host or not new_server_port_str: return jsonify({"success": False, "message": "Serveradresse oder Port fehlt."}), 400

    try: new_server_port = int(new_server_port_str)
    except ValueError: return jsonify({"success": False, "message": "Ungültiger Server-Port."}), 400

    session["nickname"], session["role_choice"] = nickname, role_choice
    
    server_details_changed = False
    with client_data_lock:
        if SERVER_HOST != new_server_host or SERVER_PORT != new_server_port:
            SERVER_HOST, SERVER_PORT = new_server_host, new_server_port
            client_view_data["current_server_host"], client_view_data["current_server_port"] = SERVER_HOST, SERVER_PORT
            server_details_changed = True

            # If server details changed, we MUST clear the old player identity
            # to prevent REJOIN_GAME (from network_communication_thread) to a new server with an old ID.
            # This also ensures a fresh context for the new server.
            client_view_data["player_id"] = None
            client_view_data["player_name"] = None # Clear name associated with the old session
            client_view_data["role"] = None        # Clear role associated with the old session
            client_view_data["confirmed_for_lobby"] = False
            client_view_data["player_is_ready"] = False
            # Reset other game-specific states that might be tied to the old session
            client_view_data["current_task"] = None
            client_view_data["hider_leaderboard"] = []
            client_view_data["hider_locations"] = {}
            client_view_data["task_skips_available"] = 0
            client_view_data["game_message"] = None # Clear old messages
            # error_message and join_error are handled later or by the network thread
            print(f"CLIENT JOIN_GAME: Server details changed to {SERVER_HOST}:{SERVER_PORT}. Cleared old player session data for fresh join.")

        # This update then correctly uses the nickname and role from the form for the new join context.
        # player_id is explicitly set to None here, which is correct for a new join action.
        client_view_data.update({
            "player_id": None,
            "player_name": nickname, # Nickname from the current join form
            "role": role_choice,     # Role from the current join form
            "confirmed_for_lobby": False, # Reset for new join
            "player_is_ready": False,     # Reset for new join
            "player_status": "active",
            "join_error": None, # Clear previous join errors before attempting new join
            "error_message": None, # Clear general errors
            "game_message": None,
            "current_task": None,
            "hider_leaderboard": [],
            "hider_locations": {},
            "hider_location_update_imminent": False,
            "early_end_requests_count": 0,
            "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False,
            "task_skips_available": 0
        })
        if "game_state" not in client_view_data or client_view_data["game_state"] is None: 
            client_view_data["game_state"] = {"status": "disconnected", "status_display": "Initialisiere..."}
        
        if server_details_changed:
            client_view_data["game_state"]["status_display"] = f"Serveradresse aktualisiert. Verbinde mit {SERVER_HOST}:{SERVER_PORT}..."
            client_view_data["is_socket_connected_to_server"] = False
            is_connected_to_server = False 
            if server_socket_global:
                try: server_socket_global.shutdown(socket.SHUT_RDWR); server_socket_global.close()
                except OSError: pass
                server_socket_global = None
        else: client_view_data["game_state"]["status_display"] = f"Sende Beitrittsanfrage als {nickname}..."
    
    response_for_js = {"success": True, "message": "Beitrittsanfrage wird verarbeitet."}
    # Attempt to send JOIN_GAME if connected, or let network_communication_thread handle connection
    if is_connected_to_server and server_socket_global:
        payload = {
            "action": "JOIN_GAME",
            "name": nickname,
            "role_preference": role_choice
            # player_id is not sent here; server assigns it on successful JOIN_GAME
        }
        success, message = send_message_to_server(payload)
        if not success:
            with client_data_lock:
                client_view_data["join_error"] = message if message else "Fehler beim Senden der Beitrittsanfrage."
            return jsonify({"success": False, "message": client_view_data["join_error"]}), 500
        else:
            with client_data_lock:
                 client_view_data["game_state"]["status_display"] = f"Beitrittsanfrage an {SERVER_HOST}:{SERVER_PORT} gesendet. Warte auf Antwort..."
            return jsonify({"success": True, "message": "Beitrittsanfrage gesendet. Warte auf Server-Antwort."})

    # If not connected, or if server details just changed:
    # The network_communication_thread is responsible for establishing the connection.
    # If server_details_changed, it will connect to the new server.
    # The user might see a "Connecting..." message and then the UI should reflect the new state.
    # A JOIN_GAME is an explicit user action. If the connection isn't ready at the moment of this action,
    # the user might need to click "Join" again once connected.
    # The REJOIN_GAME logic in network_communication_thread handles automatic re-synchronization if a player_id exists
    # for the *current* server, upon re-establishing a connection.
    else:
        status_message = f"Verbindung zu {SERVER_HOST}:{SERVER_PORT} wird hergestellt..."
        if server_details_changed:
            status_message = f"Serverdetails geändert. Verbindung zu {SERVER_HOST}:{SERVER_PORT} wird hergestellt. Bitte nach Verbindung erneut beitreten."
        else: # Not connected, server details same
            status_message = f"Nicht mit {SERVER_HOST}:{SERVER_PORT} verbunden. Verbindung wird versucht. Bitte nach erfolgreicher Verbindung erneut beitreten."

        with client_data_lock:
            # Update status display to inform user
            client_view_data["game_state"]["status_display"] = status_message
            # Ensure player_name and role are stored so if user clicks join again, or for context
            client_view_data["player_name"] = nickname
            client_view_data["role"] = role_choice
            if not server_details_changed: # Only set join_error if it's not a server change scenario
                 client_view_data["join_error"] = "Nicht mit dem Server verbunden. Bitte warten Sie auf die Verbindung und versuchen Sie es erneut."

        print(f"CLIENT JOIN_GAME: Nicht verbunden oder Serverdetails geändert. Status: {status_message}")
        # Return 202 to indicate the request is accepted but processing (connection) is pending.
        # The client-side JS should handle this by not assuming immediate success and relying on polling /game_data.
        return jsonify({"success": False, "message": status_message}), 202

@app.route('/update_location_from_browser', methods=['POST'])
def update_location_from_browser():
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
    if player_id_local and game_can_receive_loc and socket_ok_local and is_connected_to_server:
        send_success = send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy})
        if send_success: 
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy]
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    else: return jsonify({"success": False, "message": "Keine Serververbindung (Socket)."}), 503

def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True):
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
        if req_data is None and payload_key != "ready_status": return jsonify({"success": False, "message": "Keine JSON-Daten."}), 400
        val_from_req = req_data.get(payload_value_from_request or payload_key) if req_data else None
        if payload_key == "ready_status":
             if not isinstance(val_from_req, bool): return jsonify({"success": False, "message": "Ungültiger Wert für ready_status."}), 400
        elif val_from_req is None and payload_key != "force_server_reset":
            return jsonify({"success": False, "message": f"Fehlender Wert für '{payload_key}'."}), 400
        if val_from_req is not None or payload_key != "force_server_reset":
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

@app.route('/confirm_lobby_join', methods=['POST'])
def confirm_lobby_join_route(): return handle_generic_action("CONFIRM_LOBBY_JOIN")
@app.route('/set_ready', methods=['POST'])
def set_ready_route(): return handle_generic_action("SET_READY", "ready_status", "ready_status")
@app.route('/complete_task', methods=['POST'])
def complete_task_route(): return handle_generic_action("TASK_COMPLETE")
@app.route('/catch_hider', methods=['POST'])
def catch_hider_route(): return handle_generic_action("CATCH_HIDER", "hider_id_to_catch", "hider_id_to_catch")
# @app.route('/use_powerup', methods=['POST']) wurde entfernt

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    action_sent_successfully = False; message_to_user = "Versuche, Spiel zu verlassen..."
    original_player_id_if_any = None
    with client_data_lock: original_player_id_if_any = client_view_data.get("player_id")
    
    with client_data_lock:
        client_view_data.update({
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False, "player_status": "active",
            "current_task": None, "hider_leaderboard": [], "hider_locations": {},
            # "power_ups_available" wurde entfernt
            "game_message": None, "error_message": None, "join_error": None, 
            "hider_location_update_imminent": False,
            "early_end_requests_count": 0, "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False, "task_skips_available": 0 
        })
        if "game_state" in client_view_data and client_view_data["game_state"] is not None:
            client_view_data["game_state"]["status"] = GAME_STATE_LOBBY 
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None 

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

@app.route('/request_early_round_end_action', methods=['POST'])
def request_early_round_end_action_route(): return handle_generic_action("REQUEST_EARLY_ROUND_END")
@app.route('/skip_task', methods=['POST']) 
def skip_task_route(): return handle_generic_action("SKIP_TASK")
@app.route('/force_server_reset_from_ui', methods=['POST'])
def force_server_reset_route(): return handle_generic_action("FORCE_SERVER_RESET_FROM_CLIENT", requires_player_id=False)

if __name__ == '__main__':
    with client_data_lock: 
        client_view_data["game_state"]["status_display"] = "Initialisiere Client Flask-App..."
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT 
    
    threading.Thread(target=network_communication_thread, daemon=True).start()
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
