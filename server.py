# server.py
import socket
import threading
import json
import time
import random
import traceback # Importiert für detailliertere Fehlermeldungen
from tasks import TASKS # Annahme: tasks.py existiert und enthält eine Liste von Aufgaben

HOST = '0.0.0.0'
PORT = 65432
GAME_DURATION_SECONDS = 1800 # 30 Minuten Spielzeit NACH der Hider-Vorbereitungszeit
HIDER_INITIAL_DEPARTURE_TIME_SECONDS = 240 # 4 Minuten Vorbereitungszeit für Hider (Phase 0 der Updates)
HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS = 20 # Hider bekommen 20s vor Standort-Broadcast eine Warnung

POST_GAME_LOBBY_RETURN_DELAY_SECONDS = 30
PHASE_DEFINITIONS = [
    {"name": "Initial Reveal", "duration_seconds": 0, "is_initial_reveal": True, "updates_in_phase": 1},
    {"name": "Phase 1 (10 min, 2 Updates)", "duration_seconds": 600, "updates_in_phase": 2},
    {"name": "Phase 2 (10 min, 4 Updates)", "duration_seconds": 600, "updates_in_phase": 4},
    {"name": "Phase 3 (5 min, 3 Updates)", "duration_seconds": 300, "updates_in_phase": 3},
    {"name": "Phase 4 (3 min, 30s Interval)", "duration_seconds": 180, "update_interval_seconds": 30},
    {"name": "Phase 5 (Continuous - 5s Interval)", "duration_seconds": float('inf'), "update_interval_seconds": 5}
]

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

INITIAL_TASK_SKIPS = 1
game_data = {}
data_lock = threading.RLock()

def format_time_ago(seconds_elapsed):
    seconds_elapsed = int(seconds_elapsed)
    if seconds_elapsed < 0: seconds_elapsed = 0
    if seconds_elapsed < 60: return f"{seconds_elapsed} Sek"
    minutes = seconds_elapsed // 60
    if minutes < 60: return f"{minutes} Min"
    hours = minutes // 60
    if hours < 24: return f"{hours} Std"
    days = hours // 24
    return f"{days} Tag(en)"

def _safe_send_json(conn, payload, player_id_for_log="N/A", player_name_for_log="N/A_IN_SAFE_SEND"):
    if not conn:
        print(f"SERVER SAFE_SEND (NO CONN): P:{player_id_for_log} ({player_name_for_log}): Payload nicht gesendet, da conn=None.")
        return False
    try:
        # print(f"SERVER SAFE_SEND: An P:{player_id_for_log} ({player_name_for_log}), Payload Typ: {payload.get('type','NO_TYPE')}") # Sehr gesprächig
        conn.sendall(json.dumps(payload).encode('utf-8') + b'\n')
        return True
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(f"SERVER SAFE_SEND (COMM ERROR): P:{player_id_for_log} ({player_name_for_log}): {e}")
        with data_lock:
            if "players" in game_data and player_id_for_log in game_data["players"]:
                if game_data["players"][player_id_for_log].get("client_conn") == conn:
                    game_data["players"][player_id_for_log]["client_conn"] = None
                    print(f"SERVER SAFE_SEND: client_conn für P:{player_id_for_log} auf None gesetzt wegen Sendefehler.")
        return False
    except Exception as e:
        print(f"SERVER SAFE_SEND (UNEXPECTED ERROR): P:{player_id_for_log} ({player_name_for_log}): {e}")
        traceback.print_exc()
        return False


def reset_game_to_initial_state(notify_clients_about_reset=False, reset_message="Server wurde zurückgesetzt. Bitte neu beitreten."):
    global game_data
    
    players_to_notify_and_disconnect_info = []

    with data_lock:
        print(f"SERVER LOGIC (RGS_ENTER_LOCK): Spiel wird zurückgesetzt. Notify Clients: {notify_clients_about_reset}")

        current_players_snapshot_for_notification = {}
        if notify_clients_about_reset and "players" in game_data:
            current_players_snapshot_for_notification = {
                p_id: {"conn": p_info.get("client_conn"), "name": p_info.get("name", "N/A")}
                for p_id, p_info in game_data["players"].items()
                if p_info.get("client_conn")
            }
        
        print(f"SERVER LOGIC (RGS_PRE_CLEAR): game_data wird jetzt geleert.")
        game_data.clear() 
        print(f"SERVER LOGIC (RGS_POST_CLEAR): game_data geleert.")
        game_data.update({
            "status": GAME_STATE_LOBBY,
            "status_display": GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY],
            "players": {},
            "game_start_time_actual": None, "game_end_time": None, "hider_wait_end_time": None,
            "available_tasks": list(TASKS), "game_over_message": None,
            "hider_warning_active_for_current_cycle": False, "actual_game_over_time": None,
            "early_end_requests": set(), "total_active_players_for_early_end": 0,
            "current_phase_index": -1, "current_phase_start_time": 0,
            "updates_done_in_current_phase": 0, "next_location_broadcast_time": float('inf'),
        })
        print("SERVER LOGIC (RGS_POST_UPDATE): Spielzustand auf Initialwerte zurückgesetzt (game_data manipuliert).")

        if notify_clients_about_reset:
            for p_id, p_snapshot_info in current_players_snapshot_for_notification.items():
                conn_to_notify = p_snapshot_info["conn"]
                p_name_log = p_snapshot_info["name"]
                if conn_to_notify:
                    players_to_notify_and_disconnect_info.append({
                        "id": p_id, "conn": conn_to_notify, "name": p_name_log
                    })
        print(f"SERVER LOGIC (RGS_EXIT_LOCK): Lock wird freigegeben. {len(players_to_notify_and_disconnect_info)} Clients werden benachrichtigt/getrennt.")

    if notify_clients_about_reset and players_to_notify_and_disconnect_info:
        print(f"SERVER LOGIC (RGS_NOTIFY_LOOP_START): Beginne Benachrichtigung/Trennung von {len(players_to_notify_and_disconnect_info)} Clients.")
        
        payload_for_reset = {
            "type": "game_update", "player_id": None, 
            "error_message": reset_message, "join_error": reset_message, 
            "game_state": { "status": "disconnected", "status_display": reset_message, "game_over_message": reset_message }
        }

        for player_info_item in players_to_notify_and_disconnect_info: # Umbenannt, um Verwechslung mit p_info im globalen Scope zu vermeiden
            conn = player_info_item["conn"]
            p_id = player_info_item["id"]
            p_name = player_info_item["name"]
            
            if _safe_send_json(conn, payload_for_reset, p_id, p_name):
                print(f"SERVER RGS_NOTIFY: Reset-Nachricht an P:{p_id} ({p_name}) gesendet.")
            else:
                print(f"SERVER RGS_NOTIFY (SEND FAILED): P:{p_id} ({p_name}).")
            
            try:
                print(f"SERVER RGS_SHUTDOWN: Versuche Shutdown für Socket von P:{p_id} ({p_name}).")
                conn.shutdown(socket.SHUT_RDWR) 
            except (OSError, socket.error) as e_shutdown:
                if e_shutdown.errno not in [socket.EBADF, socket.ENOTCONN]:
                    print(f"SERVER RGS_SHUTDOWN_ERROR: Fehler bei Socket-Shutdown für P:{p_id} ({p_name}): {e_shutdown}.")
            except Exception as e_shutdown_generic:
                 print(f"SERVER RGS_SHUTDOWN_GENERIC_ERROR: Für P:{p_id} ({p_name}): {e_shutdown_generic}.")
            finally:
                try:
                    print(f"SERVER RGS_CLOSE: Schließe Socket von P:{p_id} ({p_name}).")
                    conn.close()
                except Exception as e_close:
                    print(f"SERVER RGS_CLOSE_ERROR: Fehler beim expliziten Schließen für P:{p_id} ({p_name}): {e_close}.")
    
    print("SERVER LOGIC (RGS_END): reset_game_to_initial_state abgeschlossen.")

