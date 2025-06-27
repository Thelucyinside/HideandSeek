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
STATIC_FOLDER = '.'

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
        command.extend(['--vibrate', '500']) # Vibrieren für 0.5 Sekunden
        subprocess.run(command, check=False) # check=False, um Fehler zu ignorieren, wenn Befehl nicht gefunden
    except FileNotFoundError:
        pass # Ignoriere, wenn termux-notification nicht gefunden wird
    except Exception as e:
        print(f"CLIENT NOTIFICATION ERROR: {e}") # Logge andere unerwartete Fehler

def send_message_to_server(data):
    """Sendet eine JSON-Nachricht an den globalen Spielserver-Socket."""
    global server_socket_global
    action_sent = data.get('action', 'NO_ACTION_SPECIFIED')
    socket_is_currently_connected = False
    with client_data_lock: # Prüfe den aktuellen Verbindungsstatus unter Lock
        socket_is_currently_connected = client_view_data["is_socket_connected_to_server"]
    
    # print(f"CLIENT SEND: Attempting to send action '{action_sent}'. Socket global: {'Exists' if server_socket_global else 'None'}, Connected-Flag: {socket_is_currently_connected}, Socket Obj: {server_socket_global}")

    if server_socket_global and socket_is_currently_connected:
        try:
            server_socket_global.sendall(json.dumps(data).encode('utf-8') + b'\n')
            # print(f"CLIENT SEND: Action '{action_sent}' sent successfully.")
            return True
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            print(f"CLIENT SEND (ERROR): Senden von '{action_sent}' fehlgeschlagen, Verbindung verloren: {e}.")
            with client_data_lock: # Aktualisiere den Verbindungsstatus bei Sendefehler
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
        # Dieses Log ist sehr wichtig, um zu sehen, warum nicht gesendet wurde.
        print(f"CLIENT SEND (NO CONN): Aktion '{action_sent}' nicht gesendet. Socket: {server_socket_global}, Connected-Flag: {socket_is_currently_connected}")
        with client_data_lock:
            # Falls kein Socket oder der Status schon als getrennt markiert ist
            client_view_data["is_socket_connected_to_server"] = False # Sicherstellen, dass es False ist
            if not client_view_data.get("error_message"): # Nur setzen, wenn nicht schon ein anderer Fehler da ist
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
    return False

def process_offline_queue():
    """
    Verarbeitet die gesammelten Offline-Aktionen und sendet sie an den Server.
    Wird in einem separaten Thread ausgeführt.
    """
    with client_data_lock:
        if not client_view_data.get("offline_action_queue") or client_view_data.get("is_processing_offline_queue"):
            # print(f"CLIENT OFFLINE QUEUE: Skipping processing. Queue empty or already processing. Queue len: {len(client_view_data.get('offline_action_queue', []))}, Processing flag: {client_view_data.get('is_processing_offline_queue')}")
            return
        client_view_data["is_processing_offline_queue"] = True
        queue_to_process = list(client_view_data["offline_action_queue"]) # Kopie erstellen
        client_view_data["offline_action_queue"].clear() # Original-Queue leeren, um neue Offline-Aktionen zu sammeln, während diese verarbeitet wird

    print(f"CLIENT OFFLINE QUEUE: Starte Verarbeitung von {len(queue_to_process)} Offline-Aktionen.")
    successfully_sent_actions_count = 0
    failed_actions_to_re_queue = []

    for offline_action_package in queue_to_process:
        action_to_send_to_server = offline_action_package.get("action_for_server")
        if action_to_send_to_server:
            # print(f"CLIENT OFFLINE QUEUE: Versuche Aktion zu senden: {action_to_send_to_server.get('action')}")
            # Versuche zu senden. send_message_to_server aktualisiert is_socket_connected_to_server bei Fehler.
            if send_message_to_server(action_to_send_to_server):
                # print(f"CLIENT OFFLINE QUEUE: Offline-Aktion '{action_to_send_to_server.get('action')}' erfolgreich an Server gesendet.")
                successfully_sent_actions_count += 1
            else:
                print(f"CLIENT OFFLINE QUEUE: Senden der Offline-Aktion '{action_to_send_to_server.get('action')}' fehlgeschlagen.")
                failed_actions_to_re_queue.append(offline_action_package)
                # Falls die Verbindung erneut abbricht, breche ab, um nicht sinnlos zu versuchen
                with client_data_lock:
                    if not client_view_data["is_socket_connected_to_server"]:
                        print("CLIENT OFFLINE QUEUE: Verbindung während Verarbeitung verloren. Breche ab.")
                        break # Beende Schleife, Rest wird re-queued.
        else:
            print(f"CLIENT ERROR: Ungültiges Offline-Aktions-Paket: {offline_action_package}")

    with client_data_lock:
        # Füge die fehlgeschlagenen Aktionen wieder an den Anfang der (jetzt möglicherweise wieder gefüllten) globalen Queue
        client_view_data["offline_action_queue"] = failed_actions_to_re_queue + client_view_data["offline_action_queue"]
        client_view_data["is_processing_offline_queue"] = False
        if not client_view_data["offline_action_queue"] and successfully_sent_actions_count > 0 :
             client_view_data["game_message"] = "Alle Offline-Aktionen erfolgreich synchronisiert."
        elif failed_actions_to_re_queue:
             client_view_data["error_message"] = f"{len(failed_actions_to_re_queue)} Offline-Aktion(en) konnte(n) nicht synchronisiert werden."
        else: # Keine Aktionen in Queue, aber auch keine gesendet (oder alle waren schon vorher leer)
            client_view_data["game_message"] = None # Lösche ggf. alte Nachrichten
    # print(f"CLIENT OFFLINE QUEUE: Verarbeitung beendet. {successfully_sent_actions_count} gesendet. {len(client_view_data['offline_action_queue'])} verbleiben.")


