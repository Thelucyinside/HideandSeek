# server.py
import socket
import threading
import json
import time
import random
from tasks import TASKS

HOST = '0.0.0.0'
PORT = 65432
GAME_DURATION_SECONDS = 1800
HIDER_START_DELAY_SECONDS = 5
MIN_HIDER_LOCATION_UPDATE_INTERVAL = 30
MAX_HIDER_LOCATION_UPDATE_INTERVAL = 180
POWER_UP_COOLDOWN_SECONDS = 300
HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS = 20

POWER_UPS = {
    "reveal_one": {"id": "reveal_one", "name": "Zeige einen Hider (präzise)", "cooldown": 300},
    "radar_ping": {"id": "radar_ping", "name": "Kurzer Radar Ping (alle Hider, ungenau)", "cooldown": 180}
}

GAME_STATE_LOBBY = "lobby"
GAME_STATE_HIDER_WAIT = "hider_wait"
GAME_STATE_RUNNING = "running"
GAME_STATE_HIDER_WINS = "hider_wins"
GAME_STATE_SEEKER_WINS = "seeker_wins"

GAME_STATE_DISPLAY_NAMES = {
    GAME_STATE_LOBBY: "Lobby - Warten auf Spieler",
    GAME_STATE_HIDER_WAIT: "Vorbereitung - Hider verstecken sich",
    GAME_STATE_RUNNING: "Spiel läuft",
    GAME_STATE_HIDER_WINS: "Spiel beendet - Hider gewinnen!",
    GAME_STATE_SEEKER_WINS: "Spiel beendet - Seeker gewinnen!"
}

game_data = {}
data_lock = threading.RLock()

def reset_game_to_initial_state():
    """ Setzt das Spiel komplett zurück, entfernt alle Spieler und startet eine frische Lobby. """
    global game_data
    with data_lock:
        print("SERVER LOGIC: Spiel wird komplett auf Anfangszustand zurückgesetzt.")
        game_data.clear()
        game_data.update({
            "status": GAME_STATE_LOBBY,
            "status_display": GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY],
            "players": {}, # Alle Spieler entfernt
            "game_start_time_actual": None,
            "game_end_time": None,
            "hider_wait_end_time": None,
            "next_seeker_hider_location_broadcast_time": 0,
            "current_hider_location_update_interval": MAX_HIDER_LOCATION_UPDATE_INTERVAL,
            "available_tasks": list(TASKS),
            "game_over_message": None,
            "hider_warning_active_for_current_cycle": False,
            "early_end_requests": set(), # Für Abstimmung zum Rundenende
            "total_active_players_for_early_end": 0 # Für Abstimmung zum Rundenende
        })

def get_active_lobby_players_data():
    active_lobby_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("confirmed_for_lobby", False):
                active_lobby_players[p_id] = {
                    "name": p_info.get("name", "Unbekannt"),
                    "role": p_info.get("current_role", "hider"), 
                    "is_ready": p_info.get("is_ready", False)
                }
    return active_lobby_players

def get_all_players_public_status():
    all_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            all_players[p_id] = {
                "name": p_info.get("name", "Unbekannt"),
                "role": p_info.get("current_role", "hider"),
                "status": p_info.get("status_ingame", "active")
            }
    return all_players

def get_hider_leaderboard():
    leaderboard = []
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("original_role") == "hider":
                leaderboard.append({
                    "id": p_id,
                    "name": p_info.get("name", "Unbekannt"),
                    "points": p_info.get("points", 0),
                    "status": p_info.get("status_ingame", "active")
                })
    leaderboard.sort(key=lambda x: x["points"], reverse=True)
    return leaderboard

def assign_task_to_hider(player_id):
    with data_lock:
        player = game_data.get("players", {}).get(player_id)
        if not player or player.get("current_role") != "hider" or player.get("status_ingame") != "active":
            return
        
        available_tasks_list = game_data.get("available_tasks")
        if not player.get("task") and available_tasks_list: 
            task = random.choice(available_tasks_list)
            player["task"] = task
            player["task_deadline"] = time.time() + task.get("time_limit_seconds", 180)
            print(f"SERVER TASK: Hider {player.get('name','N/A')} ({player_id}) neue Aufgabe: {task.get('description','N/A')}")

def count_active_players_for_early_end():
    with data_lock:
        return sum(1 for p_info in game_data.get("players", {}).values()
                   if p_info.get("status_ingame") == "active" and p_info.get("confirmed_for_lobby")) # confirmed_for_lobby ist wichtig

