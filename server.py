# server.py
import socket
import threading
import json
import time
import random
import traceback # Import für detailliertere Fehlermeldungen
from tasks import TASKS # Annahme: tasks.py existiert und enthält eine Liste von Aufgaben

HOST = '0.0.0.0'
PORT = 65432
GAME_DURATION_SECONDS = 1800 # 30 Minuten Spielzeit NACH der Hider-Vorbereitungszeit
HIDER_INITIAL_DEPARTURE_TIME_SECONDS = 240 # 4 Minuten Vorbereitungszeit für Hider (Phase 0 der Updates)
HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS = 20 # Hider bekommen 20s vor Standort-Broadcast eine Warnung

# Phasen-Definitionen für Hider-Standort-Updates an Seeker
# Die Dauer der letzten Phase wird effektiv durch GAME_DURATION_SECONDS begrenzt.
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

def reset_game_to_initial_state(notify_clients_about_reset=False, reset_message="Server wurde zurückgesetzt. Bitte neu beitreten."):
    """ Setzt das Spiel komplett zurück, entfernt alle Spieler und startet eine frische Lobby. """
    global game_data
    with data_lock:
        print(f"SERVER LOGIC: Spiel wird zurückgesetzt. Notify Clients: {notify_clients_about_reset}")
        
        if notify_clients_about_reset:
            players_to_disconnect_info = []
            current_players_copy = list(game_data.get("players", {}).items()) 
            
            for p_id, p_info in current_players_copy:
                conn_to_notify = p_info.get("client_conn")
                if conn_to_notify:
                    players_to_disconnect_info.append({
                        "id": p_id, 
                        "conn": conn_to_notify, 
                        "name": p_info.get("name", "N/A")
                    })
                    try:
                        payload = {
                            "type": "game_update", 
                            "player_id": None, 
                            "error_message": reset_message,
                            "join_error": reset_message,
                            "game_state": { "status": "disconnected", "status_display": reset_message, "game_over_message": reset_message }
                        }
                        conn_to_notify.sendall(json.dumps(payload).encode('utf-8') + b'\n')
                        print(f"SERVER RESET NOTIFY: An P:{p_id} ({p_info.get('name', 'N/A')}) gesendet.")
                    except Exception as e:
                        print(f"SERVER RESET NOTIFY (ERROR) P:{p_id}: {e}")
            
            for player_info_dc in players_to_disconnect_info:
                try:
                    player_info_dc["conn"].close()
                    print(f"SERVER RESET: Socket für P:{player_info_dc['id']} ({player_info_dc['name']}) explizit geschlossen.")
                except Exception: pass

        game_data.clear()
        game_data.update({
            "status": GAME_STATE_LOBBY,
            "status_display": GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY],
            "players": {},
            "game_start_time_actual": None, # Start der RUNNING Phase (Epoch-Zeit)
            "game_end_time": None, # Ende der RUNNING Phase (Epoch-Zeit)
            "hider_wait_end_time": None, # Ende der HIDER_WAIT Phase (Epoch-Zeit)
            "available_tasks": list(TASKS),
            "game_over_message": None,
            "hider_warning_active_for_current_cycle": False,
            "early_end_requests": set(),
            "total_active_players_for_early_end": 0,
            # Phasen-spezifische Daten
            "current_phase_index": -1, # Beginnt bei -1, wird beim Start von HIDER_WAIT zu 0 (Initial Reveal)
            "current_phase_start_time": 0, # Startzeit der aktuell aktiven Phase (Epoch-Zeit)
            "updates_done_in_current_phase": 0, # Zähler für Updates in der aktuellen Phase
            "next_location_broadcast_time": float('inf'), # Epoch-Zeit des nächsten Broadcasts
            "_last_calculated_phase_idx_for_broadcast": -2, # Interne Hilfsvariable für Phasenübergang-Erkennung
        })
        print("SERVER LOGIC: Spielzustand auf Initialwerte zurückgesetzt.")


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
        elif not available_tasks_list:
            print(f"SERVER TASK: Keine Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")

def count_active_players_for_early_end():
    with data_lock:
        return sum(1 for p_info in game_data.get("players", {}).values()
                   if p_info.get("status_ingame") == "active" and p_info.get("confirmed_for_lobby"))