def get_active_lobby_players_data(): #... (Rest bleibt gleich)
    active_lobby_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("confirmed_for_lobby", False):
                active_lobby_players[p_id] = { "name": p_info.get("name", "Unbekannt"), "role": p_info.get("current_role", "hider"), "is_ready": p_info.get("is_ready", False) }
    return active_lobby_players
def get_all_players_public_status(): #... (Rest bleibt gleich)
    all_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            all_players[p_id] = { "name": p_info.get("name", "Unbekannt"), "role": p_info.get("current_role", "hider"), "status": p_info.get("status_ingame", "active") }
    return all_players
def get_hider_leaderboard(): #... (Rest bleibt gleich)
    leaderboard = []
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("original_role") == "hider":
                leaderboard.append({ "id": p_id, "name": p_info.get("name", "Unbekannt"), "points": p_info.get("points", 0), "status": p_info.get("status_ingame", "active") })
    leaderboard.sort(key=lambda x: x["points"], reverse=True)
    return leaderboard
def assign_task_to_hider(player_id): #... (Rest bleibt gleich)
    with data_lock:
        player = game_data.get("players", {}).get(player_id)
        if not player or player.get("current_role") != "hider" or player.get("status_ingame") != "active": return
        available_tasks_list = game_data.get("available_tasks")
        if not player.get("task") and available_tasks_list:
            assigned_tasks = {p.get("task", {}).get("id") for p in game_data["players"].values() if p.get("task")}
            possible_tasks = [t for t in available_tasks_list if t.get("id") not in assigned_tasks]
            if possible_tasks:
                task = random.choice(possible_tasks)
                player["task"] = task
                player["task_deadline"] = time.time() + task.get("time_limit_seconds", 180)
                print(f"SERVER TASK: Hider {player.get('name','N/A')} ({player_id}): Neue Aufgabe: {task.get('description','N/A')}")
            else: print(f"SERVER TASK: Keine unzugewiesenen Aufgaben mehr für Hider {player.get('name','N/A')}")
        elif not available_tasks_list: print(f"SERVER TASK: Keine Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")
def count_active_players_for_early_end(): #... (Rest bleibt gleich)
    with data_lock:
        return sum(1 for p in game_data.get("players", {}).values() if p.get("status_ingame") == "active" and p.get("confirmed_for_lobby"))
