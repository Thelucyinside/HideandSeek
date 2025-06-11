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

# Phasen-Definitionen für Hider-Standort-Updates an Seeker
# Die Dauer der letzten Phase wird effektiv durch GAME_DURATION_SECONDS begrenzt.
POST_GAME_LOBBY_RETURN_DELAY_SECONDS = 30 # 30 seconds in game-over screen before returning to lobby
PHASE_DEFINITIONS = [
    # Phase 0: Initialer Reveal sofort nach der Hider-Vorbereitungszeit
    {"name": "Initial Reveal", "duration_seconds": 0, "is_initial_reveal": True, "updates_in_phase": 1},
    # Phase 1: Nächste 10 Min (600s), 2 Updates (d.h. alle 300s / 5 Min)
    {"name": "Phase 1 (10 min, 2 Updates)", "duration_seconds": 600, "updates_in_phase": 2},
    # Phase 2: Nächste 10 Min (600s), 4 Updates (d.h. alle 150s / 2.5 Min)
    {"name": "Phase 2 (10 min, 4 Updates)", "duration_seconds": 600, "updates_in_phase": 4},
    # Phase 3: Nächste 5 Min (300s), 3 Updates (d.h. alle 100s / 1 Min 40s)
    {"name": "Phase 3 (5 min, 3 Updates)", "duration_seconds": 300, "updates_in_phase": 3},
    # Phase 4: Nächste 3 Min (180s), Updates alle 30 Sekunden
    {"name": "Phase 4 (3 min, 30s Interval)", "duration_seconds": 180, "update_interval_seconds": 30},
    # Phase 5: Bis Spielende, Updates alle 5 Sekunden
    {"name": "Phase 5 (Continuous - 5s Interval)", "duration_seconds": float('inf'), "update_interval_seconds": 5}
]

# Spielzustände
GAME_STATE_LOBBY = "lobby"
GAME_STATE_HIDER_WAIT = "hider_wait" # Hider-Vorbereitungszeit
GAME_STATE_RUNNING = "running"
GAME_STATE_HIDER_WINS = "hider_wins"
GAME_STATE_SEEKER_WINS = "seeker_wins"

# Anzeigenamen für die Spielzustände
GAME_STATE_DISPLAY_NAMES = {
    GAME_STATE_LOBBY: "Lobby - Warten auf Spieler",
    GAME_STATE_HIDER_WAIT: "Vorbereitung - Hider verstecken sich",
    GAME_STATE_RUNNING: "Spiel läuft",
    GAME_STATE_HIDER_WINS: "Spiel beendet - Hider gewinnen!",
    GAME_STATE_SEEKER_WINS: "Spiel beendet - Seeker gewinnen!"
}

INITIAL_TASK_SKIPS = 1 # Anzahl der Aufgaben-Skips, die ein Hider pro Spiel erhält

game_data = {} # Globales Dictionary, das den aktuellen Spielzustand speichert
data_lock = threading.RLock() # Reentrant Lock für den Zugriff auf game_data

def format_time_ago(seconds_elapsed):
    """Formatiert eine Anzahl von Sekunden in eine lesbare 'vor X Zeit'-Angabe."""
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
    """Sicherer Versand von JSON-Daten an einen Client. Setzt client_conn auf None bei Fehler."""
    if not conn:
        # NEUES LOG
        print(f"SERVER SAFE_SEND (NO CONN): P:{player_id_for_log} ({player_name_for_log}): Payload (Typ: {payload.get('type','NO_TYPE')}) nicht gesendet, da conn=None.")
        return False
    try:
        # Das folgende Log kann sehr gesprächig sein, wenn es für jede Nachricht aktiviert wird.
        # print(f"SERVER SAFE_SEND: An P:{player_id_for_log} ({player_name_for_log}), Payload Typ: {payload.get('type','NO_TYPE')}, Socket: {conn}")
        conn.sendall(json.dumps(payload).encode('utf-8') + b'\n')
        return True
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        # NEUES LOG (leicht modifiziert)
        print(f"SERVER SAFE_SEND (COMM ERROR): P:{player_id_for_log} ({player_name_for_log}): {e}. Socket: {conn}")
        with data_lock: # Muss gelockt sein, um game_data zu ändern
            if "players" in game_data and player_id_for_log in game_data.get("players", {}): # Sicherstellen, dass player_id noch existiert
                # Wichtig: Nur None setzen, wenn es sich tatsächlich um die Verbindung handelt, die den Fehler verursacht hat
                if game_data["players"][player_id_for_log].get("client_conn") == conn:
                    game_data["players"][player_id_for_log]["client_conn"] = None
                    # NEUES LOG
                    print(f"SERVER SAFE_SEND: client_conn für P:{player_id_for_log} ({player_name_for_log}) auf None gesetzt wegen Sendefehler.")
        return False
    except Exception as e:
        # NEUES LOG (leicht modifiziert)
        print(f"SERVER SAFE_SEND (UNEXPECTED ERROR): P:{player_id_for_log} ({player_name_for_log}): {e}. Socket: {conn}")
        traceback.print_exc()
        return False


