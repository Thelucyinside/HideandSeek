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
                print(f"SERVER SEND (FATAL PRE-CHECK): Spieler {player_id_for_perspective} nicht in game_data.players.")
                return
            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return

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
        
        if conn and payload:
            json_payload = json.dumps(payload)
            conn.sendall(json_payload.encode('utf-8') + b'\n')
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(f"SERVER SEND (ERROR - COMM): P:{player_id_for_perspective} ({player_name_for_log}): {e}.")
        with data_lock:
            if "players" in game_data and player_id_for_perspective in game_data["players"]:
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
        player_ids_to_check = list(game_data.get("players", {}).keys()) # Kopie für Iteration

        for p_id in player_ids_to_check:
            p_info = game_data.get("players", {}).get(p_id) # Erneutes Holen, da Zustand sich ändern kann
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

        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 :
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
                                reset_game_to_initial_state() # Komplett-Reset
                                current_game_status_in_handler = game_data.get("status")
                            
                            if current_game_status_in_handler != GAME_STATE_LOBBY:
                                conn.sendall(json.dumps({"type":"error", "message":"Spiel läuft bereits oder ist nicht in der Lobby."}).encode('utf-8') + b'\n')
                                return 
                            
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            p_role = message.get("role", "hider")
                            if p_role not in ["hider", "seeker"]: p_role = "hider"
                            player_name_for_log = p_name
                            
                            base_id = str(addr[1]); id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}):
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate
                            
                            game_data["players"][player_id] = {
                                "addr": addr, "name": p_name, "original_role": p_role, "current_role": p_role,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": False, "is_ready": False, "status_ingame": "active", "points": 0,
                                "power_ups_used_time": {}, "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None
                            }
                            print(f"SERVER JOIN-PLAYER-CREATED: {p_name} ({player_id}).")
                            send_data_to_one_client(conn, player_id)
                            broadcast_full_game_state_to_all(exclude_pid=player_id)
                            continue

                        if not player_id or player_id not in game_data.get("players", {}):
                            try: conn.sendall(json.dumps({"type":"error", "message":"Nicht authentifiziert."}).encode('utf-8') + b'\n')
                            except: pass
                            continue
                        
                        # current_player_data wird hier geholt, um sicherzustellen, dass es aktuell ist.
                        # Es könnte sein, dass der Spieler zwischenzeitlich entfernt wurde (z.B. durch LEAVE_GAME)
                        current_player_data_check = game_data.get("players", {}).get(player_id)
                        if not current_player_data_check:
                            print(f"SERVER: Spieler {player_id} nicht mehr in game_data.players. Aktion '{action}' wird ignoriert.")
                            # Optional: Client benachrichtigen, dass er nicht mehr Teil des Spiels ist
                            try:
                                conn.sendall(json.dumps({"type":"error", "message":"Du bist nicht mehr Teil des aktuellen Spiels."}).encode('utf-8') + b'\n')
                            except: pass
                            player_id = None # Spieler-ID für diese Verbindung ungültig machen
                            break # Breche innere while-Schleife, um Verbindung ggf. neu zu bewerten
                        
                        current_player_data = current_player_data_check # Nun sicher, dass der Spieler existiert
                        current_player_data["last_seen"] = time.time()
                        if current_player_data.get("client_conn") != conn: current_player_data["client_conn"] = conn
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
                                    current_player_data["status_ingame"] = "failed_task"
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe zu spät eingereicht!")
                                    status_changed = True
                            if status_changed:
                                if check_game_conditions_and_end(): pass
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
                            print(f"SERVER: Spieler {player_name_for_log} ({player_id}) verlässt Spiel und geht zum Join-Screen.")
                            if player_id in game_data["players"]:
                                del game_data["players"][player_id]
                                # Sende Bestätigung an Client, dass er entfernt wurde (implizit durch nächstes Update ohne seine ID)
                                # oder sende eine spezielle Nachricht
                                try:
                                    conn.sendall(json.dumps({"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}).encode('utf-8') + b'\n')
                                except: pass
                            player_id = None # Wichtig: Diese Verbindung ist nicht mehr diesem Spieler zugeordnet
                            broadcast_full_game_state_to_all() # Andere Spieler informieren
                            break # Breche innere Message-Loop, Client-Handler schließt dann Verbindung

                        elif action == "REQUEST_EARLY_ROUND_END":
                            if current_game_status_in_handler == GAME_STATE_RUNNING and \
                               current_player_data.get("status_ingame") == "active" and \
                               current_player_data.get("confirmed_for_lobby"): # Muss im Spiel sein
                                
                                game_data.setdefault("early_end_requests", set()).add(player_id)
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                                print(f"SERVER: Spieler {player_name_for_log} ({player_id}) beantragt frühes Rundenende. Stand: {len(game_data['early_end_requests'])}/{game_data['total_active_players_for_early_end']}")
                                
                                if game_data["total_active_players_for_early_end"] > 0 and \
                                   len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    print("SERVER: Konsens für frühes Rundenende erreicht!")
                                    game_data["status"] = GAME_STATE_SEEKER_WINS # Oder eine andere Logik
                                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
                                    game_data["game_over_message"] = "Spiel durch Konsens der Spieler beendet. Seeker gewinnen!"
                                    game_data["early_end_requests"].clear() # Reset für nächste Runde
                                    if check_game_conditions_and_end(): pass # Sollte hier direkt true sein
                                
                                broadcast_full_game_state_to_all()
                            else:
                                send_data_to_one_client(conn, player_id) # Nur eigenen Status senden


            except json.JSONDecodeError as e:
                print(f"SERVER JSON ERROR ({addr[1]}): P:{player_id}. Msg: '{message_str if 'message_str' in locals() else 'N/A'}'. Err: {e}"); buffer = ""
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"SERVER CONN ERROR ({addr[1]}): P:{player_id}. Err: {e}"); break # Äußere Schleife verlassen
            except Exception as e_inner_loop:
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr[1]}): P:{player_id}. Action: {action_for_log}. Err: {e_inner_loop}"); import traceback; traceback.print_exc()
    
    except Exception as e_outer_handler: # Fängt Fehler in der äußeren while True Schleife (sollte nicht vorkommen)
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr[1]}): P:{player_id}. Err: {e_outer_handler}"); import traceback; traceback.print_exc()
    finally:
        print(f"SERVER CLEANUP ({addr[1]}): P:{player_id}, Name: {player_name_for_log}.")
        player_affected_by_disconnect = False
        with data_lock:
            # Wenn player_id noch gesetzt ist (d.h. nicht durch LEAVE_GAME genullt) und der Spieler existiert
            if player_id and player_id in game_data.get("players", {}):
                player_info_at_cleanup = game_data["players"][player_id]
                if player_info_at_cleanup.get("client_conn") is conn:
                    player_info_at_cleanup["client_conn"] = None
                    player_affected_by_disconnect = True
                    print(f"SERVER: Spieler {player_name_for_log} ({player_id}) Verbindung (client_conn) auf None gesetzt.")
            elif not player_id: # Spieler hat aktiv verlassen oder wurde entfernt
                 print(f"SERVER: Spieler {player_name_for_log} (ehemals {player_id if player_id else 'N/A'}) hatte die Verbindung bereits aufgelöst.")


        if player_affected_by_disconnect:
            # Prüfen, ob das Spiel durch den Disconnect beendet werden muss
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end():
                    print(f"SERVER: Spiel beendet nach Client-Disconnect/Cleanup von {player_name_for_log}.")
            broadcast_full_game_state_to_all() # Informiere andere über den Status des disconnected Spielers

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
            if current_game_status is None: continue # Passiert nur, wenn game_data komplett leer ist

            if previous_game_status_for_logic != current_game_status:
                broadcast_needed_due_to_time_or_state_change = True
                previous_game_status_for_logic = current_game_status
                if current_game_status == GAME_STATE_RUNNING: # Wenn Spiel neu startet
                    game_data["early_end_requests"] = set() # Reset für neue Runde
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
                # elif int(current_time) % 5 == 0 and non_ready_players: # Optional: Log which players are not ready
                #     print(f"LOGIC LOBBY: Warten auf Bereitschaft von: {', '.join(non_ready_players)}")


            elif current_game_status == GAME_STATE_HIDER_WAIT:
                if game_data.get("hider_wait_end_time"):
                    if current_time >= game_data["hider_wait_end_time"]:
                        print("LOGIC HIDER_WAIT: Zeit abgelaufen. Spiel startet!")
                        game_data["status"] = GAME_STATE_RUNNING
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS
                        game_data["next_seeker_hider_location_broadcast_time"] = current_time + game_data["current_hider_location_update_interval"]
                        game_data["early_end_requests"].clear() # Sicherstellen, dass es leer ist
                        game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                        
                        for p_id_task, p_info_task in game_data.get("players", {}).items():
                            if p_info_task.get("current_role") == "hider" and p_info_task.get("confirmed_for_lobby") and p_info_task.get("status_ingame") == "active":
                                assign_task_to_hider(p_id_task)
                        
                        for p_id_event, p_info_event in game_data.get("players", {}).items():
                            if p_info_event.get("client_conn"):
                                event_payload = {"type": "game_event", "event_name": "game_started"}
                                try: p_info_event["client_conn"].sendall(json.dumps(event_payload).encode('utf-8') + b'\n')
                                except: 
                                    if p_info_event.get("client_conn"): p_info_event["client_conn"] = None
                        broadcast_needed_due_to_time_or_state_change = True
                    elif int(game_data["hider_wait_end_time"] - current_time) % 3 == 0: 
                        broadcast_needed_due_to_time_or_state_change = True

            elif current_game_status == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): # Dies kann den Status ändern
                    game_ended_this_tick = True # Flag setzen, damit Broadcast am Ende sicher erfolgt
                else: # Spiel läuft noch, weiter mit normaler Logik
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
                                            if p_info.get("client_conn"): p_info["client_conn"] = None
                        if hiders_needing_warning_update:
                             broadcast_needed_due_to_time_or_state_change = True 

                    if current_time >= next_broadcast_time:
                        game_data["hider_warning_active_for_current_cycle"] = False 
                        active_hiders_who_failed_update_names = []
                        
                        player_list_copy = list(game_data.get("players", {}).items()) # Kopie für sichere Iteration
                        for p_id_h, p_info_h in player_list_copy:
                            if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                if p_info_h.get("has_pending_location_warning"): 
                                    if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                        game_data["players"][p_id_h]["status_ingame"] = "failed_loc_update"
                                        game_data["players"][p_id_h]["task"] = None; game_data["players"][p_id_h]["task_deadline"] = None
                                        active_hiders_who_failed_update_names.append(p_info_h.get('name', 'Unbekannt'))
                                        print(f"SERVER DISQUALIFY: Hider {p_info_h.get('name')} nicht rechtzeitig aktualisiert.")
                                game_data["players"][p_id_h]["has_pending_location_warning"] = False # Reset für den Spieler

                        if active_hiders_who_failed_update_names:
                             broadcast_server_text_notification(f"Disqualifiziert (kein Standort-Update): {', '.join(active_hiders_who_failed_update_names)}")
                             for p_id_disq, p_info_disq in player_list_copy: # Verwende die Kopie
                                 if p_info_disq.get("name") in active_hiders_who_failed_update_names and p_info_disq.get("client_conn"):
                                     disq_event = {"type": "game_event", "event_name": "hider_disqualified_loc", "player_name": p_info_disq.get("name")}
                                     try: p_info_disq["client_conn"].sendall(json.dumps(disq_event).encode('utf-8') + b'\n')
                                     except: 
                                         if p_info_disq.get("client_conn"): game_data["players"][p_id_disq]["client_conn"] = None


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
                                     if p_info_s.get("client_conn"): p_info_s["client_conn"] = None
                        
                        print(f"SERVER LOGIC: Seeker-Standort-Update. Nächstes in {current_interval:.0f}s.")
                        broadcast_needed_due_to_time_or_state_change = True 

                    if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 : 
                        broadcast_needed_due_to_time_or_state_change = True
                    
                    # Update der Zählung für early_end periodisch, falls Spieler ausscheiden
                    if int(current_time) % 10 == 0 : # Alle 10 Sekunden
                        new_active_count = count_active_players_for_early_end()
                        if game_data.get("total_active_players_for_early_end") != new_active_count:
                            game_data["total_active_players_for_early_end"] = new_active_count
                            broadcast_needed_due_to_time_or_state_change = True


            elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                if game_data.get("game_end_time"): 
                    time_since_game_end = current_time - game_data.get("game_end_time", current_time)
                    if time_since_game_end < 120 and int(current_time) % 15 == 0:
                         broadcast_needed_due_to_time_or_state_change = True
                    elif previous_game_status_for_logic != current_game_status : 
                        broadcast_needed_due_to_time_or_state_change = True


        if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
            if game_ended_this_tick:
                 print(f"LOGIC: Spiel beendet/Statusänderung. Finaler Status: {game_data.get('status_display', 'N/A')}.")
            broadcast_full_game_state_to_all()

def main_server():
    reset_game_to_initial_state() # Starte mit einem sauberen Zustand
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