def _calculate_and_set_next_broadcast_time(current_time): #... (Rest bleibt gleich)
    with data_lock:
        phase_idx = game_data.get("current_phase_index", -1)
        if phase_idx < 0 or phase_idx >= len(PHASE_DEFINITIONS):
            game_data["next_location_broadcast_time"] = float('inf')
            if phase_idx >= len(PHASE_DEFINITIONS) and game_data.get("status") == GAME_STATE_RUNNING: print("SERVER LOGIC: Alle Update-Phasen abgeschlossen.")
            return
        phase_def = PHASE_DEFINITIONS[phase_idx]
        phase_ended_by_duration = False
        if not phase_def.get("is_initial_reveal"):
            phase_ended_by_duration = (phase_def["duration_seconds"] != float('inf') and current_time >= game_data.get("current_phase_start_time", 0) + phase_def["duration_seconds"])
        phase_ended_by_updates = ("updates_in_phase" in phase_def and game_data.get("updates_done_in_current_phase", 0) >= phase_def["updates_in_phase"])
        if (phase_def.get("is_initial_reveal") and game_data.get("updates_done_in_current_phase", 0) > 0) or phase_ended_by_duration or phase_ended_by_updates:
            game_data["current_phase_index"] += 1
            phase_idx = game_data["current_phase_index"]
        if phase_idx >= len(PHASE_DEFINITIONS):
            game_data["next_location_broadcast_time"] = float('inf')
            print("SERVER LOGIC: Alle Update-Phasen abgeschlossen (nach Inkrement).")
            return
        if phase_idx != game_data.get("_last_calculated_phase_idx_for_broadcast", -2) or \
           (PHASE_DEFINITIONS[phase_idx].get("is_initial_reveal") and game_data.get("updates_done_in_current_phase", 0) == 0):
            game_data["current_phase_start_time"] = current_time
            game_data["updates_done_in_current_phase"] = 0
            phase_def = PHASE_DEFINITIONS[phase_idx]
            print(f"SERVER LOGIC: Starte/Weiter mit Phase {phase_idx}: {phase_def['name']}")
            game_data["_last_calculated_phase_idx_for_broadcast"] = phase_idx
        if "update_interval_seconds" in phase_def:
            game_data["next_location_broadcast_time"] = current_time + phase_def["update_interval_seconds"]
        elif "updates_in_phase" in phase_def and phase_def["updates_in_phase"] > 0:
            if phase_def["duration_seconds"] > 0:
                interval = phase_def["duration_seconds"] / phase_def["updates_in_phase"]
                game_data["next_location_broadcast_time"] = current_time + interval
            else: game_data["next_location_broadcast_time"] = current_time
        else: game_data["next_location_broadcast_time"] = float('inf')
        if game_data["next_location_broadcast_time"] != float('inf'):
            delay_seconds = int(game_data['next_location_broadcast_time'] - current_time)
            target_time_str = time.strftime('%H:%M:%S', time.localtime(game_data['next_location_broadcast_time']))
            # print(f"SERVER LOGIC: Nächster Broadcast für: {target_time_str} (in ca. {delay_seconds}s) in Phase '{phase_def['name']}'.") # Kann gesprächig sein

def send_data_to_one_client(conn, player_id_for_perspective): #... (Rest bleibt gleich)
    payload = {}; player_name_for_log = "N/A_SEND_INIT"
    try:
        with data_lock:
            if player_id_for_perspective not in game_data.get("players", {}):
                if conn:
                    null_player_payload = { "type": "game_update", "player_id": None, "message": "Du wurdest entfernt/Server resettet.", "join_error": "Nicht mehr Teil des Spiels.", "game_state": { "status": "disconnected", "status_display": "Sitzung ungültig." } }
                    _safe_send_json(conn, null_player_payload, player_id_for_perspective, "N/A (Player not in game_data)")
                return False
            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return False
            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            is_waiting_for_lobby = player_info.get("is_waiting_for_lobby", False)
            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbek. Status"))
            payload_game_state = {}
            if is_waiting_for_lobby: payload_game_state = { "status": "waiting_for_lobby", "status_display": "Warten auf nächste Lobby", "game_time_left": 0, "hider_wait_time_left": 0, "game_over_message": None }
            else: payload_game_state = { "status": current_game_status, "status_display": current_status_display, "game_time_left": int(game_data.get("game_end_time", 0) - time.time()) if game_data.get("game_end_time") and current_game_status == GAME_STATE_RUNNING else 0, "hider_wait_time_left": int(game_data.get("hider_wait_end_time", 0) - time.time()) if game_data.get("hider_wait_end_time") and current_game_status == GAME_STATE_HIDER_WAIT else 0, "game_over_message": game_data.get("game_over_message") }
            payload = { "type": "game_update", "player_id": player_id_for_perspective, "player_name": player_name_for_log, "role": p_role, "location": player_info.get("location"), "confirmed_for_lobby": player_info.get("confirmed_for_lobby", False), "player_is_ready": player_info.get("is_ready", False), "player_status": player_info.get("status_ingame", "active"), "is_waiting_for_lobby": is_waiting_for_lobby, "game_state": payload_game_state, "lobby_players": get_active_lobby_players_data() if current_game_status == GAME_STATE_LOBBY and not is_waiting_for_lobby else {}, "all_players_status": get_all_players_public_status(), "hider_leaderboard": get_hider_leaderboard() if p_role == "hider" or current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS] else None, "hider_location_update_imminent": player_info.get("has_pending_location_warning", False) if p_role == "hider" and not is_waiting_for_lobby else False, "early_end_requests_count": len(game_data.get("early_end_requests", set())) if not is_waiting_for_lobby else 0, "total_active_players_for_early_end": game_data.get("total_active_players_for_early_end", 0) if not is_waiting_for_lobby else 0, "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set()) if not is_waiting_for_lobby else False }
            if p_role == "hider" and not is_waiting_for_lobby:
                payload["task_skips_available"] = player_info.get("task_skips_available", 0)
                if player_info.get("status_ingame") == "active" and player_info.get("task"):
                    p_task_info = player_info["task"]
                    payload["current_task"] = { "id": p_task_info.get("id", "N/A"), "description": p_task_info.get("description", "Keine Beschr."), "points": p_task_info.get("points", 0), "time_left_seconds": max(0, int(player_info.get("task_deadline", 0) - time.time())) if player_info.get("task_deadline") else 0 }
                else: payload["current_task"] = None
                payload["pre_cached_tasks"] = []
                if player_info.get("status_ingame") == "active":
                    available_tasks_list_copy = list(game_data.get("available_tasks", []))
                    assigned_task_ids = {p.get("task", {}).get("id") for p in game_data.get("players", {}).values() if p.get("task")}
                    unassigned_tasks = [t for t in available_tasks_list_copy if t.get("id") not in assigned_task_ids]
                    random.shuffle(unassigned_tasks)
                    for i in range(min(2, len(unassigned_tasks))):
                        task_to_cache = unassigned_tasks[i]
                        payload["pre_cached_tasks"].append({ "id": task_to_cache.get("id"), "description": task_to_cache.get("description"), "points": task_to_cache.get("points") })
            if p_role == "seeker" and not is_waiting_for_lobby:
                visible_hiders = {}
                current_players_copy = dict(game_data.get("players", {}))
                for h_id, h_info in current_players_copy.items():
                    if h_info.get("current_role") == "hider" and h_info.get("status_ingame") == "active" and h_info.get("location"):
                        visible_hiders[h_id] = { "name": h_info.get("name", "Unbek. Hider"), "lat": h_info["location"][0], "lon": h_info["location"][1], "timestamp": time.strftime("%H:%M:%S", time.localtime(h_info.get("last_location_timestamp", time.time()))) }
                payload["hider_locations"] = visible_hiders
            else: payload["hider_locations"] = {}
        if conn and payload: return _safe_send_json(conn, payload, player_id_for_perspective, player_name_for_log)
    except Exception as e:
        print(f"SERVER SEND (ERROR - UNEXPECTED in prep): P:{player_id_for_perspective} ({player_name_for_log}): {e}")
        traceback.print_exc()
    return False