def reset_game_to_initial_state(notify_clients_about_reset=False, reset_message="Server wurde zurückgesetzt. Bitte neu beitreten."):
    """ Setzt das Spiel komplett zurück, entfernt alle Spieler und startet eine frische Lobby. """
    global game_data
    
    players_to_notify_and_disconnect_info = [] 

    with data_lock: 
        # NEUES LOG
        print(f"SERVER LOGIC (RGS_ENTER_LOCK): Spiel wird zurückgesetzt. Notify Clients: {notify_clients_about_reset}")

        current_players_snapshot_for_notification = {}
        if notify_clients_about_reset and "players" in game_data:
            current_players_snapshot_for_notification = {
                p_id: {"conn": p_info.get("client_conn"), "name": p_info.get("name", "N/A")}
                for p_id, p_info in game_data["players"].items()
                if p_info.get("client_conn") 
            }
        
        # NEUES LOG
        print(f"SERVER LOGIC (RGS_PRE_CLEAR): game_data wird jetzt geleert. Aktuelle Spieleranzahl (für Snapshot): {len(current_players_snapshot_for_notification)}")
        game_data.clear() 
        # NEUES LOG
        print(f"SERVER LOGIC (RGS_POST_CLEAR): game_data geleert.")
        game_data.update({
            "status": GAME_STATE_LOBBY,
            "status_display": GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY],
            "players": {}, 
            "game_start_time_actual": None,
            "game_end_time": None,
            "hider_wait_end_time": None,
            "available_tasks": list(TASKS), 
            "game_over_message": None,
            "hider_warning_active_for_current_cycle": False,
            "actual_game_over_time": None,
            "early_end_requests": set(),
            "total_active_players_for_early_end": 0,
            "current_phase_index": -1,
            "current_phase_start_time": 0,
            "updates_done_in_current_phase": 0,
            "next_location_broadcast_time": float('inf'),
        })
        # NEUES LOG
        print("SERVER LOGIC (RGS_POST_UPDATE): Spielzustand auf Initialwerte zurückgesetzt (game_data manipuliert).")

        if notify_clients_about_reset:
            for p_id, p_snapshot_info in current_players_snapshot_for_notification.items():
                conn_to_notify = p_snapshot_info["conn"]
                p_name_log = p_snapshot_info["name"]
                if conn_to_notify:
                    players_to_notify_and_disconnect_info.append({
                        "id": p_id,
                        "conn": conn_to_notify, 
                        "name": p_name_log
                    })
        # NEUES LOG
        print(f"SERVER LOGIC (RGS_EXIT_LOCK): Lock wird freigegeben. {len(players_to_notify_and_disconnect_info)} Clients werden potenziell benachrichtigt/getrennt.")

    if notify_clients_about_reset and players_to_notify_and_disconnect_info:
        # NEUES LOG
        print(f"SERVER LOGIC (RGS_NOTIFY_LOOP_START): Beginne Benachrichtigung und Trennung von {len(players_to_notify_and_disconnect_info)} Clients (außerhalb des Locks).")
        
        payload_for_reset = { 
            "type": "game_update", 
            "player_id": None, 
            "error_message": reset_message,
            "join_error": reset_message, 
            "game_state": { "status": "disconnected", "status_display": reset_message, "game_over_message": reset_message }
        }

        for player_info_item in players_to_notify_and_disconnect_info: 
            conn = player_info_item["conn"]
            p_id = player_info_item["id"]
            p_name = player_info_item["name"]
            
            if _safe_send_json(conn, payload_for_reset, p_id, p_name):
                # NEUES LOG
                print(f"SERVER RGS_NOTIFY: Reset-Nachricht an P:{p_id} ({p_name}) auf Socket {conn} gesendet.")
            else:
                # NEUES LOG
                print(f"SERVER RGS_NOTIFY (SEND FAILED): Senden an P:{p_id} ({p_name}) auf Socket {conn} fehlgeschlagen.")
            
            try:
                # NEUES LOG
                print(f"SERVER RGS_SHUTDOWN: Versuche Shutdown für Socket von P:{p_id} ({p_name}): {conn}.")
                conn.shutdown(socket.SHUT_RDWR) 
            except (OSError, socket.error) as e_shutdown:
                if e_shutdown.errno not in [socket.EBADF, socket.ENOTCONN]: 
                    # NEUES LOG
                    print(f"SERVER RGS_SHUTDOWN_ERROR: Fehler bei Socket-Shutdown für P:{p_id} ({p_name}) auf {conn}: {e_shutdown}.")
            except Exception as e_shutdown_generic:
                 # NEUES LOG
                 print(f"SERVER RGS_SHUTDOWN_GENERIC_ERROR: Für P:{p_id} ({p_name}) auf {conn}: {e_shutdown_generic}.")
            finally:
                try:
                    # NEUES LOG
                    print(f"SERVER RGS_CLOSE: Schließe Socket von P:{p_id} ({p_name}): {conn}.")
                    conn.close()
                except Exception as e_close:
                    # NEUES LOG
                    print(f"SERVER RGS_CLOSE_ERROR: Fehler beim expliziten Schließen für P:{p_id} ({p_name}) auf {conn}: {e_close}.")
    
    # NEUES LOG
    print("SERVER LOGIC (RGS_END): reset_game_to_initial_state abgeschlossen.")

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
            assigned_tasks = {p_info.get("task", {}).get("id") for p_info in game_data["players"].values() if p_info.get("task")}
            possible_tasks = [t for t in available_tasks_list if t.get("id") not in assigned_tasks]

            if possible_tasks:
                task = random.choice(possible_tasks)
                player["task"] = task
                player["task_deadline"] = time.time() + task.get("time_limit_seconds", 180)
                print(f"SERVER TASK: Hider {player.get('name','N/A')} ({player_id}): Neue Aufgabe: {task.get('description','N/A')}")
            else:
                print(f"SERVER TASK: Keine unzugewiesenen Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")
        elif not available_tasks_list:
            print(f"SERVER TASK: Keine Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")

def count_active_players_for_early_end():
    with data_lock:
        return sum(1 for p_info in game_data.get("players", {}).values()
                   if p_info.get("status_ingame") == "active" and p_info.get("confirmed_for_lobby"))

def _calculate_and_set_next_broadcast_time(current_time):
    with data_lock:
        phase_idx = game_data.get("current_phase_index", -1)

        if phase_idx < 0 or phase_idx >= len(PHASE_DEFINITIONS):
            game_data["next_location_broadcast_time"] = float('inf')
            if phase_idx >= len(PHASE_DEFINITIONS) and game_data.get("status") == GAME_STATE_RUNNING:
                 print("SERVER LOGIC: Alle Update-Phasen abgeschlossen. Standort-Updates beendet (Spiel läuft weiter bis Zeitende).")
            return

        phase_def = PHASE_DEFINITIONS[phase_idx]
        phase_ended_by_duration = False
        if not phase_def.get("is_initial_reveal"):
            phase_ended_by_duration = (phase_def["duration_seconds"] != float('inf') and
                                   current_time >= game_data.get("current_phase_start_time", 0) + phase_def["duration_seconds"])
        phase_ended_by_updates = ("updates_in_phase" in phase_def and
                                  game_data.get("updates_done_in_current_phase", 0) >= phase_def["updates_in_phase"])

        if (phase_def.get("is_initial_reveal") and game_data.get("updates_done_in_current_phase", 0) > 0) or \
           phase_ended_by_duration or phase_ended_by_updates:
            game_data["current_phase_index"] += 1
            phase_idx = game_data["current_phase_index"] 

        if phase_idx >= len(PHASE_DEFINITIONS): 
            game_data["next_location_broadcast_time"] = float('inf')
            print("SERVER LOGIC: Alle Update-Phasen abgeschlossen (nach Inkrement). Standort-Updates beendet.")
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
            else: 
                 game_data["next_location_broadcast_time"] = current_time 
        else:
            game_data["next_location_broadcast_time"] = float('inf')

        if game_data["next_location_broadcast_time"] != float('inf'):
            delay_seconds = int(game_data['next_location_broadcast_time'] - current_time)
            target_time_str = time.strftime('%H:%M:%S', time.localtime(game_data['next_location_broadcast_time']))
            # Das folgende Log kann sehr gesprächig sein.
            # print(f"SERVER LOGIC: Nächster Hider-Standort-Broadcast geplant für: {target_time_str} (in ca. {delay_seconds}s) in Phase '{phase_def['name']}'.")