def network_communication_thread():
    """
    Dieser Thread verwaltet die persistente Socket-Verbindung zum Spielserver.
    Er versucht, die Verbindung bei Verlust wiederherzustellen und sendet ggf. eine Rejoin-Anfrage.
    Alle eingehenden Nachrichten vom Server werden hier verarbeitet und in `client_view_data` aktualisiert.
    """
    global server_socket_global, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = "" # Puffer für unvollständige Nachrichtenpakete
    print("CLIENT NET: Network communication thread started.")

    while True:
        user_wants_to_connect = False
        with client_data_lock:
            user_wants_to_connect = client_view_data.get("user_has_initiated_connection", False)
        
        if not user_wants_to_connect:
            with client_data_lock:
                if client_view_data["is_socket_connected_to_server"]:
                    client_view_data["is_socket_connected_to_server"] = False 
                client_view_data["game_state"]["status_display"] = "Bereit zum Verbinden mit einem Server."
            
            if server_socket_global:
                # print(f"CLIENT NET: User does not want to connect, closing existing socket {server_socket_global}")
                try: server_socket_global.close()
                except: pass
                server_socket_global = None

            time.sleep(1) 
            continue 

        socket_should_be_connected = False
        with client_data_lock:
            socket_should_be_connected = client_view_data["is_socket_connected_to_server"]
            current_host_to_connect = client_view_data["current_server_host"]
            current_port_to_connect = client_view_data["current_server_port"]


        if not socket_should_be_connected: 
            try:
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False 
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"):
                         client_view_data["game_state"]["status_display"] = f"Verbinde mit {current_host_to_connect}:{current_port_to_connect}..."

                # print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}")
                
                if server_socket_global:
                    # print(f"CLIENT NET: Schließe alten Socket {server_socket_global} vor neuem Verbindungsversuch.")
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None

                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5) 
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                # print(f"CLIENT NET: Erfolgreich verbunden mit {current_host_to_connect}:{current_port_to_connect}. Socket: {temp_sock}")
                temp_sock.settimeout(None)
                server_socket_global = temp_sock
                buffer = "" 

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True
                    client_view_data["error_message"] = None 
                    client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Server-Antwort."

                    if client_view_data.get("offline_action_queue") and \
                       not client_view_data.get("is_processing_offline_queue"):
                        # print("CLIENT NET: Verbindung hergestellt, starte Verarbeitung der Offline-Queue...")
                        threading.Thread(target=process_offline_queue, daemon=True).start()
                    
                    if client_view_data.get("player_id") and client_view_data.get("player_name"):
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": client_view_data["player_id"],
                            "name": client_view_data["player_name"]
                        }
                        try:
                            server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                            client_view_data["game_state"]["status_display"] = f"Sende Rejoin-Anfrage als {client_view_data['player_name']}..."
                            # print(f"CLIENT NET: REJOIN_GAME für {client_view_data['player_name']} ({client_view_data['player_id']}) gesendet.")
                        except Exception as e_rejoin:
                            print(f"CLIENT NET: Senden von REJOIN_GAME fehlgeschlagen: {e_rejoin}.")
                            traceback.print_exc()
                            client_view_data["is_socket_connected_to_server"] = False
                            client_view_data["error_message"] = "Senden der Rejoin-Anfrage fehlgeschlagen."
                    else: 
                        # print("CLIENT NET: Keine Spieler-ID/Name für Rejoin vorhanden. Warte auf JOIN oder Server-Update.")
                        pass


            except socket.timeout:
                print(f"CLIENT NET (CONNECT TIMEOUT): Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung.")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: gaierror"
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
        
        with client_data_lock:
            if not client_view_data["is_socket_connected_to_server"]:
                if server_socket_global:
                    # print(f"CLIENT NET: Socket-Verbindung im Aufbau-Block als 'nicht verbunden' markiert. Schließe Socket {server_socket_global}.")
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
                print(f"CLIENT NET: Server hat Verbindung getrennt (leere Daten erhalten).")
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

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True
                    msg_type = message.get("type")

                    if msg_type == "game_update":
                        # *** HIER IST DIE EINE, WICHTIGE ÄNDERUNG ***
                        if "player_id" in message and message["player_id"] is None:
                            is_definitive_kick_out = bool(message.get("join_error")) or \
                                                     "Du bist nicht mehr Teil des aktuellen Spiels" in message.get("error_message", "") or \
                                                     "Rejoin fehlgeschlagen" in message.get("error_message", "")

                            client_thinks_its_ingame = (
                                client_view_data.get("player_id") is not None and
                                client_view_data.get("game_state", {}).get("status") in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]
                            )

                            if is_definitive_kick_out or not client_thinks_its_ingame:
                                if client_view_data["player_id"] is not None:
                                    print(f"CLIENT NET: Server hat player_id=None mit definitivem Grund gesendet. Resette Client-Spielerdaten.")
                                
                                client_view_data["player_id"] = None
                                client_view_data["player_name"] = None
                                client_view_data["role"] = None
                                client_view_data["confirmed_for_lobby"] = False
                                client_view_data["player_is_ready"] = False
                                
                                if client_view_data["offline_action_queue"]:
                                    print("CLIENT NET (player_id=None): Leere Offline-Queue, da Spielerdaten resettet wurden.")
                                    client_view_data["offline_action_queue"].clear()
                                client_view_data["is_processing_offline_queue"] = False

                                if message.get("join_error"): client_view_data["join_error"] = message["join_error"]
                                if message.get("error_message"): client_view_data["error_message"] = message["error_message"]
                            
                            else:
                                print(f"CLIENT NET: Ignoriere transienten player_id=None vom Server, da Client sich im Spiel wähnt und kein expliziter 'join_error' vorliegt. Warte auf Rejoin.")

                        elif "player_id" in message and message["player_id"] is not None:
                            if client_view_data["player_id"] != message["player_id"]:
                                print(f"CLIENT NET: Eigene Player ID vom Server erhalten/geändert zu: {message['player_id']}")
                            client_view_data["player_id"] = message["player_id"]
                            client_view_data["join_error"] = None
                        
                        # *** ENDE DER ÄNDERUNG ***

                        update_keys = [
                            "player_name", "role", "confirmed_for_lobby", "player_is_ready",
                            "player_status", "location", "game_state", "lobby_players",
                            "all_players_status", "current_task", "hider_leaderboard",
                            "hider_locations",
                            "hider_location_update_imminent",
                            "early_end_requests_count", "total_active_players_for_early_end",
                            "player_has_requested_early_end", "task_skips_available",
                            "pre_cached_tasks" 
                        ]
                        for key in update_keys:
                            if key in message: client_view_data[key] = message[key]

                        if client_view_data.get("player_id") and \
                           client_view_data.get("offline_action_queue") and \
                           not client_view_data.get("is_processing_offline_queue"):
                            threading.Thread(target=process_offline_queue, daemon=True).start()

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
                        critical_errors = [
                            "Spiel läuft bereits", "Spiel voll", "Nicht authentifiziert",
                            "Bitte neu beitreten", "Du bist nicht mehr Teil des aktuellen Spiels",
                            "Server wurde von einem Spieler zurückgesetzt", "Rejoin fehlgeschlagen",
                            "Name", "bereits vergeben" 
                        ]
                        if any(crit_err in error_text for crit_err in critical_errors):
                            client_view_data["join_error"] = error_text 
                            if client_view_data["player_id"] is not None: 
                                print(f"CLIENT NET: Kritischer Fehler vom Server '{error_text}'. Resette player_id.")
                                client_view_data["player_id"] = None; client_view_data["player_name"] = None
                                client_view_data["role"] = None; client_view_data["confirmed_for_lobby"] = False
                                client_view_data["player_is_ready"] = False
                                if client_view_data["offline_action_queue"]:
                                    print("CLIENT NET (critical error): Leere Offline-Queue.")
                                    client_view_data["offline_action_queue"].clear() 

                    elif msg_type == "acknowledgement":
                        ack_message = message.get("message", "Aktion bestätigt.")
                        client_view_data["game_message"] = ack_message

        except json.JSONDecodeError:
            print(f"CLIENT NET (JSON DECODE ERROR): Buffer war '{buffer[:200]}...'")
            with client_data_lock: client_view_data["error_message"] = "Fehlerhafte Daten vom Server empfangen."
            buffer = "" 
        except (ConnectionResetError, BrokenPipeError, OSError) as e_recv:
            print(f"CLIENT NET (RECEIVE ERROR - COMM): Verbindung getrennt (Empfang): {e_recv}")
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = f"Verbindung getrennt (Empfang): {type(e_recv).__name__}"
        except Exception as e_recv_main:
            print(f"CLIENT NET (RECEIVE ERROR - UNEXPECTED): Unerwarteter Fehler beim Empfang: {e_recv_main}")
            traceback.print_exc()
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False 
                client_view_data["error_message"] = "Interner Client-Fehler beim Empfang von Serverdaten."
        finally:
            is_still_connected_after_loop = False
            with client_data_lock:
                is_still_connected_after_loop = client_view_data["is_socket_connected_to_server"]

            if not is_still_connected_after_loop: 
                if server_socket_global:
                    try: server_socket_global.close() 
                    except: pass
                    server_socket_global = None 
                time.sleep(1) 