def _calculate_and_set_next_broadcast_time(current_time):
    """Berechnet und setzt den nächsten Hider-Standort-Broadcast-Zeitpunkt basierend auf der aktuellen Phase."""
    with data_lock:
        phase_idx = game_data.get("current_phase_index", -1)

        # Wenn Phasen-Index ungültig oder alle Phasen abgeschlossen sind
        if phase_idx < 0 or phase_idx >= len(PHASE_DEFINITIONS):
            game_data["next_location_broadcast_time"] = float('inf')
            if phase_idx >= len(PHASE_DEFINITIONS) and game_data.get("status") == GAME_STATE_RUNNING:
                 print("SERVER LOGIC: Alle Update-Phasen abgeschlossen. Standort-Updates beendet (Spiel läuft weiter bis Zeitende).")
            return

        phase_def = PHASE_DEFINITIONS[phase_idx]
        
        # Phasenübergang prüfen (außer für "is_initial_reveal", das speziell behandelt wird)
        phase_ended_by_duration = False
        if not phase_def.get("is_initial_reveal"): # Dauerprüfung nur nach dem Initial Reveal
            phase_ended_by_duration = (phase_def["duration_seconds"] != float('inf') and
                                   current_time >= game_data.get("current_phase_start_time", 0) + phase_def["duration_seconds"])
        
        phase_ended_by_updates = ("updates_in_phase" in phase_def and not phase_def.get("is_initial_reveal") and
                                  game_data.get("updates_done_in_current_phase", 0) >= phase_def["updates_in_phase"])

        # Logik für Phasenübergang
        if phase_def.get("is_initial_reveal") and game_data.get("updates_done_in_current_phase", 0) > 0:
            # Initial Reveal wurde gerade gemacht, gehe zur nächsten Phase
            game_data["current_phase_index"] += 1
            phase_idx = game_data["current_phase_index"] # Aktualisiere phase_idx
            # Setze aktuelle Phase neu, falls der Index noch nicht die neue Phase darstellt
            if phase_idx < len(PHASE_DEFINITIONS):
                game_data["current_phase_start_time"] = current_time # Beginn der neuen Phase
                game_data["updates_done_in_current_phase"] = 0 # Reset für neue Phase
                game_data["_last_calculated_phase_idx_for_broadcast"] = phase_idx
                phase_def = PHASE_DEFINITIONS[phase_idx] # phase_def neu laden
                print(f"SERVER LOGIC: Übergang zu Phase {phase_idx}: {phase_def['name']} nach Initial Reveal.")
        elif phase_ended_by_duration or phase_ended_by_updates:
            game_data["current_phase_index"] += 1
            phase_idx = game_data["current_phase_index"] # Aktualisiere phase_idx
            # Setze aktuelle Phase neu
            if phase_idx < len(PHASE_DEFINITIONS):
                game_data["current_phase_start_time"] = current_time # Beginn der neuen Phase
                game_data["updates_done_in_current_phase"] = 0 # Reset für neue Phase
                game_data["_last_calculated_phase_idx_for_broadcast"] = phase_idx
                phase_def = PHASE_DEFINITIONS[phase_idx] # phase_def neu laden
                print(f"SERVER LOGIC: Übergang zu Phase {phase_idx}: {phase_def['name']} (Dauer/Updates erfüllt).")

        if phase_idx >= len(PHASE_DEFINITIONS): # Erneut prüfen nach Inkrementierung
            game_data["next_location_broadcast_time"] = float('inf')
            print("SERVER LOGIC: Alle Update-Phasen abgeschlossen. Standort-Updates beendet (Spiel läuft weiter bis Zeitende).")
            return
        
        # Nächsten Broadcast-Zeitpunkt für die aktuelle (ggf. neue) Phase setzen
        if "update_interval_seconds" in phase_def:
            game_data["next_location_broadcast_time"] = current_time + phase_def["update_interval_seconds"]
        elif "updates_in_phase" in phase_def and phase_def["updates_in_phase"] > 0:
            # Für den Initial Reveal (updates_in_phase=1) wird dies den ersten Broadcast planen
            # Für andere Phasen wird es den nächsten Broadcast basierend auf dem Intervall planen
            # Da wir updates_done_in_current_phase bei Phasenstart auf 0 setzen, wird das erste Intervall
            # korrekt vom Phasenstart aus berechnet. Für nachfolgende Updates in der gleichen Phase,
            # wird das Intervall einfach zum aktuellen Zeitpunkt addiert.
            interval = phase_def["duration_seconds"] / phase_def["updates_in_phase"]
            game_data["next_location_broadcast_time"] = current_time + interval
        else: 
            game_data["next_location_broadcast_time"] = float('inf') # Kein Update-Mechanismus definiert
        
        if game_data["next_location_broadcast_time"] != float('inf'):
            delay_seconds = int(game_data['next_location_broadcast_time'] - current_time)
            target_time_str = time.strftime('%H:%M:%S', time.localtime(game_data['next_location_broadcast_time']))
            print(f"SERVER LOGIC: Nächster Hider-Standort-Broadcast geplant für: {target_time_str} (in ca. {delay_seconds}s) in Phase '{phase_def['name']}'.")