def send_data_to_one_client(conn, player_id_for_perspective):
    payload = {}
    player_name_for_log = "N/A_IN_SEND_INIT"
    try:
        with data_lock:
            if player_id_for_perspective not in game_data.get("players", {}):
                if conn:
                    null_player_payload = {
                        "type": "game_update", "player_id": None, 
                        "message": "Du wurdest aus dem Spiel entfernt oder der Server wurde zurückgesetzt.",
                        "join_error": "Du bist nicht mehr Teil des aktuellen Spiels. Bitte neu beitreten.",
                        "game_state": { "status": "disconnected", "status_display": "Sitzung ungültig." }
                    }
                    _safe_send_json(conn, null_player_payload, player_id_for_perspective, "N/A (Player not in game_data)")
                return False 

            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return False 

            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            is_waiting_for_lobby = player_info.get("is_waiting_for_lobby", False)

            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbekannter Status"))

            payload_game_state = {}
            if is_waiting_for_lobby:
                payload_game_state = {
                    "status": "waiting_for_lobby", "status_display": "Warten auf nächste Lobby-Runde",
                    "game_time_left": 0, "hider_wait_time_left": 0, "game_over_message": None
                }
            else:
                payload_game_state = {
                    "status": current_game_status, "status_display": current_status_display,
                    "game_time_left": int(game_data.get("game_end_time", 0) - time.time()) if game_data.get("game_end_time") and current_game_status == GAME_STATE_RUNNING else 0,
                    "hider_wait_time_left": int(game_data.get("hider_wait_end_time", 0) - time.time()) if game_data.get("hider_wait_end_time") and current_game_status == GAME_STATE_HIDER_WAIT else 0,
                    "game_over_message": game_data.get("game_over_message")
                }

            payload = {
                "type": "game_update", "player_id": player_id_for_perspective, 
                "player_name": player_name_for_log, "role": p_role, "location": player_info.get("location"),
                "confirmed_for_lobby": player_info.get("confirmed_for_lobby", False),
                "player_is_ready": player_info.get("is_ready", False),
                "player_status": player_info.get("status_ingame", "active"),
                "is_waiting_for_lobby": is_waiting_for_lobby, 
                "game_state": payload_game_state,
                "lobby_players": get_active_lobby_players_data() if current_game_status == GAME_STATE_LOBBY and not is_waiting_for_lobby else {},
                "all_players_status": get_all_players_public_status(),
                "hider_leaderboard": get_hider_leaderboard() if p_role == "hider" or current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS] else None,
                "hider_location_update_imminent": player_info.get("has_pending_location_warning", False) if p_role == "hider" and not is_waiting_for_lobby else False,
                "early_end_requests_count": len(game_data.get("early_end_requests", set())) if not is_waiting_for_lobby else 0,
                "total_active_players_for_early_end": game_data.get("total_active_players_for_early_end", 0) if not is_waiting_for_lobby else 0,
                "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set()) if not is_waiting_for_lobby else False
            }

            if p_role == "hider" and not is_waiting_for_lobby:
                payload["task_skips_available"] = player_info.get("task_skips_available", 0)
                if player_info.get("status_ingame") == "active" and player_info.get("task"):
                    p_task_info = player_info["task"]
                    payload["current_task"] = {
                        "id": p_task_info.get("id", "N/A"), "description": p_task_info.get("description", "Keine Beschreibung"),
                        "points": p_task_info.get("points", 0),
                        "time_left_seconds": max(0, int(player_info.get("task_deadline", 0) - time.time())) if player_info.get("task_deadline") else 0
                    }
                else: 
                    payload["current_task"] = None
                
                payload["pre_cached_tasks"] = []
                if player_info.get("status_ingame") == "active": 
                    available_tasks_list_copy = list(game_data.get("available_tasks", []))
                    assigned_task_ids = {p.get("task", {}).get("id") for p in game_data.get("players", {}).values() if p.get("task")}
                    
                    unassigned_tasks = [t for t in available_tasks_list_copy if t.get("id") not in assigned_task_ids]
                    random.shuffle(unassigned_tasks) 
                    
                    for i in range(min(2, len(unassigned_tasks))): 
                        task_to_cache = unassigned_tasks[i]
                        payload["pre_cached_tasks"].append({
                            "id": task_to_cache.get("id"), "description": task_to_cache.get("description"),
                            "points": task_to_cache.get("points")
                        })


            if p_role == "seeker" and not is_waiting_for_lobby:
                visible_hiders = {}
                current_players_copy = dict(game_data.get("players", {})) 
                for h_id, h_info in current_players_copy.items():
                    if h_info.get("current_role") == "hider" and \
                       h_info.get("status_ingame") == "active" and \
                       h_info.get("location"):
                        visible_hiders[h_id] = {
                            "name": h_info.get("name", "Unbekannter Hider"),
                            "lat": h_info["location"][0], "lon": h_info["location"][1],
                            "timestamp": time.strftime("%H:%M:%S", time.localtime(h_info.get("last_location_timestamp", time.time())))
                        }
                payload["hider_locations"] = visible_hiders
            else: 
                payload["hider_locations"] = {} 

        if conn and payload:
             return _safe_send_json(conn, payload, player_id_for_perspective, player_name_for_log)

    except Exception as e: 
        print(f"SERVER SEND (ERROR - UNEXPECTED in prep): P:{player_id_for_perspective} ({player_name_for_log}): Unerwarteter Fehler: {e}")
        traceback.print_exc()
    return False 


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
    players_to_notify = []
    with data_lock:
        player_pool = target_player_ids if target_player_ids is not None else game_data.get("players", {}).keys()
        for p_id in player_pool:
            p_info = game_data.get("players", {}).get(p_id)
            if not p_info or not p_info.get("client_conn"): continue
            if role_filter and p_info.get("current_role") != role_filter: continue
            players_to_notify.append((p_id, p_info["client_conn"], p_info.get("name", "N/A")))

    for p_id, conn, name in players_to_notify:
        _safe_send_json(conn, message_data, p_id, name)


def check_game_conditions_and_end():
    with data_lock:
        current_game_status = game_data.get("status")
        if current_game_status != GAME_STATE_RUNNING: return False 

        current_time = time.time()
        original_hiders_exist = False
        active_hiders_in_game = 0 

        for p_id, p_info in list(game_data.get("players", {}).items()): 
            if not p_info: continue

            if p_info.get("original_role") == "hider":
                original_hiders_exist = True
                if p_info.get("status_ingame") == "active": 
                    active_hiders_in_game += 1

                if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                    if p_info.get("task") and p_info.get("task_deadline") and current_time > p_info["task_deadline"]:
                        task_description_for_log = p_info.get('task',{}).get('description','N/A')
                        player_name_for_log = p_info.get('name','N/A')
                        if p_id in game_data.get("players", {}):
                            game_data["players"][p_id]["task"] = None 
                            game_data["players"][p_id]["task_deadline"] = None
                            broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' NICHT rechtzeitig geschafft! Aufgabe entfernt.")
                            assign_task_to_hider(p_id)

        if original_hiders_exist and active_hiders_in_game == 0:
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Alle Hider ausgeschieden/gefangen. Seeker gewinnen!"
            game_data["early_end_requests"].clear() 
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (alle Hider gefangen).")
            return True

        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 and any(p.get("confirmed_for_lobby") for p in game_data.get("players", {}).values()):
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Keine Hider im Spiel gestartet. Seeker gewinnen!"
            game_data["early_end_requests"].clear()
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (keine Hider gestartet).")
            return True

        if game_data.get("game_end_time") and current_time > game_data["game_end_time"]:
            final_active_hiders_at_timeout = sum(1 for p_info_final in game_data.get("players", {}).values()
                                                 if p_info_final.get("current_role") == "hider" and p_info_final.get("status_ingame") == "active")
            game_data["status"] = GAME_STATE_HIDER_WINS if final_active_hiders_at_timeout > 0 else GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[game_data["status"]]
            game_data["game_over_message"] = "Zeit abgelaufen. " + ("Hider gewinnen!" if final_active_hiders_at_timeout > 0 else "Seeker gewinnen!")
            game_data["early_end_requests"].clear()
            print(f"SERVER LOGIC: Spiel beendet - Zeit abgelaufen. Status: {game_data['status_display']}.")
            return True

        return False 