def send_data_to_one_client(conn, player_id_for_perspective):
    payload = {}
    player_name_for_log = "N/A_IN_SEND_INIT"
    try:
        with data_lock:
            if "players" not in game_data or player_id_for_perspective not in game_data["players"]:
                # Sende spezielle Nachricht an den Client, dass seine player_id serverseitig nicht mehr existiert
                # Dies hilft dem Client, seinen eigenen Zustand (player_id) zu nullen.
                # Dieser Fall kann eintreten, wenn der Spieler z.B. durch LEAVE_GAME entfernt wurde,
                # aber die Verbindung noch besteht und ein letztes Update versucht wird.
                if conn:
                    null_player_payload = {"type": "game_update", "player_id": None, "message": "Player removed from game."}
                    try:
                        conn.sendall(json.dumps(null_player_payload).encode('utf-8') + b'\n')
                        print(f"SERVER SEND: An P:{player_id_for_perspective} gesendet, dass er nicht mehr im Spiel ist (player_id: None).")
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        print(f"SERVER SEND (ERROR - NULL_PLAYER_PAYLOAD): P:{player_id_for_perspective} Verbindung verloren.")
                        # Conn kann hier nicht None gesetzt werden, da p_id nicht mehr in players ist
                else:
                    print(f"SERVER SEND (FATAL PRE-CHECK): Spieler {player_id_for_perspective} nicht in game_data.players und keine Verbindung.")
                return

            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return # Sollte durch obige Prüfung nicht mehr passieren

            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbekannter Status"))

            payload = {
                "type": "game_update",
                "player_id": player_id_for_perspective,
                "player_name": player_name_for_log,
                "role": p_role,
                "location": player_info.get("location"), 
                "confirmed_for_lobby": player_info.get("confirmed_for_lobby", False),
                "player_is_ready": player_info.get("is_ready", False),
                "player_status": player_info.get("status_ingame", "active"),
                "game_state": {
                    "status": current_game_status,
                    "status_display": current_status_display,
                    "game_time_left": int(game_data.get("game_end_time", 0) - time.time()) if game_data.get("game_end_time") and current_game_status == GAME_STATE_RUNNING else 0,
                    "hider_wait_time_left": int(game_data.get("hider_wait_end_time", 0) - time.time()) if game_data.get("hider_wait_end_time") and current_game_status == GAME_STATE_HIDER_WAIT else 0,
                    "game_over_message": game_data.get("game_over_message")
                },
                "lobby_players": get_active_lobby_players_data() if current_game_status == GAME_STATE_LOBBY else {},
                "all_players_status": get_all_players_public_status(),
                "hider_leaderboard": get_hider_leaderboard() if player_info.get("original_role") == "hider" or current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS] else None,
                "hider_location_update_imminent": player_info.get("has_pending_location_warning", False) if p_role == "hider" else False,
                "early_end_requests_count": len(game_data.get("early_end_requests", set())),
                "total_active_players_for_early_end": game_data.get("total_active_players_for_early_end", 0),
                "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set())
            }

            if p_role == "hider" and player_info.get("status_ingame") == "active" and player_info.get("task"):
                p_task_info = player_info["task"]
                payload["current_task"] = {
                    "id": p_task_info.get("id", "N/A"),
                    "description": p_task_info.get("description", "Keine Beschreibung"),
                    "points": p_task_info.get("points", 0),
                    "time_left_seconds": max(0, int(player_info.get("task_deadline", 0) - time.time())) if player_info.get("task_deadline") else 0
                }

            if p_role == "seeker":
                visible_hiders = {}
                current_players_copy = dict(game_data.get("players", {}))
                for h_id, h_info in current_players_copy.items():
                    if h_info.get("current_role") == "hider" and h_info.get("status_ingame") == "active" and h_info.get("location"):
                        visible_hiders[h_id] = {
                            "name": h_info.get("name", "Unbekannter Hider"),
                            "lat": h_info["location"][0], "lon": h_info["location"][1],
                            "timestamp": time.strftime("%H:%M:%S", time.localtime(h_info.get("last_location_timestamp", time.time())))
                        }
                payload["hider_locations"] = visible_hiders

                available_pu = []
                p_power_ups_used = player_info.get("power_ups_used_time", {})
                for pu_id, pu_data in POWER_UPS.items():
                    if time.time() - p_power_ups_used.get(pu_id, 0) > pu_data.get("cooldown", POWER_UP_COOLDOWN_SECONDS):
                        available_pu.append({"id": pu_id, "name": pu_data.get("name", "Unbekanntes Powerup")})
                payload["power_ups_available"] = available_pu
        
        if conn and payload: # Payload könnte leer sein, wenn der Spieler gerade entfernt wurde
            json_payload = json.dumps(payload)
            conn.sendall(json_payload.encode('utf-8') + b'\n')
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(f"SERVER SEND (ERROR - COMM): P:{player_id_for_perspective} ({player_name_for_log}): {e}.")
        with data_lock:
            if "players" in game_data and player_id_for_perspective in game_data["players"]:
                # Nur client_conn nullen, wenn es sich um die aktuelle Verbindung des Spielers handelt
                if game_data["players"][player_id_for_perspective].get("client_conn") == conn:
                    game_data["players"][player_id_for_perspective]["client_conn"] = None
    except Exception as e:
        print(f"SERVER SEND (ERROR - UNEXPECTED): P:{player_id_for_perspective} ({player_name_for_log}): {e}")
        import traceback
        traceback.print_exc()