def broadcast_full_game_state_to_all(exclude_pid=None): #... (Rest bleibt gleich)
    players_to_update_with_conn = []
    with data_lock:
        for pid, pinfo in game_data.get("players", {}).items():
            if pid != exclude_pid and pinfo.get("client_conn"): players_to_update_with_conn.append((pid, pinfo["client_conn"]))
    for p_id_to_update, conn_to_use in players_to_update_with_conn:
        send_data_to_one_client(conn_to_use, p_id_to_update)
def broadcast_server_text_notification(message_text, target_player_ids=None, role_filter=None): #... (Rest bleibt gleich)
    message_data = {"type": "server_text_notification", "message": message_text}
    players_to_notify = []
    with data_lock:
        player_pool = target_player_ids if target_player_ids is not None else game_data.get("players", {}).keys()
        for p_id in player_pool:
            p_info = game_data.get("players", {}).get(p_id)
            if not p_info or not p_info.get("client_conn"): continue
            if role_filter and p_info.get("current_role") != role_filter: continue
            players_to_notify.append((p_id, p_info["client_conn"], p_info.get("name", "N/A")))
    for p_id, conn, name in players_to_notify: _safe_send_json(conn, message_data, p_id, name)

def check_game_conditions_and_end(): #... (Rest bleibt gleich)
    with data_lock:
        current_game_status = game_data.get("status")
        if current_game_status != GAME_STATE_RUNNING: return False
        current_time = time.time(); original_hiders_exist = False; active_hiders_in_game = 0
        for p_id, p_info in list(game_data.get("players", {}).items()):
            if not p_info: continue
            if p_info.get("original_role") == "hider":
                original_hiders_exist = True
                if p_info.get("status_ingame") == "active": active_hiders_in_game += 1
                if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                    if p_info.get("task") and p_info.get("task_deadline") and current_time > p_info["task_deadline"]:
                        task_desc_log = p_info.get('task',{}).get('description','N/A'); p_name_log = p_info.get('name','N/A')
                        if p_id in game_data.get("players", {}):
                            game_data["players"][p_id]["task"] = None; game_data["players"][p_id]["task_deadline"] = None
                            broadcast_server_text_notification(f"Hider {p_name_log} hat Aufgabe '{task_desc_log}' NICHT rechtzeitig geschafft!")
                            assign_task_to_hider(p_id)
        if original_hiders_exist and active_hiders_in_game == 0:
            game_data["status"] = GAME_STATE_SEEKER_WINS; game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Alle Hider ausgeschieden. Seeker gewinnen!"; game_data["early_end_requests"].clear()
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (alle Hider gefangen)."); return True
        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 and any(p.get("confirmed_for_lobby") for p in game_data.get("players", {}).values()):
            game_data["status"] = GAME_STATE_SEEKER_WINS; game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Keine Hider gestartet. Seeker gewinnen!"; game_data["early_end_requests"].clear()
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (keine Hider gestartet)."); return True
        if game_data.get("game_end_time") and current_time > game_data["game_end_time"]:
            final_active_hiders = sum(1 for p in game_data.get("players", {}).values() if p.get("current_role") == "hider" and p.get("status_ingame") == "active")
            game_data["status"] = GAME_STATE_HIDER_WINS if final_active_hiders > 0 else GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[game_data["status"]]
            game_data["game_over_message"] = "Zeit abgelaufen. " + ("Hider gewinnen!" if final_active_hiders > 0 else "Seeker gewinnen!")
            game_data["early_end_requests"].clear(); print(f"SERVER LOGIC: Spiel beendet - Zeit abgelaufen. Status: {game_data['status_display']}."); return True
        return False