def handle_client_connection(conn, addr):
    player_id = None 
    player_name_for_log = "Unbekannt_Init" 
    action_for_log = "N/A" 
    # NEUES LOG
    print(f"SERVER HANDLER: Thread für {addr} gestartet. Socket: {conn}")
    try:
        buffer = ""
        while True:
            try:
                # Das folgende Log kann sehr gesprächig sein. Für Debugging von Verbindungsabbrüchen aktivieren.
                # print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Wartet auf Daten (recv)...")
                data_chunk = conn.recv(4096)
                # NEUES LOG - Dieses ist sehr wichtig!
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
                    # NEUES LOG
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
                            # NEUES LOG
                            print(f"SERVER ADMIN: Reset durch {client_name_for_reset_log} abgeschlossen. Handler-Thread wird beendet.")
                            return 

                        if action == "JOIN_GAME" and player_id is None:
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            MAX_NICKNAME_LENGTH = 50
                            if len(p_name) > MAX_NICKNAME_LENGTH:
                                p_name = p_name[:MAX_NICKNAME_LENGTH] + "..."
                                print(f"SERVER JOIN WARN: Nickname von {addr} auf {MAX_NICKNAME_LENGTH} Zeichen gekürzt.")
                            p_role_pref = message.get("role_preference", "hider") 
                            if p_role_pref not in ["hider", "seeker"]: p_role_pref = "hider"
                            player_name_for_log = p_name 

                            is_name_taken = False
                            for pid_check, pinfo_check in game_data.get("players", {}).items():
                                if pinfo_check.get("name") == p_name and pinfo_check.get("client_conn") is not None and pid_check != player_id:
                                    is_name_taken = True; break
                            if is_name_taken:
                                print(f"SERVER JOIN (FAIL): Name '{p_name}' ist bereits von einem aktiven Spieler belegt. {addr}")
                                error_payload = {
                                    "type": "game_update", "player_id": None, 
                                    "error_message": f"Name '{p_name}' bereits vergeben. Wähle einen anderen Namen.",
                                    "join_error": f"Name '{p_name}' bereits vergeben.",
                                    "game_state": { "status": "disconnected", "status_display": "Beitritt fehlgeschlagen."}
                                }
                                _safe_send_json(conn, error_payload, "N/A_JOIN_FAIL_NAME_TAKEN", p_name)
                                return 
                            base_id = str(addr[1]) + "_" + str(random.randint(1000, 9999))
                            id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}):
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate 
                            player_entry_data = {
                                "addr": addr, "name": p_name, "original_role": p_role_pref, "current_role": p_role_pref,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": True, "is_ready": False, "status_ingame": "active",
                                "status_before_offline": "active", "points": 0, "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None,
                                "task_skips_available": INITIAL_TASK_SKIPS if p_role_pref == "hider" else 0,
                                "is_waiting_for_lobby": False 
                            }
                            if current_game_status_in_handler in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                                print(f"SERVER JOIN: Spiel war beendet. Server wird für neue Runde zurückgesetzt, {p_name} ({player_id}) tritt bei.")
                                reset_game_to_initial_state(notify_clients_about_reset=False) 
                                current_game_status_in_handler = game_data.get("status") 
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                send_data_to_one_client(conn, player_id) 
                                broadcast_full_game_state_to_all(exclude_pid=player_id) 
                            elif current_game_status_in_handler in [GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]:
                                player_entry_data["is_waiting_for_lobby"] = True
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                print(f"SERVER JOIN-PLAYER-WAITING: {p_name} ({player_id}) von {addr} zur Warteliste hinzugefügt (Spiel läuft).")
                                join_wait_message = {
                                    "type": "game_update", "player_id": player_id,
                                    "player_name": p_name, "role": p_role_pref, "is_waiting_for_lobby": True,
                                    "game_state": { "status": "waiting_for_lobby", "status_display": "Warten auf nächste Lobby-Runde. Du bist registriert." },
                                    "message": "Spiel läuft. Du bist auf der Warteliste."
                                }
                                _safe_send_json(conn, join_wait_message, player_id, p_name)
                            else: 
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                print(f"SERVER JOIN-PLAYER-CREATED (lobby): {p_name} ({player_id}) von {addr}.")
                                send_data_to_one_client(conn, player_id) 
                                broadcast_full_game_state_to_all(exclude_pid=player_id) 
                            continue 

                        elif action == "REJOIN_GAME" and player_id is None:
                            rejoin_player_id = message.get("player_id")
                            rejoin_player_name = message.get("name") 
                            action_for_log = f"REJOIN_GAME (Attempt ID: {rejoin_player_id}, Name: {rejoin_player_name})"
                            found_player_to_rejoin = False
                            if rejoin_player_id and rejoin_player_id in game_data.get("players", {}):
                                player_entry = game_data["players"][rejoin_player_id]
                                if player_entry.get("name") != rejoin_player_name:
                                    print(f"SERVER REJOIN WARN: Name mismatch for ID {rejoin_player_id}. Client: '{rejoin_player_name}', Server: '{player_entry.get('name')}'. Rejoin trotzdem erlaubt.")
                                old_conn = player_entry.get("client_conn")
                                if old_conn and old_conn != conn:
                                    print(f"SERVER REJOIN: Spieler {player_entry.get('name')} ({rejoin_player_id}) hatte alte Verbindung. Aktualisiere auf neue.")
                                    try: 
                                        old_conn.shutdown(socket.SHUT_RDWR)
                                        old_conn.close()
                                    except Exception as e: print(f"SERVER REJOIN WARN: Fehler beim Schließen alter Verbindung für {rejoin_player_id}: {e}")
                                player_entry["client_conn"] = conn 
                                player_entry["addr"] = addr
                                player_entry["last_seen"] = time.time() 
                                player_id = rejoin_player_id 
                                player_name_for_log = player_entry.get("name", rejoin_player_name)
                                found_player_to_rejoin = True
                                if player_entry.get("status_ingame") == "offline":
                                    previous_status = player_entry.get("status_before_offline", "active")
                                    player_entry["status_ingame"] = previous_status
                                    player_entry.pop("status_before_offline", None) 
                                    broadcast_server_text_notification(f"Spieler {player_entry.get('name', rejoin_player_name)} ist wieder online (Status: {previous_status}).")
                                    print(f"SERVER REJOIN: Spieler {player_name_for_log} ({player_id}) Status von 'offline' auf '{previous_status}' gesetzt.")
                                print(f"SERVER REJOIN (SUCCESS): Spieler {player_name_for_log} ({player_id}) re-assoziiert mit neuer Verbindung von {addr}")
                                send_data_to_one_client(conn, player_id) 
                                broadcast_full_game_state_to_all(exclude_pid=player_id) 
                            else:
                                print(f"SERVER REJOIN (FAIL): Spieler-ID '{rejoin_player_id}' nicht gefunden für {addr}.")
                                rejoin_fail_payload = {
                                    "type": "game_update", "player_id": None, 
                                    "error_message": f"Rejoin fehlgeschlagen. Spieler-ID '{rejoin_player_id}' nicht mehr gültig oder gefunden.",
                                    "join_error": f"Rejoin fehlgeschlagen. Spieler-ID '{rejoin_player_id}' nicht mehr gültig oder gefunden.",
                                    "game_state": { "status": "disconnected", "status_display": "Rejoin fehlgeschlagen."}
                                }
                                _safe_send_json(conn, rejoin_fail_payload, "N/A_REJOIN_FAIL", "N/A_REJOIN_FAIL")
                                return 
                            continue 

                        if not player_id or player_id not in game_data.get("players", {}):
                            print(f"SERVER WARN: Unauthentifizierter/Entfernter Client von {addr} sendet Aktion '{action}'. Player_id im Handler: {player_id}. Verbindung wird getrennt.")
                            error_payload_unauth = {
                                "type":"game_update", "player_id": None, 
                                "message":"Nicht authentifiziert oder aus Spiel entfernt. Bitte neu beitreten.",
                                "join_error": "Sitzung ungültig oder abgelaufen. Bitte neu beitreten.",
                                "game_state": {"status": "disconnected", "status_display": "Sitzung ungültig."}
                            }
                            _safe_send_json(conn, error_payload_unauth, "N/A_UNAUTH", "N/A_UNAUTH")
                            return 

                        current_player_data = game_data["players"][player_id]
                        current_player_data["last_seen"] = time.time() 
                        if current_player_data.get("client_conn") != conn:
                            current_player_data["client_conn"] = conn
                        player_name_for_log = current_player_data.get("name", "N/A") 


                        if action == "SET_READY":
                            if current_game_status_in_handler == GAME_STATE_LOBBY and current_player_data.get("confirmed_for_lobby"):
                                current_player_data["is_ready"] = message.get("ready_status") == True
                                print(f"SERVER ACTION: P:{player_id} ({player_name_for_log}) gesetzt auf is_ready={current_player_data['is_ready']}.")
                                broadcast_full_game_state_to_all()
                            else:
                                print(f"SERVER ACTION DENIED: P:{player_id} ({player_name_for_log}) SET_READY in falschem Status/Konf. ({current_game_status_in_handler}, confirmed={current_player_data.get('confirmed_for_lobby')}).")
                                send_data_to_one_client(conn, player_id)
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
                            else:
                                print(f"SERVER WARN: Ungültige Standortdaten von P:{player_id} ({player_name_for_log}): lat={lat}, lon={lon}")
                                _safe_send_json(conn, {"type":"error", "message":"Ungültige Standortdaten empfangen."}, player_id, player_name_for_log)
                        elif action == "TASK_COMPLETE":
                            status_changed = False
                            if current_player_data["current_role"] == "hider" and \
                               current_player_data["status_ingame"] == "active" and \
                               current_player_data.get("task"):
                                task_details = current_player_data["task"]
                                if time.time() <= current_player_data.get("task_deadline", 0):
                                    current_player_data["points"] += task_details.get("points", 0)
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_details.get('description', 'N/A')}' erledigt!")
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None
                                    assign_task_to_hider(player_id); status_changed = True
                                else:
                                    task_description_for_log = current_player_data.get("task",{}).get('description','N/A')
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' zu spät eingereicht! Aufgabe entfernt.")
                                    assign_task_to_hider(player_id); status_changed = True
                            if status_changed:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else:
                                print(f"SERVER ACTION DENIED: P:{player_id} ({player_name_for_log}) TASK_COMPLETE nicht möglich (kein Hider, nicht aktiv, keine Aufgabe).")
                                send_data_to_one_client(conn, player_id)
                        elif action == "TASK_COMPLETE_OFFLINE":
                            task_id_offline = message.get("task_id")
                            completed_at_offline_ts = message.get("completed_at_timestamp_offline")
                            status_changed_offline, ack_msg_to_client, err_msg_to_client = False, None, None
                            if not task_id_offline or not isinstance(completed_at_offline_ts, (int, float)):
                                err_msg_to_client = "Ungültige Daten für Offline-Aufgabenerledigung."
                            elif current_player_data.get("current_role") == "hider" and \
                                 current_player_data.get("status_ingame") not in ["caught", "failed_task", "failed_loc_update"]: 
                                server_task_info = current_player_data.get("task")
                                server_task_deadline = current_player_data.get("task_deadline")
                                if server_task_info and server_task_info.get("id") == task_id_offline:
                                    if completed_at_offline_ts <= server_task_deadline:
                                        current_player_data["points"] += server_task_info.get("points", 0)
                                        task_desc_log = server_task_info.get('description', 'N/A')
                                        time_diff_str = format_time_ago(time.time() - completed_at_offline_ts)
                                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_desc_log}' erledigt (offline vor ca. {time_diff_str} nachgereicht).")
                                        ack_msg_to_client = f"Offline erledigte Aufgabe '{task_desc_log}' erfolgreich angerechnet."
                                        current_player_data["task"], current_player_data["task_deadline"] = None, None
                                        assign_task_to_hider(player_id); status_changed_offline = True
                                    else:
                                        err_msg_to_client = f"Offline erledigte Aufgabe (ID: {task_id_offline}) war laut Server-Deadline bereits zum Offline-Zeitpunkt abgelaufen."
                                        current_player_data["task"], current_player_data["task_deadline"] = None, None
                                        assign_task_to_hider(player_id) ; status_changed_offline = True
                                else: 
                                    err_msg_to_client = f"Gemeldete Offline-Aufgabe (ID: {task_id_offline}) ist nicht (mehr) deine aktuelle Server-Aufgabe."
                            else: err_msg_to_client = "Offline-Aufgabe kann nicht angerechnet werden (falsche Rolle oder Spielerstatus)."
                            if err_msg_to_client: _safe_send_json(conn, {"type": "error", "message": err_msg_to_client}, player_id, player_name_for_log)
                            if ack_msg_to_client: _safe_send_json(conn, {"type": "acknowledgement", "message": ack_msg_to_client}, player_id, player_name_for_log)
                            if status_changed_offline:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "SKIP_TASK":
                            task_skipped_successfully = False; error_message_to_client = None; ack_message_to_client = None
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active":
                                if current_player_data.get("task"):
                                    if current_player_data.get("task_skips_available", 0) > 0:
                                        current_player_data["task_skips_available"] -= 1
                                        skipped_task_desc = current_player_data["task"].get("description", "Unbekannte Aufgabe")
                                        current_player_data["task"], current_player_data["task_deadline"] = None, None
                                        assign_task_to_hider(player_id); task_skipped_successfully = True
                                        ack_message_to_client = f"Aufgabe '{skipped_task_desc}' übersprungen. Verbleibende Skips: {current_player_data['task_skips_available']}."
                                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat eine Aufgabe übersprungen.")
                                    else: error_message_to_client = "Keine Aufgaben-Skips mehr verfügbar."
                                else: error_message_to_client = "Du hast keine aktive Aufgabe zum Überspringen."
                            else: error_message_to_client = "Aufgabe kann derzeit nicht übersprungen werden (falsche Rolle/Status)."
                            if error_message_to_client: _safe_send_json(conn, {"type": "error", "message": error_message_to_client}, player_id, player_name_for_log)
                            if ack_message_to_client: _safe_send_json(conn, {"type": "acknowledgement", "message": ack_message_to_client}, player_id, player_name_for_log)
                            if task_skipped_successfully:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn,player_id) 
                        elif action == "CATCH_HIDER":
                            hider_id_to_catch = message.get("hider_id_to_catch"); caught = False
                            if current_player_data["current_role"] == "seeker" and \
                               current_game_status_in_handler == GAME_STATE_RUNNING and \
                               hider_id_to_catch in game_data.get("players", {}):
                                hider_player_data = game_data["players"][hider_id_to_catch]
                                if hider_player_data.get("current_role") == "hider" and hider_player_data.get("status_ingame") == "active":
                                    hider_player_data["current_role"] = "seeker"; hider_player_data["status_ingame"] = "caught"
                                    hider_player_data["task"], hider_player_data["task_deadline"] = None, None
                                    hider_player_data["task_skips_available"] = 0 
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Hider {hider_player_data.get('name','N/A')} gefangen!")
                                    print(f"SERVER ACTION: Seeker {player_name_for_log} ({player_id}) hat Hider {hider_player_data.get('name','N/A')} ({hider_id_to_catch}) gefangen.")
                                    caught = True
                                else: _safe_send_json(conn, {"type":"error", "message":f"Hider {hider_player_data.get('name','N/A')} kann nicht gefangen werden (falsche Rolle/Status oder Offline)."}, player_id, player_name_for_log)
                            else: _safe_send_json(conn, {"type":"error", "message":f"Aktion 'Fangen' nicht möglich (falsche Rolle/Status oder Hider nicht gefunden)."}, player_id, player_name_for_log)
                            if caught:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "RETURN_TO_REGISTRATION":
                            if current_game_status_in_handler == GAME_STATE_LOBBY and player_id in game_data.get("players", {}):
                                print(f"SERVER ACTION: Spieler {player_name_for_log} ({player_id}) kehrt zur Registrierung zurück.")
                                del game_data["players"][player_id]
                                reset_payload = { "type": "game_update", "player_id": None, "join_error": None, "game_message": "Bitte gib deine Details erneut ein." }
                                _safe_send_json(conn, reset_payload, player_id, player_name_for_log)
                                player_id = None; player_name_for_log = "Unbekannt_Nach_Reset"
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN":
                            print(f"SERVER LEAVE: Spieler {player_name_for_log} ({player_id}) verlässt das Spiel.")
                            if player_id in game_data.get("players", {}):
                                if game_data["players"][player_id].get("status_ingame") == "active":
                                     game_data["players"][player_id]["status_ingame"] = "failed_loc_update" 
                                     game_data["players"][player_id]["current_role"] = "seeker" 
                                     game_data["players"][player_id]["task"] = None; game_data["players"][player_id]["task_deadline"] = None
                                     game_data["players"][player_id]["task_skips_available"] = 0
                                     game_data["players"][player_id].pop("status_before_offline", None) 
                                     broadcast_server_text_notification(f"Spieler {player_name_for_log} hat das Spiel vorzeitig verlassen.")
                            _safe_send_json(conn, {"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}, player_id, player_name_for_log)
                            player_id = None 
                            broadcast_full_game_state_to_all() 
                            return 
                        elif action == "REQUEST_EARLY_ROUND_END":
                            if current_game_status_in_handler in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT] and \
                               current_player_data.get("status_ingame") == "active" and \
                               current_player_data.get("confirmed_for_lobby"):
                                game_data.setdefault("early_end_requests", set()).add(player_id)
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                                if game_data["total_active_players_for_early_end"] > 0 and \
                                   len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    game_data["status"] = GAME_STATE_SEEKER_WINS 
                                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
                                    game_data["game_over_message"] = f"Spiel durch Konsens vorzeitig beendet (während {GAME_STATE_DISPLAY_NAMES.get(current_game_status_in_handler, current_game_status_in_handler)}). Seeker gewinnen!"
                                    game_data["early_end_requests"].clear()
                                    print(f"SERVER LOGIC: Spiel vorzeitig beendet durch Konsens ({len(game_data.get('early_end_requests',set()))}/{game_data['total_active_players_for_early_end']}).") # .get mit default für early_end_requests
                                broadcast_full_game_state_to_all()
                            else:
                                print(f"SERVER ACTION DENIED: P:{player_id} ({player_name_for_log}) REQUEST_EARLY_ROUND_END in falschem Status/Konf. ({current_game_status_in_handler}, active={current_player_data.get('status_ingame')}).")
                                send_data_to_one_client(conn, player_id) 
                        else:
                            print(f"SERVER WARN: Unbekannte/unerwartete Aktion '{action}' von P:{player_id} ({player_name_for_log}) empfangen.")
                            _safe_send_json(conn, {"type":"error", "message": f"Aktion '{action}' unbekannt oder derzeit nicht erlaubt."}, player_id, player_name_for_log)

            except json.JSONDecodeError:
                print(f"SERVER JSON DECODE ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}): Buffer war '{buffer[:200]}...'")
                _safe_send_json(conn, {"type":"error", "message":"Fehlerhafte JSON-Daten empfangen. Verbindung könnte instabil sein."}, player_id, player_name_for_log)
                buffer = "" 
            except (ConnectionResetError, BrokenPipeError, OSError) as e_comm_loop:
                print(f"SERVER COMM ERROR in handler loop ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_comm_loop}")
                break 
            except Exception as e_inner_loop:
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_inner_loop}"); traceback.print_exc()
                _safe_send_json(conn, {"type":"error", "message":"Interner Serverfehler bei Nachrichtenverarbeitung."}, player_id, player_name_for_log)
                # Hier nicht breaken, vielleicht erholt sich der Handler.

    except Exception as e_outer_handler:
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Fehler: {e_outer_handler}"); traceback.print_exc()
    finally:
        # NEUES LOG
        print(f"SERVER CLEANUP ENTERED ({addr}, P:{player_id}, Name: {player_name_for_log}). Socket: {conn}")
        player_affected_by_disconnect = False
        player_rejoined_meanwhile = False 
        with data_lock:
            if player_id and player_id in game_data.get("players", {}):
                player_entry = game_data["players"][player_id]
                # NEUES LOG
                print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler in game_data gefunden. Aktuelle conn des Spielers: {player_entry.get('client_conn')}, Handler conn: {conn}")
                if player_entry.get("client_conn") == conn: 
                    player_entry["client_conn"] = None
                    if player_entry.get("status_ingame") not in ["offline", "caught", "failed_task", "failed_loc_update"]:
                        player_entry["status_before_offline"] = player_entry.get("status_ingame", "active")
                        player_entry["status_ingame"] = "offline"
                        player_affected_by_disconnect = True
                        print(f"SERVER DISCONNECT: Spieler {player_name_for_log} ({player_id}) Status auf 'offline' gesetzt.")
                    else: 
                        print(f"SERVER DISCONNECT: P:{player_id} ({player_name_for_log}) war bereits in End-Status oder offline. Keine Statusänderung.")
                else:
                    player_rejoined_meanwhile = True
                    # NEUES LOG
                    print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler hat sich bereits mit neuer Verbindung verbunden ({player_entry.get('client_conn')}). Alte Handler-Verbindung ({conn}) wird nur geschlossen.")
            elif player_id: # player_id ist nicht None, aber nicht in game_data.players
                 # NEUES LOG
                 print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler-ID bekannt, aber Spieler NICHT MEHR in game_data (z.B. nach Reset oder RETURN_TO_REGISTRATION).")
            else: # player_id war None
                 # NEUES LOG
                 print(f"SERVER CLEANUP ({addr}): Keine Spieler-ID für diesen Handler gesetzt (z.B. Join nie erfolgt, nach RETURN_TO_REGISTRATION oder LEAVE_GAME).")

        if player_affected_by_disconnect: 
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): pass 
            broadcast_full_game_state_to_all() 
            broadcast_server_text_notification(f"Spieler {player_name_for_log} ist offline gegangen.")
        elif player_rejoined_meanwhile:
            # NEUES LOG
             print(f"SERVER CLEANUP ({addr}, P:{player_id}): Kein Broadcast nötig, da Spieler bereits rejoined und die neue Verbindung aktiv ist.")
        
        if conn: 
            try:
                # NEUES LOG
                print(f"SERVER CLEANUP ({addr}, P:{player_id}, Name:{player_name_for_log}): Schließe Socket dieses Handlers ({conn}).")
                conn.close()
            except Exception as e_close:
                print(f"SERVER CLEANUP: Fehler beim Schließen des Sockets für {addr} ({conn}): {e_close}")
        # NEUES LOG
        print(f"SERVER CLEANUP EXIT ({addr}, P:{player_id}, Name:{player_name_for_log}). Handler-Thread beendet.")