# --- Flask Webserver Routen (Originalzustand) ---

@app.route('/')
def index_page_route(): return send_from_directory(app.static_folder, 'index.html')

@app.route('/manifest.json')
def manifest_route(): return send_from_directory(app.static_folder, 'manifest.json')

@app.route('/sw.js')
def service_worker_route(): return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript')

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
        if SERVER_HOST != host or SERVER_PORT != port:
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True

        client_view_data.update({
            "user_has_initiated_connection": True, 
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False,
            "join_error": None, "error_message": None, 
            "game_message": "Verbinde mit " + server_address,
            "is_socket_connected_to_server": False, 
        })

    if server_socket_global:
        if server_details_changed:
            print(f"CLIENT FLASK: Server details changed, shutting down old socket: {server_socket_global}")
        else:
            print(f"CLIENT FLASK: Re-connecting to same server, shutting down existing socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e:
            print(f"CLIENT FLASK: Error shutting down socket (ignorable if already closed): {e}")
        finally:
            server_socket_global = None

    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)


@app.route('/register_player_details', methods=['POST'])
def register_player_details_route():
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
    if player_id_local and game_can_receive_loc and socket_ok_local:
        if send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy}):
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy] 
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID bekannt. Bitte zuerst beitreten."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    else: return jsonify({"success": False, "message": "Keine aktive Socket-Verbindung zum Spielserver."}), 503