def send_data_to_one_client(conn, player_id_for_perspective):
    payload = {}
    player_name_for_log = "N/A_IN_SEND_INIT"
    try:
        with data_lock:
            if "players" not in game_data or player_id_for_perspective not in game_data["players"]:
                # Wenn der Spieler nicht mehr existiert, sende ein Reset-Signal oder eine Fehlermeldung
                if conn:
                    null_player_payload = {"type": "game_update", "player_id": None, "error_message": "Du wurdest aus dem Spiel entfernt oder der Server wurde zurückgesetzt.", "game_state": {"status": "disconnected", "status_display": "Server zurückgesetzt. Bitte neu beitreten."}}
                    try: conn.sendall(json.dumps(null_player_payload).encode('utf-8') + b'\n')
                    except: pass 
                return

            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return # Sollte durch obige Prüfung abgedeckt sein

            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbekannter Status"))

            # --- NEU: Phaseninformationen für die UI ---
            phase_info_for_client = None
            # Sende Phaseninfo nur, wenn das Spiel gestartet wurde oder gerade läuft
            # Und wenn der Spieler auch Teil des Spiels ist (confirmed_for_lobby ist hier ein guter Indikator,
            # dass der Spieler über die Lobby hinaus ist)
            if player_info and player_info.get("confirmed_for_lobby") and \
               current_game_status in [GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]:
                
                simplified_phase_definitions = []
                for idx, phase_def in enumerate(PHASE_DEFINITIONS):
                    simplified_phase_definitions.append({
                        "name": phase_def.get("name", f"Phase {idx}"),
                        "duration_seconds": phase_def.get("duration_seconds"),
                        "updates_in_phase": phase_def.get("updates_in_phase"),
                        "update_interval_seconds": phase_def.get("update_interval_seconds"),
                        "is_initial_reveal": phase_def.get("is_initial_reveal", False)
                    })

                current_phase_idx = game_data.get("current_phase_index", -1)
                current_phase_details_for_client = None
                if 0 <= current_phase_idx < len(PHASE_DEFINITIONS):
                    current_phase_on_server = PHASE_DEFINITIONS[current_phase_idx]
                    current_phase_details_for_client = {
                        "index": current_phase_idx,
                        "name": current_phase_on_server.get("name", f"Phase {current_phase_idx}"),
                        # Zeitstempel in Millisekunden für JS Date Objekte
                        "start_time_epoch_ms": int(game_data.get("current_phase_start_time", 0) * 1000),
                        "duration_seconds": current_phase_on_server.get("duration_seconds"),
                        "updates_in_phase": current_phase_on_server.get("updates_in_phase"),
                        "update_interval_seconds": current_phase_on_server.get("update_interval_seconds"),
                        "is_initial_reveal": current_phase_on_server.get("is_initial_reveal", False),
                        "updates_done_this_phase": game_data.get("updates_done_in_current_phase", 0)
                    }
                
                next_broadcast_time_val = game_data.get("next_location_broadcast_time", float('inf'))
                # Sende als Millisekunden-Timestamp oder null
                next_broadcast_time_ms_for_client = int(next_broadcast_time_val * 1000) if next_broadcast_time_val != float('inf') else None

                phase_info_for_client = {
                    "definitions": simplified_phase_definitions,
                    "current_details": current_phase_details_for_client,
                    "next_broadcast_time_epoch_ms": next_broadcast_time_ms_for_client,
                    "hider_departure_config_seconds": HIDER_INITIAL_DEPARTURE_TIME_SECONDS,
                    # Spielstart (Beginn RUNNING Phase) für Referenz in UI, falls benötigt
                    "game_start_time_actual_epoch_ms": int(game_data.get("game_start_time_actual",0) * 1000) if game_data.get("game_start_time_actual") else None
                }
            # --- ENDE NEU ---

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
                "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set()),
                "phase_info": phase_info_for_client # Hinzufügen der neuen Phaseninfo
            }
            
            if p_role == "hider":
                payload["task_skips_available"] = player_info.get("task_skips_available", 0)
                if player_info.get("status_ingame") == "active" and player_info.get("task"):
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

        if conn and payload:
            json_payload = json.dumps(payload)
            conn.sendall(json_payload.encode('utf-8') + b'\n')
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        # print(f"SERVER SEND (ERROR - COMM): P:{player_id_for_perspective} ({player_name_for_log}): Verbindung getrennt: {e}.")
        with data_lock:
            if "players" in game_data and player_id_for_perspective in game_data["players"]:
                if game_data["players"][player_id_for_perspective].get("client_conn") == conn:
                    game_data["players"][player_id_for_perspective]["client_conn"] = None
    except Exception as e:
        print(f"SERVER SEND (ERROR - UNEXPECTED): P:{player_id_for_perspective} ({player_name_for_log}): Unerwarteter Fehler beim Senden: {e}")
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
        try: conn.sendall(json_message)
        except: # Einfaches Error-Handling für Broadcast
             with data_lock: # Client-Verbindung als None markieren, falls Fehler
                if "players" in game_data and p_id in game_data["players"] and game_data["players"][p_id].get("client_conn") == conn:
                    game_data["players"][p_id]["client_conn"] = None


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
                    task_description_for_log = p_info.get('task',{}).get('description','N/A')
                    player_name_for_log = p_info.get('name','N/A')
                    if p_id in game_data.get("players", {}): # Re-check if player still exists
                        game_data["players"][p_id]["task"] = None
                        game_data["players"][p_id]["task_deadline"] = None
                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' NICHT rechtzeitig geschafft! Aufgabe entfernt.")
                        assign_task_to_hider(p_id)

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
                if not data_chunk: break
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
                                # Allow re-join after game end by resetting server if a new join comes in after game over
                                reset_game_to_initial_state(notify_clients_about_reset=False) 
                                current_game_status_in_handler = game_data.get("status")
                            
                            if current_game_status_in_handler != GAME_STATE_LOBBY:
                                conn.sendall(json.dumps({"type":"error", "message":"Spiel läuft bereits oder ist nicht in der Lobby."}).encode('utf-8') + b'\n')
                                return
                            
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            p_role = message.get("role", "hider")
                            if p_role not in ["hider", "seeker"]: p_role = "hider"
                            player_name_for_log = p_name
                            
                            base_id = str(addr[1]) + "_" + str(random.randint(100,999))
                            id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}):
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate
                            
                            game_data.setdefault("players", {})[player_id] = {
                                "addr": addr, "name": p_name, "original_role": p_role, "current_role": p_role,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": False, "is_ready": False, "status_ingame": "active", "points": 0,
                                "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None,
                                "task_skips_available": INITIAL_TASK_SKIPS if p_role == "hider" else 0
                            }
                            print(f"SERVER JOIN-PLAYER-CREATED: {p_name} ({player_id}) von {addr}.")
                            send_data_to_one_client(conn, player_id)
                            broadcast_full_game_state_to_all(exclude_pid=player_id)
                            continue
                        
                        elif action == "FORCE_SERVER_RESET_FROM_CLIENT":
                            client_name_for_reset_log = player_name_for_log if player_id else f"Client {addr[0]}:{addr[1]}"
                            print(f"SERVER: {client_name_for_reset_log} hat Server-Reset (FORCE_SERVER_RESET_FROM_CLIENT) angefordert.")
                            
                            reset_message_for_clients = f"Server wurde von '{client_name_for_reset_log}' zurückgesetzt. Bitte neu beitreten."
                            reset_game_to_initial_state(notify_clients_about_reset=True, reset_message=reset_message_for_clients)
                            
                            try:
                                ack_payload = {"type": "acknowledgement", "message": "Server wurde erfolgreich zurückgesetzt."}
                                conn.sendall(json.dumps(ack_payload).encode('utf-8') + b'\n')
                            except Exception as e: pass # Don't care if we can't send ack, client will disconnect anyway
                            return

                        if not player_id or player_id not in game_data.get("players", {}):
                            try: conn.sendall(json.dumps({"type":"error", "message":"Nicht authentifiziert oder aus Spiel entfernt."}).encode('utf-8') + b'\n')
                            except: pass
                            return
                        
                        current_player_data = game_data["players"][player_id]
                        current_player_data["last_seen"] = time.time()
                        if current_player_data.get("client_conn") != conn:
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
                                    if time.time() > current_player_data.get("warning_sent_time", 0): # Only count as updated if warning was sent
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
                                    task_description_for_log = current_player_data.get("task",{}).get('description','N/A')
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None 
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe zu spät eingereicht! Aufgabe entfernt.")
                                    assign_task_to_hider(player_id); status_changed = True
                            if status_changed:
                                if check_game_conditions_and_end(): pass 
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)

                        elif action == "SKIP_TASK": 
                            task_skipped_successfully = False; error_message_to_client = None
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active":
                                if current_player_data.get("task"):
                                    if current_player_data.get("task_skips_available", 0) > 0:
                                        current_player_data["task_skips_available"] -= 1
                                        skipped_task_desc = current_player_data["task"].get("description", "Unbekannte Aufgabe")
                                        current_player_data["task"], current_player_data["task_deadline"] = None, None
                                        assign_task_to_hider(player_id); task_skipped_successfully = True
                                        ack_message = f"Aufgabe '{skipped_task_desc}' übersprungen. Verbleibende Skips: {current_player_data['task_skips_available']}."
                                        conn.sendall(json.dumps({"type": "acknowledgement", "message": ack_message}).encode('utf-8') + b'\n')
                                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat eine Aufgabe übersprungen.")
                                    else: error_message_to_client = "Keine Aufgaben-Skips mehr verfügbar."
                                else: error_message_to_client = "Du hast keine aktive Aufgabe zum Überspringen."
                            else: error_message_to_client = "Aufgabe kann derzeit nicht übersprungen werden."
                            
                            if error_message_to_client:
                                conn.sendall(json.dumps({"type": "error", "message": error_message_to_client}).encode('utf-8') + b'\n')
                                send_data_to_one_client(conn, player_id)
                            if task_skipped_successfully:
                                if check_game_conditions_and_end(): pass 
                                broadcast_full_game_state_to_all()
                        
                        elif action == "CATCH_HIDER": 
                            hider_id_to_catch = message.get("hider_id_to_catch"); caught = False
                            if current_player_data["current_role"] == "seeker" and hider_id_to_catch in game_data.get("players", {}):
                                hider_player_data = game_data["players"][hider_id_to_catch]
                                if hider_player_data.get("current_role") == "hider" and hider_player_data.get("status_ingame") == "active":
                                    hider_player_data["current_role"] = "seeker"; hider_player_data["status_ingame"] = "caught"
                                    hider_player_data["task"], hider_player_data["task_deadline"] = None, None
                                    hider_player_data["task_skips_available"] = 0
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Hider {hider_player_data.get('name','N/A')} gefangen!")
                                    caught = True
                            if caught:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN":
                            if player_id in game_data.get("players", {}):
                                del game_data["players"][player_id] 
                            player_id_that_left = player_id; player_id = None # Dereference player_id for this connection handler
                            try: conn.sendall(json.dumps({"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}).encode('utf-8') + b'\n')
                            except: pass 
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
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
            except json.JSONDecodeError: 
                print(f"SERVER JSON (ERROR) ({addr[1]}): P:{player_id}. Ungültiges JSON empfangen, Puffer gelöscht.")
                buffer = "" # Clear buffer on malformed JSON
            except (ConnectionResetError, BrokenPipeError, OSError): 
                # print(f"SERVER CONN (LOST) ({addr[1]}): P:{player_id}. Verbindung verloren.")
                break 
            except Exception as e_inner_loop:
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr[1]}): P:{player_id}. Aktion: {action_for_log}. Fehler: {e_inner_loop}")
                traceback.print_exc()
    except Exception as e_outer_handler: 
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr[1]}): P:{player_id}. Fehler: {e_outer_handler}")
        traceback.print_exc()
    finally:
        # print(f"SERVER CLEANUP ({addr[1]}): P:{player_id}, Name: {player_name_for_log}. Verbindung wird geschlossen.")
        player_affected_by_disconnect = False
        with data_lock:
            if player_id and player_id in game_data.get("players", {}):
                if game_data["players"][player_id].get("client_conn") is conn: # Only clear if this connection is still associated
                    game_data["players"][player_id]["client_conn"] = None
                    player_affected_by_disconnect = True
        if player_affected_by_disconnect and game_data.get("players"): 
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): pass # Re-check game state after disconnect
            broadcast_full_game_state_to_all() # Inform other clients about player list change
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
                reset_game_to_initial_state(); current_game_status = game_data.get("status")

            if previous_game_status_for_logic != current_game_status:
                broadcast_needed_due_to_time_or_state_change = True
                previous_game_status_for_logic = current_game_status
                if current_game_status in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]:
                    game_data["early_end_requests"] = set()
                    game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()

            if current_game_status == GAME_STATE_LOBBY:
                active_lobby_player_count = 0; all_in_active_lobby_ready = True
                current_players_in_lobby = game_data.get("players", {})
                if not current_players_in_lobby: all_in_active_lobby_ready = False
                else:
                    for p_info_check in current_players_in_lobby.values():
                        if p_info_check.get("confirmed_for_lobby", False):
                            active_lobby_player_count += 1
                            if not p_info_check.get("is_ready", False):
                                all_in_active_lobby_ready = False
                    if active_lobby_player_count == 0: all_in_active_lobby_ready = False
                
                MIN_PLAYERS_TO_START = 1
                if all_in_active_lobby_ready and active_lobby_player_count >= MIN_PLAYERS_TO_START:
                    game_data["status"] = GAME_STATE_HIDER_WAIT
                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_HIDER_WAIT]
                    game_data["hider_wait_end_time"] = current_time + HIDER_INITIAL_DEPARTURE_TIME_SECONDS
                    broadcast_needed_due_to_time_or_state_change = True

            elif current_game_status == GAME_STATE_HIDER_WAIT:
                if game_data.get("hider_wait_end_time"):
                    if current_time >= game_data["hider_wait_end_time"]:
                        game_data["status"] = GAME_STATE_RUNNING
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS
                        
                        # Phasenlogik initialisieren für den ersten (Initial Reveal) Broadcast
                        game_data["current_phase_index"] = 0
                        game_data["current_phase_start_time"] = current_time # Start der ersten Phase ist jetzt
                        game_data["updates_done_in_current_phase"] = 0 # Noch keine Updates in Phase 0 erfolgt
                        game_data["_last_calculated_phase_idx_for_broadcast"] = -1 # Reset for initial calculation

                        # Der Initial Reveal soll sofort passieren
                        initial_phase_def = PHASE_DEFINITIONS[0]
                        if initial_phase_def.get("is_initial_reveal"):
                             game_data["next_location_broadcast_time"] = current_time # Sofortiger Broadcast
                             print(f"SERVER LOGIC: Initialer Hider-Standort-Broadcast wird sofort nach Hider-Wartezeit durchgeführt.")
                        else: # Sollte nicht passieren, ist ein Fallback
                             _calculate_and_set_next_broadcast_time(current_time)


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
                    next_b_time = game_data.get("next_location_broadcast_time", float('inf'))
                    warning_time_trigger = next_b_time - HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS
                    
                    # Warnlogik
                    current_phase_idx_for_warn = game_data.get("current_phase_index", -1)
                    allow_warning = True
                    if 0 <= current_phase_idx_for_warn < len(PHASE_DEFINITIONS):
                        phase_def_warn = PHASE_DEFINITIONS[current_phase_idx_for_warn]
                        # Keine Warnung für sehr kurze Intervalle (z.B. Phase 5 oder wenn Intervall < Warnzeit + Puffer)
                        interval_calc_value = 1000 # Default if no interval or duration/updates is defined
                        if phase_def_warn.get("update_interval_seconds"):
                            interval_calc_value = phase_def_warn["update_interval_seconds"]
                        elif phase_def_warn.get("updates_in_phase") > 0 and phase_def_warn.get("duration_seconds") > 0:
                            interval_calc_value = phase_def_warn["duration_seconds"] / phase_def_warn["updates_in_phase"]

                        if interval_calc_value < HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS + 5: # Small buffer for safety
                            allow_warning = False
                    
                    if allow_warning and \
                       not game_data.get("hider_warning_active_for_current_cycle", False) and \
                       current_time >= warning_time_trigger and current_time < next_b_time:
                        
                        game_data["hider_warning_active_for_current_cycle"] = True
                        hiders_needing_warning_update = False
                        for p_id, p_info in game_data.get("players", {}).items():
                            if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                                if not p_info.get("has_pending_location_warning"): 
                                    p_info["has_pending_location_warning"] = True; p_info["warning_sent_time"] = current_time
                                    p_info["last_location_update_after_warning"] = 0 # Reset this to detect if new location comes in AFTER warning
                                    hiders_needing_warning_update = True
                                    if p_info.get("client_conn"):
                                        event_payload_warn = {"type": "game_event", "event_name": "hider_location_update_due"}
                                        try: p_info["client_conn"].sendall(json.dumps(event_payload_warn).encode('utf-8') + b'\n')
                                        except: 
                                             # Handle client disconnection
                                             if "players" in game_data and p_id in game_data["players"] and game_data["players"][p_id].get("client_conn") == p_info.get("client_conn"):
                                                game_data["players"][p_id]["client_conn"] = None
                        if hiders_needing_warning_update: broadcast_needed_due_to_time_or_state_change = True 

                    # Standort-Broadcast
                    if current_time >= next_b_time and next_b_time != float('inf'):
                        game_data["hider_warning_active_for_current_cycle"] = False 
                        active_hiders_who_failed_update_names = []
                        
                        player_list_copy = list(game_data.get("players", {}).items())
                        for p_id_h, p_info_h in player_list_copy:
                            if p_id_h not in game_data.get("players", {}): continue # Player might have left
                            if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                if p_info_h.get("has_pending_location_warning"): 
                                    # If last_location_update_after_warning is older than warning_sent_time, it means no new location was sent after warning
                                    if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                        active_hiders_who_failed_update_names.append(p_info_h.get('name', 'Unbekannt'))
                                # Reset warning flags regardless if they updated or not
                                game_data["players"][p_id_h]["has_pending_location_warning"] = False
                                game_data["players"][p_id_h]["warning_sent_time"] = 0
                                game_data["players"][p_id_h]["last_location_update_after_warning"] = 0

                        if active_hiders_who_failed_update_names:
                             broadcast_server_text_notification(f"Folgende Hider haben Standort nach Warnung NICHT aktualisiert: {', '.join(active_hiders_who_failed_update_names)}. Sie bleiben aktiv, aber ohne aktuellste Position für Seeker.")
                        
                        game_data["updates_done_in_current_phase"] += 1

                        for p_id_s, p_info_s in game_data.get("players", {}).items():
                            if p_info_s.get("current_role") == "seeker" and p_info_s.get("client_conn"):
                                event_payload_seeker = {"type": "game_event", "event_name": "seeker_locations_updated"}
                                try: p_info_s["client_conn"].sendall(json.dumps(event_payload_seeker).encode('utf-8') + b'\n')
                                except:
                                    if "players" in game_data and p_id_s in game_data["players"] and game_data["players"][p_id_s].get("client_conn") == p_info_s.get("client_conn"):
                                        game_data["players"][p_id_s]["client_conn"] = None
                        
                        print(f"SERVER LOGIC: Seeker-Standort-Update durchgeführt (Update {game_data['updates_done_in_current_phase']} in Phase {game_data.get('current_phase_index',0)}).")
                        _calculate_and_set_next_broadcast_time(current_time) # Nächsten Broadcast oder Phasenübergang planen
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
                    if time_since_game_end < 30 and int(current_time) % 5 == 0: broadcast_needed_due_to_time_or_state_change = True
                    elif time_since_game_end < 120 and int(current_time) % 15 == 0: broadcast_needed_due_to_time_or_state_change = True
                    # Only broadcast once right when game status changes, then less frequently
                    elif previous_game_status_for_logic != current_game_status : broadcast_needed_due_to_time_or_state_change = True

        if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
            broadcast_full_game_state_to_all()

def main_server():
    reset_game_to_initial_state()
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"!!! SERVER FATAL: Fehler beim Binden an {HOST}:{PORT}: {e}. Läuft Server bereits? !!!"); return
    server_socket.listen()
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")

    threading.Thread(target=game_logic_thread, daemon=True).start()
    print("SERVER: Game Logic Thread gestartet.")

    try:
        while True:
            conn, addr = server_socket.accept()
            thread = threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt: print("SERVER: KeyboardInterrupt. Fahre herunter.")
    except Exception as e: print(f"SERVER FATAL: Unerwarteter Fehler in Hauptschleife: {e}"); traceback.print_exc()
    finally:
        print("SERVER: Schließe Server-Socket..."); server_socket.close(); print("SERVER: Server beendet.")

if __name__ == "__main__":
    main_server()