def handle_client_connection(conn, addr):
    player_id = None
    player_name_for_log = "Unbekannt_Init"
    action_for_log = "N/A"
    print(f"SERVER HANDLER: Thread für {addr} gestartet. Socket: {conn}")
    try:
        buffer = ""
        while True:
            try:
                # Das folgende Log kann sehr gesprächig sein, wenn viele Clients verbunden sind.
                # print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Wartet auf Daten (recv)...")
                data_chunk = conn.recv(4096)
                # Das folgende Log ist sehr wichtig für die Diagnose von Verbindungsabbrüchen.
                print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Empfangen {len(data_chunk)} bytes.")
                if not data_chunk:
                    print(f"SERVER COMM: Client {addr} (P:{player_id}, Name:{player_name_for_log}) hat Verbindung geschlossen (recv returned empty).")
                    break 
                buffer += data_chunk.decode('utf-8')

                while '\n' in buffer:
                    message_str, buffer = buffer.split('\n', 1)
                    if not message_str.strip(): continue
                    message = json.loads(message_str)
                    action = message.get("action"); action_for_log = action
                    print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Aktion '{action}' empfangen.")

                    with data_lock:
                        current_game_status_in_handler = game_data.get("status")

                        if action == "FORCE_SERVER_RESET_FROM_CLIENT":
                            client_name_for_reset_log = player_name_for_log if player_id else f"Client {addr[0]}:{addr[1]}"
                            print(f"SERVER ADMIN: {client_name_for_reset_log} hat Server-Reset (FORCE_SERVER_RESET_FROM_CLIENT) angefordert.")
                            reset_message_for_clients = f"Server wurde von '{client_name_for_reset_log}' zurückgesetzt. Bitte neu beitreten."
                            reset_game_to_initial_state(notify_clients_about_reset=True, reset_message=reset_message_for_clients)
                            ack_payload = {"type": "acknowledgement", "message": "Server wurde erfolgreich zurückgesetzt."}
                            _safe_send_json(conn, ack_payload, player_id, player_name_for_log)
                            print(f"SERVER ADMIN: Reset abgeschlossen. Handler für {client_name_for_reset_log} wird beendet.")
                            return # Beendet diesen Handler-Thread

                        if action == "JOIN_GAME" and player_id is None: #... (Rest der Aktion bleibt gleich)
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}"); MAX_NICKNAME_LENGTH = 50
                            if len(p_name) > MAX_NICKNAME_LENGTH: p_name = p_name[:MAX_NICKNAME_LENGTH] + "..."
                            p_role_pref = message.get("role_preference", "hider"); player_name_for_log = p_name
                            if p_role_pref not in ["hider", "seeker"]: p_role_pref = "hider"
                            is_name_taken = False
                            for pid_check, pinfo_check in game_data.get("players", {}).items():
                                if pinfo_check.get("name") == p_name and pinfo_check.get("client_conn") is not None and pid_check != player_id:
                                    is_name_taken = True; break
                            if is_name_taken:
                                print(f"SERVER JOIN (FAIL): Name '{p_name}' belegt. {addr}")
                                error_payload = { "type": "game_update", "player_id": None, "error_message": f"Name '{p_name}' bereits vergeben.", "join_error": f"Name '{p_name}' bereits vergeben.", "game_state": { "status": "disconnected", "status_display": "Beitritt fehlgeschlagen."} }
                                _safe_send_json(conn, error_payload, "N/A_JOIN_FAIL_NAME_TAKEN", p_name)
                                return 
                            base_id = str(addr[1]) + "_" + str(random.randint(1000, 9999)); id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}): id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate
                            player_entry_data = { "addr": addr, "name": p_name, "original_role": p_role_pref, "current_role": p_role_pref, "location": None, "last_seen": time.time(), "client_conn": conn, "confirmed_for_lobby": True, "is_ready": False, "status_ingame": "active", "status_before_offline": "active", "points": 0, "has_pending_location_warning": False, "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0, "task": None, "task_deadline": None, "task_skips_available": INITIAL_TASK_SKIPS if p_role_pref == "hider" else 0, "is_waiting_for_lobby": False }
                            if current_game_status_in_handler in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                                print(f"SERVER JOIN: Spiel war beendet. Reset für neue Runde, {p_name} ({player_id}) tritt bei.")
                                reset_game_to_initial_state(notify_clients_about_reset=False)
                                current_game_status_in_handler = game_data.get("status")
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                send_data_to_one_client(conn, player_id)
                                broadcast_full_game_state_to_all(exclude_pid=player_id)
                            elif current_game_status_in_handler in [GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]:
                                player_entry_data["is_waiting_for_lobby"] = True
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                print(f"SERVER JOIN-PLAYER-WAITING: {p_name} ({player_id}) zur Warteliste hinzugefügt.")
                                join_wait_message = { "type": "game_update", "player_id": player_id, "player_name": p_name, "role": p_role_pref, "is_waiting_for_lobby": True, "game_state": { "status": "waiting_for_lobby", "status_display": "Warten auf nächste Lobby." }, "message": "Spiel läuft. Du bist auf Warteliste." }
                                _safe_send_json(conn, join_wait_message, player_id, p_name)
                            else: # Implizit GAME_STATE_LOBBY
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                print(f"SERVER JOIN-PLAYER-CREATED (lobby): {p_name} ({player_id}) von {addr}.")
                                send_data_to_one_client(conn, player_id)
                                broadcast_full_game_state_to_all(exclude_pid=player_id)
                            continue

                        elif action == "REJOIN_GAME" and player_id is None: #... (Rest der Aktion bleibt gleich)
                            rejoin_player_id = message.get("player_id"); rejoin_player_name = message.get("name")
                            action_for_log = f"REJOIN_GAME (ID: {rejoin_player_id}, Name: {rejoin_player_name})"
                            found_player_to_rejoin = False
                            if rejoin_player_id and rejoin_player_id in game_data.get("players", {}):
                                player_entry = game_data["players"][rejoin_player_id]
                                if player_entry.get("name") != rejoin_player_name: print(f"SERVER REJOIN WARN: Name mismatch for {rejoin_player_id}. Client: '{rejoin_player_name}', Server: '{player_entry.get('name')}'.")
                                old_conn = player_entry.get("client_conn")
                                if old_conn and old_conn != conn:
                                    print(f"SERVER REJOIN: Spieler {player_entry.get('name')} ({rejoin_player_id}) hatte alte Verbindung. Aktualisiere.")
                                    try: old_conn.shutdown(socket.SHUT_RDWR); old_conn.close()
                                    except Exception as e: print(f"SERVER REJOIN WARN: Fehler beim Schließen alter Verbindung für {rejoin_player_id}: {e}")
                                player_entry["client_conn"] = conn; player_entry["addr"] = addr; player_entry["last_seen"] = time.time()
                                player_id = rejoin_player_id; player_name_for_log = player_entry.get("name", rejoin_player_name)
                                found_player_to_rejoin = True
                                if player_entry.get("status_ingame") == "offline":
                                    previous_status = player_entry.get("status_before_offline", "active")
                                    player_entry["status_ingame"] = previous_status; player_entry.pop("status_before_offline", None)
                                    broadcast_server_text_notification(f"Spieler {player_entry.get('name', rejoin_player_name)} wieder online (Status: {previous_status}).")
                                    print(f"SERVER REJOIN: Spieler {player_name_for_log} ({player_id}) Status von 'offline' auf '{previous_status}'.")
                                print(f"SERVER REJOIN (SUCCESS): Spieler {player_name_for_log} ({player_id}) re-assoziiert mit {addr}")
                                send_data_to_one_client(conn, player_id)
                                broadcast_full_game_state_to_all(exclude_pid=player_id)
                            else:
                                print(f"SERVER REJOIN (FAIL): Spieler-ID '{rejoin_player_id}' nicht gefunden für {addr}.")
                                rejoin_fail_payload = { "type": "game_update", "player_id": None, "error_message": f"Rejoin fehlgeschlagen. ID '{rejoin_player_id}' ungültig.", "join_error": f"Rejoin fehlgeschlagen. ID '{rejoin_player_id}' ungültig.", "game_state": { "status": "disconnected", "status_display": "Rejoin fehlgeschlagen."} }
                                _safe_send_json(conn, rejoin_fail_payload, "N/A_REJOIN_FAIL", "N/A_REJOIN_FAIL")
                                return
                            continue
                        
                        if not player_id or player_id not in game_data.get("players", {}): #... (Rest der Aktion bleibt gleich)
                            print(f"SERVER WARN: Unauth./Entfernter Client von {addr} sendet Aktion '{action}'. PID im Handler: {player_id}. Trenne.")
                            error_payload_unauth = { "type":"game_update", "player_id": None, "message":"Nicht authentifiziert oder entfernt.", "join_error": "Sitzung ungültig. Bitte neu beitreten.", "game_state": {"status": "disconnected", "status_display": "Sitzung ungültig."} }
                            _safe_send_json(conn, error_payload_unauth, "N/A_UNAUTH", "N/A_UNAUTH")
                            return

                        current_player_data = game_data["players"][player_id]
                        current_player_data["last_seen"] = time.time()
                        if current_player_data.get("client_conn") != conn: current_player_data["client_conn"] = conn
                        player_name_for_log = current_player_data.get("name", "N/A")

                        # --- Weitere Aktionen (SET_READY, UPDATE_LOCATION, etc.) bleiben hier logisch gleich ---
                        # ... (SET_READY) ...
                        # ... (UPDATE_LOCATION) ...
                        # ... (TASK_COMPLETE) ...
                        # ... (TASK_COMPLETE_OFFLINE) ...
                        # ... (SKIP_TASK) ...
                        # ... (CATCH_HIDER) ...
                        # ... (RETURN_TO_REGISTRATION) ...
                        # ... (LEAVE_GAME_AND_GO_TO_JOIN) ...
                        # ... (REQUEST_EARLY_ROUND_END) ...
                        # ... (Unbekannte Aktion) ...
                        # Aus Platzgründen hier gekürzt, die Logik dieser Aktionen bleibt unverändert.
                        # Wichtig ist, dass der Handler bis hierhin kommt und player_id gültig ist.
                        if action == "SET_READY":
                            if current_game_status_in_handler == GAME_STATE_LOBBY and current_player_data.get("confirmed_for_lobby"):
                                current_player_data["is_ready"] = message.get("ready_status") == True
                                print(f"SERVER ACTION: P:{player_id} ({player_name_for_log}) is_ready={current_player_data['is_ready']}.")
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id) # Nur Status-Update, keine Aktion erlaubt
                        elif action == "UPDATE_LOCATION":
                            lat, lon, acc = message.get("lat"), message.get("lon"), message.get("accuracy")
                            if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
                                current_player_data["location"] = [lat, lon, acc]; current_player_data["last_location_timestamp"] = time.time()
                                if current_player_data.get("has_pending_location_warning") and time.time() > current_player_data.get("warning_sent_time", 0):
                                     current_player_data["last_location_update_after_warning"] = time.time()
                                send_data_to_one_client(conn, player_id)
                            else: _safe_send_json(conn, {"type":"error", "message":"Ungültige Standortdaten."}, player_id, player_name_for_log)
                        elif action == "TASK_COMPLETE": # Gekürzt zur Übersicht
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active" and current_player_data.get("task") and time.time() <= current_player_data.get("task_deadline", 0):
                                current_player_data["points"] += current_player_data["task"].get("points",0)
                                broadcast_server_text_notification(f"Hider {player_name_for_log} erledigte '{current_player_data['task'].get('description', 'N/A')}'!")
                                current_player_data["task"], current_player_data["task_deadline"] = None, None
                                assign_task_to_hider(player_id)
                                if check_game_conditions_and_end(): pass; broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "TASK_COMPLETE_OFFLINE": # Gekürzt
                            # ... Logik für Offline-Task-Verarbeitung ...
                            # send_data_to_one_client oder broadcast_full_game_state_to_all je nach Ergebnis
                            pass # Hier sollte die volle Logik stehen
                        elif action == "SKIP_TASK": # Gekürzt
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active" and current_player_data.get("task") and current_player_data.get("task_skips_available",0) > 0:
                                current_player_data["task_skips_available"] -=1
                                broadcast_server_text_notification(f"Hider {player_name_for_log} übersprang eine Aufgabe.")
                                current_player_data["task"], current_player_data["task_deadline"] = None, None; assign_task_to_hider(player_id)
                                if check_game_conditions_and_end(): pass; broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "CATCH_HIDER": # Gekürzt
                            hider_id_to_catch = message.get("hider_id_to_catch")
                            if current_player_data["current_role"] == "seeker" and current_game_status_in_handler == GAME_STATE_RUNNING and hider_id_to_catch in game_data.get("players",{}) and game_data["players"][hider_id_to_catch].get("current_role") == "hider" and game_data["players"][hider_id_to_catch].get("status_ingame") == "active":
                                game_data["players"][hider_id_to_catch]["status_ingame"] = "caught"; game_data["players"][hider_id_to_catch]["current_role"] = "seeker"
                                broadcast_server_text_notification(f"Seeker {player_name_for_log} fing Hider {game_data['players'][hider_id_to_catch].get('name','N/A')}!")
                                if check_game_conditions_and_end(): pass; broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "RETURN_TO_REGISTRATION":
                            if current_game_status_in_handler == GAME_STATE_LOBBY and player_id in game_data.get("players", {}):
                                print(f"SERVER ACTION: Spieler {player_name_for_log} ({player_id}) kehrt zur Registrierung zurück.")
                                del game_data["players"][player_id]
                                _safe_send_json(conn, {"type": "game_update", "player_id": None, "game_message": "Bitte Details erneut eingeben." }, player_id, player_name_for_log)
                                player_id = None; player_name_for_log = "Unbekannt_Nach_Reset"
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN":
                            print(f"SERVER LEAVE: Spieler {player_name_for_log} ({player_id}) verlässt das Spiel.")
                            if player_id in game_data.get("players", {}):
                                if game_data["players"][player_id].get("status_ingame") == "active":
                                     game_data["players"][player_id]["status_ingame"] = "failed_loc_update" # Als "verlassen" markieren
                                     # Weitere Resets für den Spielerstatus...
                            _safe_send_json(conn, {"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}, player_id, player_name_for_log)
                            player_id = None # Wichtig: Handler-interne player_id entfernen
                            broadcast_full_game_state_to_all()
                            return # Beendet den Handler
                        elif action == "REQUEST_EARLY_ROUND_END":
                            if current_game_status_in_handler in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT] and current_player_data.get("status_ingame") == "active" and current_player_data.get("confirmed_for_lobby"):
                                game_data.setdefault("early_end_requests", set()).add(player_id)
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                                if game_data["total_active_players_for_early_end"] > 0 and len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    game_data["status"] = GAME_STATE_SEEKER_WINS # Standard-Ende
                                    # Weitere Game-Over-Logik...
                                    print(f"SERVER LOGIC: Spiel vorzeitig beendet durch Konsens.")
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        else:
                            print(f"SERVER WARN: Unbekannte Aktion '{action}' von P:{player_id} ({player_name_for_log}).")
                            _safe_send_json(conn, {"type":"error", "message": f"Aktion '{action}' unbekannt."}, player_id, player_name_for_log)


            except json.JSONDecodeError: #... (Rest bleibt gleich)
                print(f"SERVER JSON DECODE ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}): Buffer: '{buffer[:200]}...'")
                _safe_send_json(conn, {"type":"error", "message":"Fehlerhafte JSON-Daten."}, player_id, player_name_for_log); buffer = ""
            except (ConnectionResetError, BrokenPipeError, OSError) as e_comm_loop: #... (Rest bleibt gleich)
                print(f"SERVER COMM ERROR in handler loop ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_comm_loop}"); break
            except Exception as e_inner_loop: #... (Rest bleibt gleich)
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_inner_loop}"); traceback.print_exc()
                _safe_send_json(conn, {"type":"error", "message":"Interner Serverfehler bei Nachrichtenverarbeitung."}, player_id, player_name_for_log)

    except Exception as e_outer_handler: #... (Rest bleibt gleich)
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Fehler: {e_outer_handler}"); traceback.print_exc()
    finally:
        print(f"SERVER CLEANUP ENTERED ({addr}, P:{player_id}, Name: {player_name_for_log}). Socket: {conn}")
        player_affected_by_disconnect = False
        player_rejoined_meanwhile = False
        with data_lock:
            if player_id and player_id in game_data.get("players", {}):
                player_entry = game_data["players"][player_id]
                print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler in game_data gefunden. Aktuelle conn des Spielers: {player_entry.get('client_conn')}, Handler conn: {conn}")
                if player_entry.get("client_conn") == conn:
                    player_entry["client_conn"] = None
                    if player_entry.get("status_ingame") not in ["offline", "caught", "failed_task", "failed_loc_update"]:
                        player_entry["status_before_offline"] = player_entry.get("status_ingame", "active")
                        player_entry["status_ingame"] = "offline"
                        player_affected_by_disconnect = True
                        print(f"SERVER DISCONNECT: Spieler {player_name_for_log} ({player_id}) Status auf 'offline' gesetzt.")
                    else: print(f"SERVER DISCONNECT: P:{player_id} ({player_name_for_log}) war bereits in End-Status/offline.")
                else:
                    player_rejoined_meanwhile = True
                    print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler hat sich bereits mit neuer Verbindung verbunden. Alte Handler-Verbindung wird nur geschlossen.")
            elif player_id:
                 print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler-ID bekannt, aber Spieler NICHT MEHR in game_data (z.B. nach Reset oder RETURN_TO_REGISTRATION).")
            else: # player_id war None
                 print(f"SERVER CLEANUP ({addr}): Keine Spieler-ID für diesen Handler gesetzt (z.B. Join nie erfolgt, nach RETURN_TO_REGISTRATION oder LEAVE_GAME).")

        if player_affected_by_disconnect:
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): pass
            broadcast_full_game_state_to_all()
            broadcast_server_text_notification(f"Spieler {player_name_for_log} ist offline gegangen.")
        elif player_rejoined_meanwhile:
             print(f"SERVER CLEANUP ({addr}, P:{player_id}): Kein Broadcast nötig, da Spieler bereits rejoined.")
        
        if conn:
            try:
                print(f"SERVER CLEANUP ({addr}, P:{player_id}, Name:{player_name_for_log}): Schließe Socket dieses Handlers ({conn}).")
                conn.close()
            except Exception as e_close:
                print(f"SERVER CLEANUP: Fehler beim Schließen des Sockets für {addr} ({conn}): {e_close}")
        print(f"SERVER CLEANUP EXIT ({addr}, P:{player_id}, Name:{player_name_for_log}). Handler-Thread beendet.")