def broadcast_full_game_state_to_all(exclude_pid=None):
    players_to_update_with_conn = []
    with data_lock:
        for pid, pinfo in game_data.get("players", {}).items():
            if pid != exclude_pid and pinfo.get("client_conn"):
                players_to_update_with_conn.append((pid, pinfo["client_conn"]))
    for p_id_to_update, conn_to_use in players_to_update_with_conn:
        send_data_to_one_client(conn_to_use, p_id_to_update)

def broadcast_server_text_notification(message_text, target_player_ids=None, role_filter=None):
    message_data = {"type": "server_text_notification", "message": message_text}
    json_message = json.dumps(message_data).encode('utf-8') + b'\n'
    players_to_notify = []
    with data_lock:
        player_pool = target_player_ids if target_player_ids else game_data.get("players", {}).keys()
        for p_id in player_pool:
            p_info = game_data.get("players", {}).get(p_id)
            if not p_info or not p_info.get("client_conn"): continue
            if role_filter and p_info.get("current_role") != role_filter: continue
            players_to_notify.append((p_id, p_info["client_conn"], p_info.get("name", "N/A")))

    for p_id, conn, name in players_to_notify:
        try:
            conn.sendall(json_message)
        except (ConnectionResetError, BrokenPipeError, OSError):
            print(f"SERVER TEXT_NOTIFY (ERROR): Verbindung zu P:{p_id} ({name}) verloren.")
            with data_lock:
                if "players" in game_data and p_id in game_data["players"]:
                    if game_data["players"][p_id].get("client_conn") == conn:
                        game_data["players"][p_id]["client_conn"] = None
        except Exception as e:
            print(f"SERVER TEXT_NOTIFY (ERROR): Unerwarteter Fehler bei P:{p_id} ({name}): {e}")

def check_game_conditions_and_end():
    with data_lock:
        current_game_status = game_data.get("status")
        if current_game_status != GAME_STATE_RUNNING: return False
        current_time = time.time()
        original_hiders_exist = False
        player_ids_to_check = list(game_data.get("players", {}).keys()) 

        for p_id in player_ids_to_check:
            p_info = game_data.get("players", {}).get(p_id) 
            if not p_info: continue

            if p_info.get("original_role") == "hider": original_hiders_exist = True
            if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                if p_info.get("task") and p_info.get("task_deadline") and current_time > p_info["task_deadline"]:
                    if p_id in game_data.get("players", {}): 
                        game_data["players"][p_id]["status_ingame"] = "failed_task"
                        game_data["players"][p_id]["task"] = None; game_data["players"][p_id]["task_deadline"] = None
                        broadcast_server_text_notification(f"Hider {p_info.get('name','N/A')} hat Aufgabe '{p_info.get('task',{}).get('description','N/A')}' NICHT rechtzeitig geschafft!")
        
        current_active_hiders = sum(1 for p_info_recheck in game_data.get("players", {}).values()
                                    if p_info_recheck.get("current_role") == "hider" and p_info_recheck.get("status_ingame") == "active")

        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 and any(p.get("confirmed_for_lobby") for p in game_data.get("players", {}).values()):
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Keine Hider im Spiel gestartet. Seeker gewinnen!"
            game_data["early_end_requests"].clear()
            return True

        if current_active_hiders == 0 and original_hiders_exist:
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Alle Hider ausgeschieden/gefangen. Seeker gewinnen!"
            game_data["early_end_requests"].clear()
            return True
        
        if game_data.get("game_end_time") and current_time > game_data["game_end_time"]:
            final_active_hiders_at_timeout = sum(1 for p_info_final in game_data.get("players", {}).values()
                                                 if p_info_final.get("current_role") == "hider" and p_info_final.get("status_ingame") == "active")
            game_data["status"] = GAME_STATE_HIDER_WINS if final_active_hiders_at_timeout > 0 else GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[game_data["status"]]
            game_data["game_over_message"] = "Zeit abgelaufen. " + ("Hider gewinnen!" if final_active_hiders_at_timeout > 0 else "Seeker gewinnen!")
            game_data["early_end_requests"].clear()
            return True
        return False