def game_logic_thread():
    previous_game_status_for_logic = None
    # NEUES LOG
    print("SERVER GAMELOGIC: Game Logic Thread gestartet.")
    while True:
        try: 
            time.sleep(1) 
            game_ended_this_tick = False
            broadcast_needed_due_to_time_or_state_change = False

            with data_lock:
                current_time = time.time()
                current_game_status = game_data.get("status")
                if current_game_status is None: 
                    print("SERVER GAMELOGIC (ERROR): Game status is None. Resetting game to initial state.")
                    reset_game_to_initial_state(); current_game_status = game_data.get("status")

                if previous_game_status_for_logic != current_game_status:
                    broadcast_needed_due_to_time_or_state_change = True
                    # NEUES LOG
                    print(f"SERVER GAMELOGIC: Game status changed from '{previous_game_status_for_logic}' to '{current_game_status}'.")
                    previous_game_status_for_logic = current_game_status
                    if current_game_status in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]:
                        game_data["early_end_requests"] = set() 
                        game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()

                if current_game_status == GAME_STATE_LOBBY:
                    active_lobby_player_count = 0; all_in_active_lobby_ready = True
                    current_players_in_lobby = game_data.get("players", {})
                    if not current_players_in_lobby: all_in_active_lobby_ready = False
                    else:
                        confirmed_players_for_lobby = [p for p in current_players_in_lobby.values()
                                                       if p.get("confirmed_for_lobby") and p.get("client_conn") is not None]
                        if not confirmed_players_for_lobby:
                            all_in_active_lobby_ready = False
                        else:
                            active_lobby_player_count = len(confirmed_players_for_lobby)
                            for p_info_check in confirmed_players_for_lobby:
                                if not p_info_check.get("is_ready", False):
                                    all_in_active_lobby_ready = False; break
                    MIN_PLAYERS_TO_START = 1 
                    if all_in_active_lobby_ready and active_lobby_player_count >= MIN_PLAYERS_TO_START:
                        game_data["status"] = GAME_STATE_HIDER_WAIT
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_HIDER_WAIT]
                        game_data["hider_wait_end_time"] = current_time + HIDER_INITIAL_DEPARTURE_TIME_SECONDS
                        # NEUES LOG
                        print(f"SERVER GAMELOGIC: Wechsel zu HIDER_WAIT. Endzeit: {time.strftime('%H:%M:%S', time.localtime(game_data['hider_wait_end_time']))}. Spieler: {active_lobby_player_count}")
                        broadcast_needed_due_to_time_or_state_change = True

                elif current_game_status == GAME_STATE_HIDER_WAIT:
                    if game_data.get("hider_wait_end_time") and current_time >= game_data["hider_wait_end_time"]:
                        game_data["status"] = GAME_STATE_RUNNING
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS
                        # NEUES LOG
                        print(f"SERVER GAMELOGIC: Wechsel zu RUNNING. Spielende: {time.strftime('%H:%M:%S', time.localtime(game_data['game_end_time']))}")
                        game_data["current_phase_index"] = 0
                        game_data["current_phase_start_time"] = current_time
                        game_data["updates_done_in_current_phase"] = 0
                        _calculate_and_set_next_broadcast_time(current_time) 
                        for p_id_task, p_info_task in list(game_data.get("players", {}).items()):
                            if p_info_task.get("current_role") == "hider" and p_info_task.get("confirmed_for_lobby") and p_info_task.get("status_ingame") == "active":
                                assign_task_to_hider(p_id_task)
                        event_payload_gs = {"type": "game_event", "event_name": "game_started"}
                        player_list_copy_gs = list(game_data.get("players", {}).items())
                        for p_id_event, p_info_event in player_list_copy_gs:
                            conn_gs = p_info_event.get("client_conn")
                            if conn_gs: _safe_send_json(conn_gs, event_payload_gs, p_id_event, p_info_event.get("name"))
                        broadcast_needed_due_to_time_or_state_change = True
                    elif game_data.get("hider_wait_end_time") and int(game_data["hider_wait_end_time"] - current_time) % 3 == 0 : # Regelmäßige Updates für Countdown
                        broadcast_needed_due_to_time_or_state_change = True 

                elif current_game_status == GAME_STATE_RUNNING:
                    if check_game_conditions_and_end():
                        game_ended_this_tick = True 
                    else:
                        next_b_time = game_data.get("next_location_broadcast_time", float('inf'))
                        warning_time_trigger = next_b_time - HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS
                        current_phase_idx_for_warn = game_data.get("current_phase_index", -1)
                        allow_warning = True
                        if 0 <= current_phase_idx_for_warn < len(PHASE_DEFINITIONS):
                            phase_def_warn = PHASE_DEFINITIONS[current_phase_idx_for_warn]
                            interval_check = phase_def_warn.get("update_interval_seconds", phase_def_warn.get("duration_seconds", 1000) / phase_def_warn.get("updates_in_phase",1) if phase_def_warn.get("updates_in_phase",0)>0 else 1000)
                            if interval_check < HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS + 5: 
                                allow_warning = False
                        if allow_warning and \
                           not game_data.get("hider_warning_active_for_current_cycle", False) and \
                           current_time >= warning_time_trigger and current_time < next_b_time:
                            game_data["hider_warning_active_for_current_cycle"] = True
                            hiders_needing_warning_update = False
                            event_payload_warn = {"type": "game_event", "event_name": "hider_location_update_due"}
                            player_list_copy_warn = list(game_data.get("players", {}).items())
                            for p_id, p_info in player_list_copy_warn:
                                if p_id not in game_data.get("players",{}): continue
                                if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active" and p_info.get("client_conn"):
                                    if not p_info.get("has_pending_location_warning"):
                                        game_data["players"][p_id]["has_pending_location_warning"] = True
                                        game_data["players"][p_id]["warning_sent_time"] = current_time
                                        game_data["players"][p_id]["last_location_update_after_warning"] = 0 
                                        hiders_needing_warning_update = True
                                        conn_warn = p_info.get("client_conn")
                                        if conn_warn: _safe_send_json(conn_warn, event_payload_warn, p_id, p_info.get("name"))
                            if hiders_needing_warning_update: broadcast_needed_due_to_time_or_state_change = True
                        if current_time >= next_b_time and next_b_time != float('inf'):
                            game_data["hider_warning_active_for_current_cycle"] = False 
                            active_hiders_who_failed_update_names = []
                            player_list_copy_bc = list(game_data.get("players", {}).items())
                            for p_id_h, p_info_h in player_list_copy_bc:
                                if p_id_h not in game_data.get("players", {}): continue 
                                if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                    if p_info_h.get("has_pending_location_warning") and p_info_h.get("client_conn"):
                                        if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                            active_hiders_who_failed_update_names.append(p_info_h.get('name', 'Unbekannt'))
                                    game_data["players"][p_id_h]["has_pending_location_warning"] = False 
                            if active_hiders_who_failed_update_names:
                                 broadcast_server_text_notification(f"Hider haben Standort nach Warnung NICHT aktualisiert: {', '.join(active_hiders_who_failed_update_names)}. Sie bleiben aktiv (keine Strafe).")
                            game_data["updates_done_in_current_phase"] += 1
                            print(f"SERVER GAMELOGIC: Hider-Standort-Broadcast durchgeführt (Update {game_data['updates_done_in_current_phase']} in Phase {game_data.get('current_phase_index',0)}).")
                            event_payload_seeker = {"type": "game_event", "event_name": "seeker_locations_updated"}
                            player_list_copy_seek_ev = list(game_data.get("players", {}).items())
                            for p_id_s, p_info_s in player_list_copy_seek_ev:
                                if p_id_s not in game_data.get("players",{}): continue
                                if p_info_s.get("current_role") == "seeker" and p_info_s.get("client_conn"):
                                    conn_seek_ev = p_info_s.get("client_conn")
                                    if conn_seek_ev: _safe_send_json(conn_seek_ev, event_payload_seeker, p_id_s, p_info_s.get("name"))
                            _calculate_and_set_next_broadcast_time(current_time) 
                            broadcast_needed_due_to_time_or_state_change = True
                        if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 :
                            broadcast_needed_due_to_time_or_state_change = True
                        if int(current_time) % 10 == 0 :
                            new_active_count = count_active_players_for_early_end()
                            if game_data.get("total_active_players_for_early_end") != new_active_count:
                                game_data["total_active_players_for_early_end"] = new_active_count
                                broadcast_needed_due_to_time_or_state_change = True

                elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                    if "actual_game_over_time" not in game_data or game_data["actual_game_over_time"] is None:
                        game_data["actual_game_over_time"] = current_time
                        if not game_data.get("game_end_time"):
                             game_data["game_end_time"] = current_time 
                    if current_time >= game_data["actual_game_over_time"] + POST_GAME_LOBBY_RETURN_DELAY_SECONDS:
                        print("SERVER GAMELOGIC: Game over screen timeout. Transitioning to new lobby (soft-reset).")
                        players_to_keep = {}
                        players_copy_reset = list(game_data.get("players", {}).items())
                        for p_id, p_info in players_copy_reset:
                            if p_info.get("client_conn") is not None:
                                original_role = p_info.get("original_role", "hider")
                                p_info.update({
                                    "is_waiting_for_lobby": False, "confirmed_for_lobby": True, 
                                    "is_ready": False, "current_role": original_role, "points": 0, 
                                    "task": None, "task_deadline": None, "status_ingame": "active",
                                    "status_before_offline": "active",
                                    "task_skips_available": INITIAL_TASK_SKIPS if original_role == "hider" else 0,
                                    "has_pending_location_warning": False,
                                    "last_location_update_after_warning": 0, "warning_sent_time": 0,
                                })
                                players_to_keep[p_id] = p_info
                            else:
                                print(f"SERVER SOFT-RESET: Entferne Spieler {p_info.get('name')} ({p_id}), da keine Verbindung mehr besteht.")
                        game_data["players"] = players_to_keep
                        game_data["status"] = GAME_STATE_LOBBY
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY]
                        game_data["game_start_time_actual"] = None; game_data["game_end_time"] = None
                        game_data["hider_wait_end_time"] = None; game_data["game_over_message"] = None
                        game_data["current_phase_index"] = -1; game_data["current_phase_start_time"] = 0
                        game_data["updates_done_in_current_phase"] = 0
                        game_data["next_location_broadcast_time"] = float('inf')
                        game_data["hider_warning_active_for_current_cycle"] = False
                        game_data.get("early_end_requests", set()).clear()
                        game_data["total_active_players_for_early_end"] = 0
                        game_data["actual_game_over_time"] = None
                        game_data["available_tasks"] = list(TASKS) 
                        broadcast_needed_due_to_time_or_state_change = True
                        print("SERVER GAMELOGIC: Soft-Reset abgeschlossen. Spieler in neuer Lobby.")
                    else: 
                        time_since_actual_game_over = current_time - game_data.get("actual_game_over_time", current_time)
                        if time_since_actual_game_over < 3: 
                            if int(current_time * 2) % 2 == 0: 
                                broadcast_needed_due_to_time_or_state_change = True
                        elif int(current_time) % 5 == 0: 
                             broadcast_needed_due_to_time_or_state_change = True

            if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
                broadcast_full_game_state_to_all()

        except Exception as e: 
            print(f"!!! CRITICAL ERROR IN GAME LOGIC THREAD !!!")
            print(f"Error: {e}")
            traceback.print_exc()
            print(f"Game logic thread wird versuchen, nach einer kurzen Pause fortzufahren.")
            time.sleep(5) 