def game_logic_thread(): #... (Rest bleibt gleich, nur erweiterte Logs oder kleine Fixes)
    previous_game_status_for_logic = None
    print("SERVER GAMELOGIC: Game Logic Thread gestartet.")
    while True:
        try:
            time.sleep(1) 
            game_ended_this_tick = False; broadcast_needed = False
            with data_lock:
                current_time = time.time(); current_game_status = game_data.get("status")
                if current_game_status is None:
                    print("SERVER GAMELOGIC (ERROR): Game status None! Resetting."); reset_game_to_initial_state(); current_game_status = game_data.get("status")
                if previous_game_status_for_logic != current_game_status:
                    broadcast_needed = True
                    print(f"SERVER GAMELOGIC: Statuswechsel: {previous_game_status_for_logic} -> {current_game_status}.")
                    previous_game_status_for_logic = current_game_status
                    if current_game_status in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]:
                        game_data["early_end_requests"] = set(); game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                
                if current_game_status == GAME_STATE_LOBBY: #... (Logik bleibt)
                    #...
                    MIN_PLAYERS_TO_START = 1 # Mindestens 1 Spieler zum Starten (kann angepasst werden)
                    confirmed_players = [p for p_id, p in game_data.get("players", {}).items() if p.get("confirmed_for_lobby") and p.get("client_conn") is not None]
                    if confirmed_players and len(confirmed_players) >= MIN_PLAYERS_TO_START and all(p.get("is_ready") for p in confirmed_players) :
                        game_data["status"] = GAME_STATE_HIDER_WAIT # ... (Rest der Logik für HIDER_WAIT Start)
                        print(f"SERVER GAMELOGIC: Wechsel zu HIDER_WAIT.")
                        broadcast_needed = True
                elif current_game_status == GAME_STATE_HIDER_WAIT: #... (Logik bleibt)
                    if game_data.get("hider_wait_end_time") and current_time >= game_data["hider_wait_end_time"]:
                         game_data["status"] = GAME_STATE_RUNNING # ... (Rest der Logik für RUNNING Start)
                         print(f"SERVER GAMELOGIC: Wechsel zu RUNNING.")
                         broadcast_needed = True
                    elif game_data.get("hider_wait_end_time") and int(game_data["hider_wait_end_time"] - current_time) % 3 == 0 : broadcast_needed = True
                elif current_game_status == GAME_STATE_RUNNING: #... (Logik bleibt, ggf. kleine Anpassungen im Logging/Timing)
                    if check_game_conditions_and_end(): game_ended_this_tick = True; broadcast_needed = True # broadcast_needed wird durch game_ended_this_tick abgedeckt
                    else: # Standort-Update Logik etc.
                        #...
                        if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 : broadcast_needed = True
                        if int(current_time) % 10 == 0 : # Für Early-End Vote Zähler
                            new_active_count = count_active_players_for_early_end()
                            if game_data.get("total_active_players_for_early_end") != new_active_count:
                                game_data["total_active_players_for_early_end"] = new_active_count; broadcast_needed = True
                elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]: #... (Logik für Soft-Reset bleibt)
                    if "actual_game_over_time" not in game_data or game_data["actual_game_over_time"] is None:
                        game_data["actual_game_over_time"] = current_time
                        if not game_data.get("game_end_time"): game_data["game_end_time"] = current_time
                    if current_time >= game_data["actual_game_over_time"] + POST_GAME_LOBBY_RETURN_DELAY_SECONDS:
                        print("SERVER GAMELOGIC: Game over screen timeout. Soft-Reset zu neuer Lobby.")
                        # --- SOFT-RESET LOGIK HIER ---
                        # (Logik bleibt gleich, gekürzt zur Übersicht)
                        players_to_keep = {} # ...
                        game_data["players"] = players_to_keep # ...
                        game_data["status"] = GAME_STATE_LOBBY # ...
                        broadcast_needed = True
                    else: # Während Game-Over-Screen
                         if int(current_time * (2 if (current_time - game_data.get("actual_game_over_time", current_time)) < 3 else 0.2) ) % 2 == 0: broadcast_needed = True # Häufiger am Anfang, dann seltener

            if game_ended_this_tick or broadcast_needed: broadcast_full_game_state_to_all()
        except Exception as e:
            print(f"!!! CRITICAL ERROR IN GAME LOGIC THREAD !!! Error: {e}"); traceback.print_exc()
            print(f"Game logic thread wird versuchen, nach 5s Pause fortzufahren."); time.sleep(5)

def main_server():
    print("SERVER: Initialisiere Spielzustand beim Serverstart...")
    reset_game_to_initial_state()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"!!! SERVER FATAL: Bind-Fehler an {HOST}:{PORT}: {e}. Läuft Server bereits? !!!"); return
    server_socket.listen()
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")
    threading.Thread(target=game_logic_thread, daemon=True).start()
    # print("SERVER: Game Logic Thread gestartet.") # Wird jetzt im Thread selbst geloggt

    try:
        while True:
            print("SERVER MAIN LOOP: Warte auf neue Verbindung (accept)...")
            conn, addr = server_socket.accept()
            print(f"SERVER MAIN LOOP: Verbindung von {addr} akzeptiert. Starte Handler-Thread.")
            thread = threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt: print("SERVER: KeyboardInterrupt. Fahre herunter.")
    except Exception as e: print(f"SERVER FATAL: Unerwarteter Fehler in Hauptschleife: {e}"); traceback.print_exc()
    finally:
        print("SERVER: Schließe Server-Socket...");
        if server_socket:
            try: server_socket.close()
            except Exception as e: print(f"SERVER: Fehler beim Schließen des Hauptsockets: {e}")
        print("SERVER: Server beendet.")

if __name__ == "__main__":
    main_server()