def handle_client_connection(conn, addr):
    player_id = None
    player_name_for_log = "Unbekannt_Init"
    action_for_log = "N/A"
    print(f"SERVER CONN: Neue Verbindung von {addr}.")
    try:
        buffer = ""
        while True:
            try:
                data_chunk = conn.recv(4096)
                if not data_chunk:
                    print(f"SERVER CONN ({addr[1]}): data_chunk leer. P:{player_id}, Name: {player_name_for_log}.")
                    break
                buffer += data_chunk.decode('utf-8')

                while '\n' in buffer:
                    message_str, buffer = buffer.split('\n', 1)
                    if not message_str.strip(): continue
                    message = json.loads(message_str)
                    action = message.get("action"); action_for_log = action

                    with data_lock:
                        current_game_status_in_handler = game_data.get("status")

                        if action == "JOIN_GAME" and player_id is None:
                            if current_game_status_in_handler in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                                print("SERVER: JOIN_GAME erhalten, Spiel war beendet. Resette Spiel komplett.")
                                reset_game_to_initial_state() 
                                current_game_status_in_handler = game_data.get("status")
                            
                            if current_game_status_in_handler != GAME_STATE_LOBBY:
                                conn.sendall(json.dumps({"type":"error", "message":"Spiel läuft bereits oder ist nicht in der Lobby."}).encode('utf-8') + b'\n')
                                # Verbindung hier nicht schließen, Client könnte es erneut versuchen, wenn Lobby wieder offen ist.
                                # Client muss selbst entscheiden, ob er die Verbindung trennt oder auf /status pollt.
                                # Für diesen speziellen Fehler (Spiel läuft) ist es aber sinnvoll, die Verbindung zu schließen,
                                # damit der Client nicht unnötig verbunden bleibt.
                                print(f"SERVER: JOIN_GAME abgelehnt (Spiel läuft/nicht Lobby) für {addr}. Verbindung wird geschlossen.")
                                return # Schließt den Handler-Thread für diese Verbindung
                            
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            p_role = message.get("role", "hider")
                            if p_role not in ["hider", "seeker"]: p_role = "hider"
                            player_name_for_log = p_name
                            
                            # Eindeutige Player ID generieren
                            base_id = str(addr[1]) + "_" + str(random.randint(100,999)) # Mehr Eindeutigkeit
                            id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}):
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate
                            
                            game_data.setdefault("players", {})[player_id] = {
                                "addr": addr, "name": p_name, "original_role": p_role, "current_role": p_role,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": False, "is_ready": False, "status_ingame": "active", "points": 0,
                                "power_ups_used_time": {}, "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None
                            }
                            print(f"SERVER JOIN-PLAYER-CREATED: {p_name} ({player_id}) von {addr}.")
                            send_data_to_one_client(conn, player_id)
                            broadcast_full_game_state_to_all(exclude_pid=player_id)
                            continue # Zurück zum Anfang der inneren while-Schleife für nächste Nachricht

                        if not player_id or player_id not in game_data.get("players", {}):
                            # Wenn player_id null ist (z.B. nach LEAVE_GAME) ODER wenn die player_id aus irgendeinem Grund
                            # nicht mehr in game_data.players ist (z.B. Server-Reset, Timeout-Entfernung),
                            # dann ist der Client nicht mehr authentifiziert für weitere Aktionen.
                            print(f"SERVER: P:{player_id} (Name: {player_name_for_log}) nicht authentifiziert oder nicht mehr im Spiel für Aktion '{action}'.")
                            try:
                                conn.sendall(json.dumps({"type":"error", "message":"Nicht authentifiziert oder aus Spiel entfernt. Bitte neu beitreten."}).encode('utf-8') + b'\n')
                            except: pass # Verbindung könnte schon weg sein
                            # Es ist wichtig, hier die Verbindung zu schließen oder den player_id zu nullen,
                            # damit der Client nicht endlos Nachrichten sendet, die abgelehnt werden.
                            # Da der Client sich evtl. neu verbinden will, wird die Verbindung hier beendet.
                            return # Schließt den Handler-Thread für diese Verbindung
                        
                        current_player_data = game_data["players"][player_id] # Sicher, da oben geprüft
                        current_player_data["last_seen"] = time.time()
                        if current_player_data.get("client_conn") != conn: # Falls sich die Verbindung geändert hat (Reconnect)
                            current_player_data["client_conn"] = conn
                        player_name_for_log = current_player_data.get("name", "N/A")


                        if action == "CONFIRM_LOBBY_JOIN": 
                            if current_game_status_in_handler == GAME_STATE_LOBBY:
                                current_player_data["confirmed_for_lobby"] = True
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "SET_READY": 
                            if current_game_status_in_handler == GAME_STATE_LOBBY and current_player_data.get("confirmed_for_lobby"):
                                current_player_data["is_ready"] = message.get("ready_status") == True
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "UPDATE_LOCATION":
                            lat, lon = message.get("lat"), message.get("lon")
                            accuracy = message.get("accuracy") 
                            if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
                                current_player_data["location"] = [lat, lon, accuracy] 
                                current_player_data["last_location_timestamp"] = time.time()
                                
                                if current_player_data.get("has_pending_location_warning"):
                                    if time.time() > current_player_data.get("warning_sent_time", 0):
                                         current_player_data["last_location_update_after_warning"] = time.time()
                                # Nur an diesen Client senden, Broadcast erfolgt durch game_logic seltener
                                send_data_to_one_client(conn, player_id) 
                        
                        elif action == "TASK_COMPLETE": 
                            status_changed = False
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active" and current_player_data.get("task"):
                                task_details = current_player_data["task"]
                                if time.time() <= current_player_data.get("task_deadline", 0):
                                    current_player_data["points"] += task_details.get("points", 0)
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe erledigt!")
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None
                                    assign_task_to_hider(player_id); status_changed = True
                                else:
                                    current_player_data["status_ingame"] = "failed_task" # Aufgabe zu spät
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None # Aufgabe entfernen
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe zu spät eingereicht!")
                                    status_changed = True # Status hat sich geändert
                            if status_changed:
                                if check_game_conditions_and_end(): pass # Prüfe, ob Spielende
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "CATCH_HIDER": 
                            hider_id_to_catch = message.get("hider_id_to_catch"); caught = False
                            if current_player_data["current_role"] == "seeker" and hider_id_to_catch in game_data.get("players", {}):
                                hider_player_data = game_data["players"][hider_id_to_catch]
                                if hider_player_data.get("current_role") == "hider" and hider_player_data.get("status_ingame") == "active":
                                    hider_player_data["current_role"] = "seeker"; hider_player_data["status_ingame"] = "caught"
                                    hider_player_data["task"], hider_player_data["task_deadline"] = None, None
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Hider {hider_player_data.get('name','N/A')} gefangen!")
                                    caught = True
                            if caught:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "USE_POWERUP": 
                            powerup_id_to_use = message.get("powerup_id"); powerup_used_successfully = False
                            if current_player_data["current_role"] == "seeker" and powerup_id_to_use in POWER_UPS:
                                pu_info = POWER_UPS[powerup_id_to_use]
                                if time.time() - current_player_data.get("power_ups_used_time", {}).get(powerup_id_to_use, 0) > pu_info.get("cooldown", POWER_UP_COOLDOWN_SECONDS):
                                    current_player_data.setdefault("power_ups_used_time", {})[powerup_id_to_use] = time.time()
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Power-Up '{pu_info.get('name','N/A')}' eingesetzt!")
                                    powerup_used_successfully = True
                            if powerup_used_successfully: broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN":
                            print(f"SERVER: Spieler {player_name_for_log} ({player_id}) verlässt Spiel (LEAVE_GAME_AND_GO_TO_JOIN).")
                            if player_id in game_data["players"]: # Sicherstellen, dass Spieler noch existiert
                                del game_data["players"][player_id]
                            
                            # Spieler-ID für diese Verbindung ungültig machen
                            # damit keine weiteren Aktionen unter dieser ID möglich sind.
                            player_id_that_left = player_id 
                            player_id = None 
                            
                            # Sende Bestätigung an den Client (er wird durch game_update mit player_id=None auch merken, dass er raus ist)
                            try:
                                conn.sendall(json.dumps({"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}).encode('utf-8') + b'\n')
                            except: pass # Verbindung könnte schon weg sein
                            
                            broadcast_full_game_state_to_all() # Andere Spieler informieren
                            
                            # Da player_id jetzt None ist, wird die äußere "if not player_id..."-Bedingung
                            # beim nächsten Nachrichteneingang greifen und den Handler-Thread beenden.
                            # Oder wir beenden ihn hier direkt, da der Client ja explizit weg will.
                            print(f"SERVER: Verbindung für P:{player_id_that_left} (Name: {player_name_for_log}) wird nach LEAVE_GAME geschlossen.")
                            return # Beendet den Handler-Thread für diese Verbindung

                        elif action == "REQUEST_EARLY_ROUND_END":
                            if current_game_status_in_handler == GAME_STATE_RUNNING and \
                               current_player_data.get("status_ingame") == "active" and \
                               current_player_data.get("confirmed_for_lobby"):
                                
                                game_data.setdefault("early_end_requests", set()).add(player_id)
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                                print(f"SERVER: Spieler {player_name_for_log} ({player_id}) beantragt frühes Rundenende. Stand: {len(game_data['early_end_requests'])}/{game_data['total_active_players_for_early_end']}")
                                
                                # Prüfe Konsens nur wenn es überhaupt aktive Spieler gibt für die Abstimmung
                                if game_data["total_active_players_for_early_end"] > 0 and \
                                   len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    print("SERVER: Konsens für frühes Rundenende erreicht!")
                                    # Standardmäßig gewinnen Seeker bei frühem Ende, kann angepasst werden
                                    game_data["status"] = GAME_STATE_SEEKER_WINS 
                                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
                                    game_data["game_over_message"] = "Spiel durch Konsens der Spieler vorzeitig beendet. Seeker gewinnen!"
                                    game_data["early_end_requests"].clear() 
                                    if check_game_conditions_and_end(): pass 
                                
                                broadcast_full_game_state_to_all()
                            else:
                                send_data_to_one_client(conn, player_id)


            except json.JSONDecodeError as e:
                print(f"SERVER JSON ERROR ({addr[1]}): P:{player_id}. Msg: '{message_str if 'message_str' in locals() else 'N/A'}'. Err: {e}"); buffer = ""
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"SERVER CONN ERROR ({addr[1]}): P:{player_id}. Err: {e}"); break 
            except Exception as e_inner_loop:
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr[1]}): P:{player_id}. Action: {action_for_log}. Err: {e_inner_loop}"); import traceback; traceback.print_exc()
    
    except Exception as e_outer_handler: 
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr[1]}): P:{player_id}. Err: {e_outer_handler}"); import traceback; traceback.print_exc()
    finally:
        print(f"SERVER CLEANUP ({addr[1]}): P:{player_id}, Name: {player_name_for_log}. Verbindung wird geschlossen.")
        player_affected_by_disconnect = False
        with data_lock:
            if player_id and player_id in game_data.get("players", {}):
                # Nur `client_conn` auf None setzen, wenn es DIESE Verbindung war.
                # Der Spieler könnte sich bereits mit einer neuen Verbindung wieder verbunden haben.
                if game_data["players"][player_id].get("client_conn") is conn:
                    game_data["players"][player_id]["client_conn"] = None
                    player_affected_by_disconnect = True
                    print(f"SERVER: Spieler {player_name_for_log} ({player_id}) client_conn auf None gesetzt (Socket {conn.fileno() if conn else 'N/A'}).")
                else:
                    print(f"SERVER: Spieler {player_name_for_log} ({player_id}) hatte bereits eine andere/keine client_conn.")
            elif not player_id: 
                 print(f"SERVER: Spieler {player_name_for_log} (ehemals ID, jetzt None) hatte die Verbindung aktiv beendet oder wurde entfernt.")

        if player_affected_by_disconnect:
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end():
                    print(f"SERVER: Spiel beendet nach Client-Disconnect/Cleanup von {player_name_for_log}.")
            broadcast_full_game_state_to_all()

        if conn:
            try: conn.close()
            except: pass