def main_server():
    # NEUES LOG
    print("SERVER: Initialisiere Spielzustand beim Serverstart...")
    reset_game_to_initial_state() 
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"!!! SERVER FATAL: Fehler beim Binden an {HOST}:{PORT}: {e}. Läuft Server bereits? !!!"); return
    server_socket.listen()
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")

    threading.Thread(target=game_logic_thread, daemon=True).start()
    # Das folgende Log wird jetzt im game_logic_thread selbst ausgegeben.
    # print("SERVER: Game Logic Thread gestartet.") 

    try:
        while True:
            # NEUES LOG
            print("SERVER MAIN LOOP: Warte auf neue Verbindung (accept)...")
            conn, addr = server_socket.accept() 
            # NEUES LOG
            print(f"SERVER MAIN LOOP: Verbindung von {addr} akzeptiert. Starte Handler-Thread.")
            thread = threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True)
            thread.start() 
    except KeyboardInterrupt:
        print("SERVER: KeyboardInterrupt. Fahre herunter.")
    except Exception as e:
        print(f"SERVER FATAL: Unerwarteter Fehler in Hauptschleife: {e}"); traceback.print_exc()
    finally:
        print("SERVER: Schließe Server-Socket...");
        if server_socket: 
            try: server_socket.close()
            except Exception as e: print(f"SERVER: Fehler beim Schließen des Hauptsockets: {e}")
        print("SERVER: Server beendet.")

if __name__ == "__main__":
    main_server()