@app.route('/set_ready', methods=['POST'])
def set_ready_route():
    data = request.get_json()
    if data is None or 'ready_status' not in data:
        return jsonify({"success": False, "message": "ready_status fehlt"}), 400
    
    with client_data_lock:
        player_id = client_view_data.get("player_id")
    if not player_id:
        return jsonify({"success": False, "message": "Keine Spieler-ID."}), 403
        
    action_payload = {"action": "SET_READY", "ready_status": data['ready_status']}
    success_sent = send_message_to_server(action_payload)
    
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None 
        response_data = client_view_data.copy()
    return jsonify(response_data)


@app.route('/complete_task', methods=['POST'])
def complete_task_route():
    player_id_local, current_task_local, socket_ok_local, is_hider_active = None, None, False, False
    with client_data_lock:
        player_id_local = client_view_data.get("player_id")
        current_task_local = client_view_data.get("current_task") 
        socket_ok_local = client_view_data.get("is_socket_connected_to_server", False)
        is_hider_active = (client_view_data.get("role") == "hider" and
                           client_view_data.get("player_status") == "active")

    if not player_id_local or not is_hider_active:
        with client_data_lock: temp_cvd = client_view_data.copy()
        return jsonify({"success": False, "message": "Aktion nicht möglich (kein aktiver Hider oder keine Spieler-ID).", **temp_cvd}), 403

    if not current_task_local or not current_task_local.get("id"):
        with client_data_lock: temp_cvd = client_view_data.copy()
        return jsonify({"success": False, "message": "Keine aktive Aufgabe zum Erledigen vorhanden.", **temp_cvd}), 400

    task_id_to_complete = current_task_local["id"]
    task_description_for_ui_msg = current_task_local.get("description", "Unbekannte Aufgabe")

    if socket_ok_local: 
        action_payload_for_server = {"action": "TASK_COMPLETE"}
        success_sent = send_message_to_server(action_payload_for_server)
        with client_data_lock:
            if success_sent: client_view_data["error_message"] = None
            response_data = client_view_data.copy()
        return jsonify(response_data)
    else: 
        offline_action_for_server = {
            "action": "TASK_COMPLETE_OFFLINE", 
            "task_id": task_id_to_complete,
            "completed_at_timestamp_offline": time.time() 
        }
        offline_package = {
            "action_for_server": offline_action_for_server,
            "ui_message_on_cache": f"Aufgabe '{task_description_for_ui_msg}' offline erledigt. Sende bei Verbindung."
        }
        with client_data_lock:
            client_view_data["offline_action_queue"].append(offline_package)
            client_view_data["game_message"] = offline_package["ui_message_on_cache"]
            client_view_data["current_task"] = None
            response_data = client_view_data.copy()
        print(f"CLIENT FLASK: Aufgabe '{task_description_for_ui_msg}' offline erledigt, zur Queue hinzugefügt.")
        return jsonify(response_data)