def game_logic_thread():
    previous_game_status_for_logic = None
    while True:
        time.sleep(1)
        game_ended_this_tick = False
        broadcast_needed_due_to_time_or_state_change = False
        
        with data_lock:
            current_time = time.time()
            current_game_status = game_data.get("status")
            if current_game_status is None: 
                reset_game_to_initial_state() # Sicherheitsnetz, falls game_data leer ist
                current_game_status = game_data.get("status")


            if previous_game_status_for_logic != current_game_status:
                broadcast_needed_due_to_time_or_state_change = True
                previous_game_status_for_logic = current_game_status
                if current_game_status == GAME_STATE_RUNNING: 
                    game_data["early_end_requests"] = set() 
                    game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()


            if current_game_status == GAME_STATE_LOBBY:
                active_lobby_player_count = 0; all_in_active_lobby_ready = True
                current_players_in_lobby = game_data.get("players", {})
                if not current_players_in_lobby: all_in_active_lobby_ready = False
                else:
                    non_ready_players = []
                    for p_info_check in current_players_in_lobby.values():
                        if p_info_check.get("confirmed_for_lobby", False):
                            active_lobby_player_count += 1
                            if not p_info_check.get("is_ready", False):
                                all_in_active_lobby_ready = False
                                non_ready_players.append(p_info_check.get("name", "Unbekannt"))
                    if active_lobby_player_count == 0: all_in_active_lobby_ready = False
                
                MIN_PLAYERS_TO_START = 1 
                if all_in_active_lobby_ready and active_lobby_player_count >= MIN_PLAYERS_TO_START:
                    print(f"LOGIC LOBBY: Alle {active_lobby_player_count} Spieler bereit. Starte Hider-Wartezeit...")
                    game_data["status"] = GAME_STATE_HIDER_WAIT
                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_HIDER_WAIT]
                    game_data["hider_wait_end_time"] = current_time + HIDER_START_DELAY_SECONDS
                    broadcast_needed_due_to_time_or_state_change = True


            elif current_game_status == GAME_STATE_HIDER_WAIT:
                if game_data.get("hider_wait_end_time"):
                    if current_time >= game_data["hider_wait_end_time"]:
                        print("LOGIC HIDER_WAIT: Zeit abgelaufen. Spiel startet!")
                        game_data["status"] = GAME_STATE_RUNNING
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS
                        game_data["next_seeker_hider_location_broadcast_time"] = current_time + game_data["current_hider_location_update_interval"]
                        game_data["early_end_requests"].clear() 
                        game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                        
                        for p_id_task, p_info_task in game_data.get("players", {}).items():
                            if p_info_task.get("current_role") == "hider" and p_info_task.get("confirmed_for_lobby") and p_info_task.get("status_ingame") == "active":
                                assign_task_to_hider(p_id_task)
                        
                        for p_id_event, p_info_event in game_data.get("players", {}).items():
                            if p_info_event.get("client_conn"):
                                event_payload = {"type": "game_event", "event_name": "game_started"}
                                try: p_info_event["client_conn"].sendall(json.dumps(event_payload).encode('utf-8') + b'\n')
                                except: 
                                    if "players" in game_data and p_id_event in game_data["players"] and game_data["players"][p_id_event].get("client_conn") == p_info_event.get("client_conn"):
                                        game_data["players"][p_id_event]["client_conn"] = None
                        broadcast_needed_due_to_time_or_state_change = True
                    elif int(game_data["hider_wait_end_time"] - current_time) % 3 == 0: 
                        broadcast_needed_due_to_time_or_state_change = True

            elif current_game_status == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): 
                    game_ended_this_tick = True 
                else: 
                    next_broadcast_time = game_data.get("next_seeker_hider_location_broadcast_time", 0)
                    warning_time_trigger = next_broadcast_time - HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS
                    
                    if not game_data.get("hider_warning_active_for_current_cycle", False) and \
                       current_time >= warning_time_trigger and current_time < next_broadcast_time:
                        
                        game_data["hider_warning_active_for_current_cycle"] = True
                        hiders_needing_warning_update = False
                        for p_id, p_info in game_data.get("players", {}).items():
                            if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                                if not p_info.get("has_pending_location_warning"): 
                                    p_info["has_pending_location_warning"] = True
                                    p_info["warning_sent_time"] = current_time
                                    p_info["last_location_update_after_warning"] = 0 
                                    hiders_needing_warning_update = True
                                    if p_info.get("client_conn"):
                                        event_payload_warn = {"type": "game_event", "event_name": "hider_location_update_due"}
                                        try:
                                            p_info["client_conn"].sendall(json.dumps(event_payload_warn).encode('utf-8') + b'\n')
                                        except: 
                                            if "players" in game_data and p_id in game_data["players"] and game_data["players"][p_id].get("client_conn") == p_info.get("client_conn"):
                                                game_data["players"][p_id]["client_conn"] = None
                        if hiders_needing_warning_update:
                             broadcast_needed_due_to_time_or_state_change = True 

                    if current_time >= next_broadcast_time:
                        game_data["hider_warning_active_for_current_cycle"] = False 
                        active_hiders_who_failed_update_names = []
                        
                        player_list_copy = list(game_data.get("players", {}).items()) 
                        for p_id_h, p_info_h in player_list_copy:
                            # Check if player still exists in game_data as they might have left
                            if p_id_h not in game_data.get("players", {}): continue
                            
                            if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                if p_info_h.get("has_pending_location_warning"): 
                                    if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                        game_data["players"][p_id_h]["status_ingame"] = "failed_loc_update"
                                        game_data["players"][p_id_h]["task"] = None; game_data["players"][p_id_h]["task_deadline"] = None
                                        active_hiders_who_failed_update_names.append(p_info_h.get('name', 'Unbekannt'))
                                        print(f"SERVER DISQUALIFY: Hider {p_info_h.get('name')} nicht rechtzeitig aktualisiert.")
                                game_data["players"][p_id_h]["has_pending_location_warning"] = False 

                        if active_hiders_who_failed_update_names:
                             broadcast_server_text_notification(f"Disqualifiziert (kein Standort-Update): {', '.join(active_hiders_who_failed_update_names)}")
                             # Re-iterate to send specific event to disqualified hiders' connections if they still exist
                             for p_id_disq_event, p_info_disq_event in game_data.get("players", {}).items():
                                 if p_info_disq_event.get("name") in active_hiders_who_failed_update_names and \
                                    p_info_disq_event.get("status_ingame") == "failed_loc_update" and \
                                    p_info_disq_event.get("client_conn"):
                                     disq_event = {"type": "game_event", "event_name": "hider_disqualified_loc", "player_name": p_info_disq_event.get("name")}
                                     try: p_info_disq_event["client_conn"].sendall(json.dumps(disq_event).encode('utf-8') + b'\n')
                                     except: 
                                         if "players" in game_data and p_id_disq_event in game_data["players"] and game_data["players"][p_id_disq_event].get("client_conn") == p_info_disq_event.get("client_conn"):
                                             game_data["players"][p_id_disq_event]["client_conn"] = None


                        time_since_start = current_time - game_data.get("game_start_time_actual", current_time)
                        progress = min(1.0, time_since_start / GAME_DURATION_SECONDS if GAME_DURATION_SECONDS > 0 else 0)
                        current_interval = MAX_HIDER_LOCATION_UPDATE_INTERVAL - \
                            (MAX_HIDER_LOCATION_UPDATE_INTERVAL - MIN_HIDER_LOCATION_UPDATE_INTERVAL) * progress
                        game_data["current_hider_location_update_interval"] = current_interval
                        game_data["next_seeker_hider_location_broadcast_time"] = current_time + current_interval
                        
                        for p_id_s, p_info_s in game_data.get("players", {}).items():
                            if p_info_s.get("current_role") == "seeker" and p_info_s.get("client_conn"):
                                event_payload_seeker = {"type": "game_event", "event_name": "seeker_locations_updated"}
                                try: p_info_s["client_conn"].sendall(json.dumps(event_payload_seeker).encode('utf-8') + b'\n')
                                except: 
                                     if "players" in game_data and p_id_s in game_data["players"] and game_data["players"][p_id_s].get("client_conn") == p_info_s.get("client_conn"):
                                        game_data["players"][p_id_s]["client_conn"] = None
                        
                        print(f"SERVER LOGIC: Seeker-Standort-Update. Nächstes in {current_interval:.0f}s.")
                        broadcast_needed_due_to_time_or_state_change = True 

                    if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 : 
                        broadcast_needed_due_to_time_or_state_change = True
                    
                    if int(current_time) % 10 == 0 : 
                        new_active_count = count_active_players_for_early_end()
                        if game_data.get("total_active_players_for_early_end") != new_active_count:
                            game_data["total_active_players_for_early_end"] = new_active_count
                            broadcast_needed_due_to_time_or_state_change = True


            elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                if game_data.get("game_end_time"): 
                    time_since_game_end = current_time - game_data.get("game_end_time", current_time)
                    # Send updates for a short period after game end, then less frequently or stop
                    if time_since_game_end < 30 and int(current_time) % 5 == 0: # More frequent for first 30s
                         broadcast_needed_due_to_time_or_state_change = True
                    elif time_since_game_end < 120 and int(current_time) % 15 == 0: # Less frequent up to 2 mins
                         broadcast_needed_due_to_time_or_state_change = True
                    elif previous_game_status_for_logic != current_game_status : # Always send on first state change to game_over
                        broadcast_needed_due_to_time_or_state_change = True


        if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
            if game_ended_this_tick: # This means check_game_conditions_and_end changed the state
                 print(f"LOGIC: Spiel beendet durch check_game_conditions_and_end. Finaler Status: {game_data.get('status_display', 'N/A')}.")
            elif broadcast_needed_due_to_time_or_state_change: # Other reasons for broadcast
                 print(f"LOGIC: Broadcast ausgelöst. Aktueller Status: {game_data.get('status_display', 'N/A')}. Zeit bis Spielende: {int(game_data.get('game_end_time', 0) - time.time()) if game_data.get('game_end_time') else 'N/A'}s")
            broadcast_full_game_state_to_all()

def main_server():
    reset_game_to_initial_state() 
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"!!! SERVER FATAL: Fehler beim Binden des Sockets an {HOST}:{PORT}: {e}. Läuft der Server bereits? !!!")
        return
    server_socket.listen()
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")

    threading.Thread(target=game_logic_thread, daemon=True).start()
    print("SERVER: Game Logic Thread gestartet.")

    try:
        while True:
            conn, addr = server_socket.accept()
            thread = threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        print("SERVER: KeyboardInterrupt empfangen. Server wird heruntergefahren.")
    except Exception as e:
        print(f"SERVER FATAL: Unerwarteter Fehler in der Haupt-Serverschleife: {e}")
        import traceback; traceback.print_exc()
    finally:
        print("SERVER: Schließe Server-Socket...")
        server_socket.close()
        print("SERVER: Server-Socket geschlossen. Programm beendet.")

if __name__ == "__main__":
    main_server()