@app.route('/catch_hider', methods=['POST'])
def catch_hider_route():
    data = request.get_json()
    if data is None or 'hider_id_to_catch' not in data:
        return jsonify({"success": False, "message": "hider_id_to_catch fehlt"}), 400
    
    with client_data_lock:
        player_id = client_view_data.get("player_id")
    if not player_id:
        return jsonify({"success": False, "message": "Keine Spieler-ID."}), 403
        
    action_payload = {"action": "CATCH_HIDER", "hider_id_to_catch": data['hider_id_to_catch']}
    success_sent = send_message_to_server(action_payload)
    
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None
        response_data = client_view_data.copy()
    return jsonify(response_data)

@app.route('/request_early_round_end_action', methods=['POST'])
def request_early_round_end_action_route():
    with client_data_lock:
        player_id = client_view_data.get("player_id")
    if not player_id:
        return jsonify({"success": False, "message": "Keine Spieler-ID."}), 403

    success_sent = send_message_to_server({"action": "REQUEST_EARLY_ROUND_END"})
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None
        response_data = client_view_data.copy()
    return jsonify(response_data)

@app.route('/skip_task', methods=['POST'])
def skip_task_route():
    with client_data_lock:
        player_id = client_view_data.get("player_id")
    if not player_id:
        return jsonify({"success": False, "message": "Keine Spieler-ID."}), 403
        
    success_sent = send_message_to_server({"action": "SKIP_TASK"})
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None
        response_data = client_view_data.copy()
    return jsonify(response_data)

@app.route('/force_server_reset_from_ui', methods=['POST'])
def force_server_reset_route():
    # Diese Aktion erfordert keine Spieler-ID, sie ist ein Notfall-Tool
    success_sent = send_message_to_server({"action": "FORCE_SERVER_RESET_FROM_CLIENT"})
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None
        response_data = client_view_data.copy()
    return jsonify(response_data)

@app.route('/return_to_registration', methods=['POST'])
def return_to_registration_route():
    with client_data_lock:
        player_id = client_view_data.get("player_id")
    if not player_id:
        return jsonify({"success": False, "message": "Keine Spieler-ID."}), 403
        
    success_sent = send_message_to_server({"action": "RETURN_TO_REGISTRATION"})
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None
        response_data = client_view_data.copy()
    return jsonify(response_data)

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    original_player_id_if_any = None
    
    with client_data_lock:
        original_player_id_if_any = client_view_data.get("player_id")

        client_view_data.update({
            "user_has_initiated_connection": False,
            "is_socket_connected_to_server": False, 
            "player_id": None, "player_name": None, "role": None,
            "confirmed_for_lobby": False, "player_is_ready": False,
            "join_error": None, "error_message": None, 
            "offline_action_queue": [],
            "is_processing_offline_queue": False, 
        })
        if "game_state" in client_view_data:
            client_view_data["game_state"]["status"] = "disconnected"
            client_view_data["game_state"]["status_display"] = "Zurück zum Startbildschirm..."
        print(f"CLIENT FLASK (Leave): Lokaler Client-Zustand zurückgesetzt. Player ID war: {original_player_id_if_any}")

    if original_player_id_if_any and server_socket_global:
        send_message_to_server({"action": "LEAVE_GAME_AND_GO_TO_JOIN"})

    session.pop("nickname", None); session.pop("role_choice", None)
    
    with client_data_lock:
        response_payload = client_view_data.copy()
    return jsonify(response_payload)


if __name__ == '__main__':
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
