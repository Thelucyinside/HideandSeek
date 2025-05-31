# server.py
import socket
import threading
import json
import time
import random
from tasks import TASKS # Annahme: tasks.py existiert und enthält eine Liste von Aufgaben

HOST = '0.0.0.0'
PORT = 65432
GAME_DURATION_SECONDS = 1800 # 30 Minuten Spielzeit
HIDER_START_DELAY_SECONDS = 5 # 5 Sekunden Vorbereitungszeit für Hider
MIN_HIDER_LOCATION_UPDATE_INTERVAL = 30 # Standortupdates werden mindestens alle 30s an Seeker gesendet
MAX_HIDER_LOCATION_UPDATE_INTERVAL = 180 # Anfangs werden Standortupdates maximal alle 180s gesendet
POWER_UP_COOLDOWN_SECONDS = 300 # Power-Ups haben einen Cooldown von 5 Minuten
HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS = 20 # Hider bekommen 20s vor Standort-Broadcast eine Warnung

# Definition der Power-Ups (aktuell nur Platzhalter)
POWER_UPS = {
    "reveal_one": {"id": "reveal_one", "name": "Zeige einen Hider (präzise)", "cooldown": 300},
    "radar_ping": {"id": "radar_ping", "name": "Kurzer Radar Ping (alle Hider, ungenau)", "cooldown": 180}
}

# Spielzustände
GAME_STATE_LOBBY = "lobby"
GAME_STATE_HIDER_WAIT = "hider_wait"
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
data_lock = threading.RLock() # Reentrant Lock für den Zugriff auf game_data, um Race Conditions zu vermeiden

def reset_game_to_initial_state():
    """ Setzt das Spiel komplett zurück, entfernt alle Spieler und startet eine frische Lobby. """
    global game_data
    with data_lock:
        print("SERVER LOGIC: Spiel wird komplett auf Anfangszustand zurückgesetzt.")
        game_data.clear() # Leert alle vorhandenen Spieldaten
        game_data.update({ # Setzt die initialen Spieldaten
            "status": GAME_STATE_LOBBY,
            "status_display": GAME_STATE_DISPLAY_NAMES[GAME_STATE_LOBBY],
            "players": {}, # Dictionary, um alle Spielerinformationen zu speichern
            "game_start_time_actual": None, # Tatsächliche Startzeit des Spiels
            "game_end_time": None, # Geplante Endzeit des Spiels
            "hider_wait_end_time": None, # Endzeit der Hider-Vorbereitungsphase
            "next_seeker_hider_location_broadcast_time": 0, # Nächste Zeit für Standort-Broadcast an Seeker
            "current_hider_location_update_interval": MAX_HIDER_LOCATION_UPDATE_INTERVAL, # Aktuelles Intervall für Standortupdates
            "available_tasks": list(TASKS), # Liste der verfügbaren Aufgaben
            "game_over_message": None, # Nachricht, die am Spielende angezeigt wird
            "hider_warning_active_for_current_cycle": False, # Flag für Standortwarnung
            "early_end_requests": set(), # Set von Spieler-IDs, die ein frühes Rundenende beantragt haben
            "total_active_players_for_early_end": 0 # Gesamtzahl der aktiven Spieler für die Abstimmung
        })

def get_active_lobby_players_data():
    """ Sammelt Daten aller Spieler, die sich in der Lobby befinden und die Lobby bestätigt haben. """
    active_lobby_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("confirmed_for_lobby", False): # Nur bestätigte Lobby-Spieler
                active_lobby_players[p_id] = {
                    "name": p_info.get("name", "Unbekannt"),
                    "role": p_info.get("current_role", "hider"), 
                    "is_ready": p_info.get("is_ready", False)
                }
    return active_lobby_players

def get_all_players_public_status():
    """ Sammelt den öffentlichen Status aller Spieler im Spiel (Name, Rolle, Ingame-Status). """
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
    """ Erstellt eine sortierte Bestenliste der Hider basierend auf Punkten. """
    leaderboard = []
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("original_role") == "hider": # Nur ursprüngliche Hider in die Bestenliste
                leaderboard.append({
                    "id": p_id,
                    "name": p_info.get("name", "Unbekannt"),
                    "points": p_info.get("points", 0),
                    "status": p_info.get("status_ingame", "active")
                })
    leaderboard.sort(key=lambda x: x["points"], reverse=True) # Sortieren nach Punkten (absteigend)
    return leaderboard

def assign_task_to_hider(player_id):
    """ Weist einem Hider eine zufällige Aufgabe zu, falls er keine hat und aktiv ist. """
    with data_lock:
        player = game_data.get("players", {}).get(player_id)
        # Prüfen, ob Spieler existiert, Hider ist und aktiv ist
        if not player or player.get("current_role") != "hider" or player.get("status_ingame") != "active":
            return
        
        available_tasks_list = game_data.get("available_tasks")
        # Nur neue Aufgabe zuweisen, wenn Spieler keine aktive Aufgabe hat und Aufgaben verfügbar sind
        if not player.get("task") and available_tasks_list: 
            task = random.choice(available_tasks_list) # Zufällige Auswahl einer Aufgabe
            player["task"] = task
            player["task_deadline"] = time.time() + task.get("time_limit_seconds", 180) # Setzt Deadline
            print(f"SERVER TASK: Hider {player.get('name','N/A')} ({player_id}) neue Aufgabe: {task.get('description','N/A')}")
        elif not available_tasks_list:
            print(f"SERVER TASK: Keine Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")

def count_active_players_for_early_end():
    """ Zählt die Anzahl der aktiven Spieler, die für eine Abstimmung zum frühen Rundenende relevant sind. """
    with data_lock:
        return sum(1 for p_info in game_data.get("players", {}).values()
                   if p_info.get("status_ingame") == "active" and p_info.get("confirmed_for_lobby"))

def send_data_to_one_client(conn, player_id_for_perspective):
    """ Sendet die aktuellen Spielzustandsdaten an einen bestimmten Client. """
    payload = {}
    player_name_for_log = "N/A_IN_SEND_INIT"
    try:
        with data_lock:
            # Überprüfen, ob die player_id im game_data existiert. Falls nicht, Client informieren.
            if "players" not in game_data or player_id_for_perspective not in game_data["players"]:
                if conn: # Wenn Verbindung noch existiert
                    null_player_payload = {"type": "game_update", "player_id": None, "message": "Player removed from game."}
                    try:
                        conn.sendall(json.dumps(null_player_payload).encode('utf-8') + b'\n')
                        print(f"SERVER SEND: An P:{player_id_for_perspective} gesendet, dass er nicht mehr im Spiel ist (player_id: None).")
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        print(f"SERVER SEND (ERROR - NULL_PLAYER_PAYLOAD): P:{player_id_for_perspective} Verbindung verloren.")
                else:
                    print(f"SERVER SEND (FATAL PRE-CHECK): Spieler {player_id_for_perspective} nicht in game_data.players und keine Verbindung.")
                return

            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return # Double-Check, sollte nicht passieren nach obiger Prüfung

            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbekannter Status"))

            payload = {
                "type": "game_update", # Typ der Nachricht
                "player_id": player_id_for_perspective, # ID des Spielers
                "player_name": player_name_for_log, # Name des Spielers
                "role": p_role, # Rolle des Spielers (Hider/Seeker)
                "location": player_info.get("location"), # Letzter bekannter Standort
                "confirmed_for_lobby": player_info.get("confirmed_for_lobby", False), # Ob Spieler Lobby bestätigt hat
                "player_is_ready": player_info.get("is_ready", False), # Ob Spieler bereit ist
                "player_status": player_info.get("status_ingame", "active"), # Aktueller Status im Spiel (aktiv, gefangen etc.)
                "game_state": { # Allgemeine Spielzustandsinformationen
                    "status": current_game_status,
                    "status_display": current_status_display,
                    "game_time_left": int(game_data.get("game_end_time", 0) - time.time()) if game_data.get("game_end_time") and current_game_status == GAME_STATE_RUNNING else 0,
                    "hider_wait_time_left": int(game_data.get("hider_wait_end_time", 0) - time.time()) if game_data.get("hider_wait_end_time") and current_game_status == GAME_STATE_HIDER_WAIT else 0,
                    "game_over_message": game_data.get("game_over_message")
                },
                "lobby_players": get_active_lobby_players_data() if current_game_status == GAME_STATE_LOBBY else {}, # Spieler in der Lobby
                "all_players_status": get_all_players_public_status(), # Status aller Spieler
                "hider_leaderboard": get_hider_leaderboard() if player_info.get("original_role") == "hider" or current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS] else None, # Bestenliste für Hider
                "hider_location_update_imminent": player_info.get("has_pending_location_warning", False) if p_role == "hider" else False, # Warnung für Hider vor Standort-Broadcast
                "early_end_requests_count": len(game_data.get("early_end_requests", set())), # Anzahl der Anfragen für frühes Spielende
                "total_active_players_for_early_end": game_data.get("total_active_players_for_early_end", 0), # Gesamtzahl der Spieler für frühes Spielende
                "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set()) # Ob dieser Spieler bereits beantragt hat
            }
            
            if p_role == "hider": # Hider-spezifische Daten
                payload["task_skips_available"] = player_info.get("task_skips_available", 0) # NEU: Anzahl der verfügbaren Aufgaben-Skips

                if player_info.get("status_ingame") == "active" and player_info.get("task"):
                    p_task_info = player_info["task"]
                    payload["current_task"] = {
                        "id": p_task_info.get("id", "N/A"),
                        "description": p_task_info.get("description", "Keine Beschreibung"),
                        "points": p_task_info.get("points", 0),
                        "time_left_seconds": max(0, int(player_info.get("task_deadline", 0) - time.time())) if player_info.get("task_deadline") else 0
                    }

            if p_role == "seeker": # Seeker-spezifische Daten
                visible_hiders = {}
                current_players_copy = dict(game_data.get("players", {})) # Kopie für sichere Iteration
                for h_id, h_info in current_players_copy.items():
                    if h_info.get("current_role") == "hider" and h_info.get("status_ingame") == "active" and h_info.get("location"):
                        visible_hiders[h_id] = {
                            "name": h_info.get("name", "Unbekannter Hider"),
                            "lat": h_info["location"][0], "lon": h_info["location"][1],
                            "timestamp": time.strftime("%H:%M:%S", time.localtime(h_info.get("last_location_timestamp", time.time())))
                        }
                payload["hider_locations"] = visible_hiders # Sichtbare Hider für den Seeker

                available_pu = []
                p_power_ups_used = player_info.get("power_ups_used_time", {})
                for pu_id, pu_data in POWER_UPS.items():
                    # Prüfen, ob der Cooldown abgelaufen ist
                    if time.time() - p_power_ups_used.get(pu_id, 0) > pu_data.get("cooldown", POWER_UP_COOLDOWN_SECONDS):
                        available_pu.append({"id": pu_id, "name": pu_data.get("name", "Unbekanntes Powerup")})
                payload["power_ups_available"] = available_pu # Verfügbare Power-Ups

        # Daten als JSON an den Client senden
        if conn and payload:
            json_payload = json.dumps(payload)
            conn.sendall(json_payload.encode('utf-8') + b'\n')
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        print(f"SERVER SEND (ERROR - COMM): P:{player_id_for_perspective} ({player_name_for_log}): Verbindung getrennt: {e}.")
        with data_lock:
            # Verbindung des Spielers als None markieren, falls es die aktuelle Verbindung war
            if "players" in game_data and player_id_for_perspective in game_data["players"]:
                if game_data["players"][player_id_for_perspective].get("client_conn") == conn:
                    game_data["players"][player_id_for_perspective]["client_conn"] = None
    except Exception as e:
        print(f"SERVER SEND (ERROR - UNEXPECTED): P:{player_id_for_perspective} ({player_name_for_log}): Unerwarteter Fehler beim Senden: {e}")
        import traceback
        traceback.print_exc()

def broadcast_full_game_state_to_all(exclude_pid=None):
    """ Sendet den vollständigen Spielzustand an alle verbundenen Clients (außer einem optionalen). """
    players_to_update_with_conn = []
    with data_lock:
        for pid, pinfo in game_data.get("players", {}).items():
            if pid != exclude_pid and pinfo.get("client_conn"): # Nur Spieler mit aktiver Verbindung
                players_to_update_with_conn.append((pid, pinfo["client_conn"]))
    for p_id_to_update, conn_to_use in players_to_update_with_conn:
        send_data_to_one_client(conn_to_use, p_id_to_update)

def broadcast_server_text_notification(message_text, target_player_ids=None, role_filter=None):
    """ Sendet eine Textbenachrichtigung an bestimmte Clients oder alle. """
    message_data = {"type": "server_text_notification", "message": message_text}
    json_message = json.dumps(message_data).encode('utf-8') + b'\n'
    players_to_notify = []
    with data_lock:
        # Bestimme, welche Spieler benachrichtigt werden sollen
        player_pool = target_player_ids if target_player_ids else game_data.get("players", {}).keys()
        for p_id in player_pool:
            p_info = game_data.get("players", {}).get(p_id)
            if not p_info or not p_info.get("client_conn"): continue # Nur Spieler mit Verbindung
            if role_filter and p_info.get("current_role") != role_filter: continue # Nach Rolle filtern
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
    """ Überprüft, ob das Spiel basierend auf den aktuellen Bedingungen beendet werden sollte. """
    with data_lock:
        current_game_status = game_data.get("status")
        if current_game_status != GAME_STATE_RUNNING: return False # Spiel muss laufen für diese Checks
        current_time = time.time()
        original_hiders_exist = False
        player_ids_to_check = list(game_data.get("players", {}).keys()) # Kopie, falls Spieler während der Iteration entfernt werden

        for p_id in player_ids_to_check:
            p_info = game_data.get("players", {}).get(p_id) 
            if not p_info: continue

            if p_info.get("original_role") == "hider": original_hiders_exist = True
            
            # Überprüfen, ob eine Hider-Aufgabe abgelaufen ist
            if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                if p_info.get("task") and p_info.get("task_deadline") and current_time > p_info["task_deadline"]:
                    task_description_for_log = p_info.get('task',{}).get('description','N/A')
                    player_name_for_log = p_info.get('name','N/A')
                    if p_id in game_data.get("players", {}): # Nur aktualisieren, wenn Spieler noch im Spiel ist
                        game_data["players"][p_id]["task"] = None # Aufgabe entfernen
                        game_data["players"][p_id]["task_deadline"] = None
                        print(f"SERVER TASK: Hider {player_name_for_log} Aufgabe '{task_description_for_log}' nicht rechtzeitig geschafft (Deadline überschritten). Aufgabe entfernt.")
                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' NICHT rechtzeitig geschafft! Aufgabe entfernt.")
                        assign_task_to_hider(p_id) # Versuch, dem Hider eine neue Aufgabe zuzuweisen

        # Zähle aktive Hider neu
        current_active_hiders = sum(1 for p_info_recheck in game_data.get("players", {}).values()
                                    if p_info_recheck.get("current_role") == "hider" and p_info_recheck.get("status_ingame") == "active")

        # Spielende-Bedingung: Keine ursprünglichen Hider im Spiel (kann passieren, wenn niemand als Hider startet)
        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 and any(p.get("confirmed_for_lobby") for p in game_data.get("players", {}).values()):
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Keine Hider im Spiel gestartet. Seeker gewinnen!"
            game_data["early_end_requests"].clear() # Abstimmungsanfragen zurücksetzen
            return True

        # Spielende-Bedingung: Alle Hider gefangen/ausgeschieden
        if current_active_hiders == 0 and original_hiders_exist: # Nur wenn es überhaupt Hider gab
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Alle Hider ausgeschieden/gefangen. Seeker gewinnen!"
            game_data["early_end_requests"].clear()
            return True
        
        # Spielende-Bedingung: Zeit abgelaufen
        if game_data.get("game_end_time") and current_time > game_data["game_end_time"]:
            final_active_hiders_at_timeout = sum(1 for p_info_final in game_data.get("players", {}).values()
                                                 if p_info_final.get("current_role") == "hider" and p_info_final.get("status_ingame") == "active")
            game_data["status"] = GAME_STATE_HIDER_WINS if final_active_hiders_at_timeout > 0 else GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[game_data["status"]]
            game_data["game_over_message"] = "Zeit abgelaufen. " + ("Hider gewinnen!" if final_active_hiders_at_timeout > 0 else "Seeker gewinnen!")
            game_data["early_end_requests"].clear()
            return True
        return False # Spiel läuft weiter

def handle_client_connection(conn, addr):
    """ Behandelt die Kommunikation mit einem einzelnen Client. """
    player_id = None # Hält die ID des verbundenen Spielers
    player_name_for_log = "Unbekannt_Init"
    action_for_log = "N/A"
    print(f"SERVER CONN: Neue Verbindung von {addr}.")
    try:
        buffer = "" # Puffer für eingehende Nachrichten
        while True:
            try:
                data_chunk = conn.recv(4096) # Daten empfangen
                if not data_chunk: # Verbindung geschlossen oder unterbrochen
                    print(f"SERVER CONN ({addr[1]}): data_chunk leer. P:{player_id}, Name: {player_name_for_log}.")
                    break # Schleife beenden, Verbindung wird im finally geschlossen
                buffer += data_chunk.decode('utf-8')

                # Nachrichten am Zeilenumbruch trennen
                while '\n' in buffer:
                    message_str, buffer = buffer.split('\n', 1)
                    if not message_str.strip(): continue # Leere Nachrichten ignorieren
                    message = json.loads(message_str) # JSON parsen
                    action = message.get("action"); action_for_log = action # Aktion aus der Nachricht extrahieren

                    with data_lock: # Sperre, um game_data sicher zu modifizieren
                        current_game_status_in_handler = game_data.get("status")

                        # Aktion: Spieler tritt dem Spiel bei (nur wenn noch keine ID zugewiesen)
                        if action == "JOIN_GAME" and player_id is None:
                            # Wenn Spiel bereits beendet war, setze es zurück
                            if current_game_status_in_handler in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                                print("SERVER: JOIN_GAME erhalten, Spiel war beendet. Resette Spiel komplett.")
                                reset_game_to_initial_state() 
                                current_game_status_in_handler = game_data.get("status") # Status nach Reset aktualisieren
                            
                            # Wenn das Spiel nicht in der Lobby ist, ablehnen
                            if current_game_status_in_handler != GAME_STATE_LOBBY:
                                conn.sendall(json.dumps({"type":"error", "message":"Spiel läuft bereits oder ist nicht in der Lobby."}).encode('utf-8') + b'\n')
                                print(f"SERVER: JOIN_GAME abgelehnt (Spiel läuft/nicht Lobby) für {addr}. Verbindung wird geschlossen.")
                                return # Beendet den Handler-Thread für diese Verbindung
                            
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            p_role = message.get("role", "hider")
                            if p_role not in ["hider", "seeker"]: p_role = "hider" # Standardrolle, falls ungültig
                            player_name_for_log = p_name
                            
                            # Eindeutige Player ID generieren
                            base_id = str(addr[1]) + "_" + str(random.randint(100,999)) # Kombination aus IP-Port und Zufallszahl
                            id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}): # Sicherstellen, dass ID einzigartig ist
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate
                            
                            # Spielerinformationen im game_data speichern
                            game_data.setdefault("players", {})[player_id] = {
                                "addr": addr, "name": p_name, "original_role": p_role, "current_role": p_role,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": False, "is_ready": False, "status_ingame": "active", "points": 0,
                                "power_ups_used_time": {}, "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None,
                                "task_skips_available": INITIAL_TASK_SKIPS if p_role == "hider" else 0 # NEU: Skips zuweisen
                            }
                            print(f"SERVER JOIN-PLAYER-CREATED: {p_name} ({player_id}) von {addr}.")
                            send_data_to_one_client(conn, player_id) # Ersten Status an den neuen Client senden
                            broadcast_full_game_state_to_all(exclude_pid=player_id) # Andere Clients über neuen Spieler informieren
                            continue

                        # Prüfen, ob der Spieler authentifiziert ist für weitere Aktionen
                        if not player_id or player_id not in game_data.get("players", {}):
                            print(f"SERVER: P:{player_id} (Name: {player_name_for_log}) nicht authentifiziert oder nicht mehr im Spiel für Aktion '{action}'.")
                            try:
                                conn.sendall(json.dumps({"type":"error", "message":"Nicht authentifiziert oder aus Spiel entfernt. Bitte neu beitreten."}).encode('utf-8') + b'\n')
                            except: pass
                            return # Beendet den Handler-Thread für diese Verbindung
                        
                        current_player_data = game_data["players"][player_id] # Spielerdaten abrufen
                        current_player_data["last_seen"] = time.time() # Letzte Aktivität aktualisieren
                        if current_player_data.get("client_conn") != conn: # Falls Verbindung neu aufgebaut wurde (Reconnect)
                            current_player_data["client_conn"] = conn
                        player_name_for_log = current_player_data.get("name", "N/A")


                        # Aktion: Lobby-Beitritt bestätigen
                        if action == "CONFIRM_LOBBY_JOIN": 
                            if current_game_status_in_handler == GAME_STATE_LOBBY:
                                current_player_data["confirmed_for_lobby"] = True
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id) # Bei falschem Status nur eigenen Status senden
                        
                        # Aktion: Bereitschaft zum Spielstart setzen
                        elif action == "SET_READY": 
                            if current_game_status_in_handler == GAME_STATE_LOBBY and current_player_data.get("confirmed_for_lobby"):
                                current_player_data["is_ready"] = message.get("ready_status") == True
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        # Aktion: Standort aktualisieren
                        elif action == "UPDATE_LOCATION":
                            lat, lon = message.get("lat"), message.get("lon")
                            accuracy = message.get("accuracy") 
                            if isinstance(lat, (float, int)) and isinstance(lon, (float, int)): # Gültige Koordinaten
                                current_player_data["location"] = [lat, lon, accuracy] 
                                current_player_data["last_location_timestamp"] = time.time()
                                
                                # Wenn eine Standortwarnung aktiv war, Zeitpunkt des Updates speichern
                                if current_player_data.get("has_pending_location_warning"):
                                    if time.time() > current_player_data.get("warning_sent_time", 0):
                                         current_player_data["last_location_update_after_warning"] = time.time()
                                send_data_to_one_client(conn, player_id) # Bestätigung an den Client
                        
                        # Aktion: Aufgabe als erledigt markieren
                        elif action == "TASK_COMPLETE": 
                            status_changed = False
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active" and current_player_data.get("task"):
                                task_details = current_player_data["task"]
                                if time.time() <= current_player_data.get("task_deadline", 0): # Aufgabe rechtzeitig erledigt
                                    current_player_data["points"] += task_details.get("points", 0) # Punkte hinzufügen
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe erledigt!")
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None # Aufgabe entfernen
                                    assign_task_to_hider(player_id); status_changed = True # Neue Aufgabe zuweisen
                                else: # Aufgabe zu spät eingereicht (keine Disqualifikation mehr)
                                    task_description_for_log = current_player_data.get("task",{}).get('description','N/A')
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None 
                                    print(f"SERVER TASK: Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' zu spät eingereicht. Aufgabe entfernt.")
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe zu spät eingereicht! Aufgabe entfernt.")
                                    assign_task_to_hider(player_id) # Neue Aufgabe zuweisen
                                    status_changed = True
                            if status_changed:
                                if check_game_conditions_and_end(): pass 
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)

                        # NEUE AKTION: Aufgabe überspringen
                        elif action == "SKIP_TASK": 
                            task_skipped_successfully = False
                            error_message_to_client = None

                            if current_player_data["current_role"] == "hider" and \
                               current_player_data["status_ingame"] == "active":
                                
                                if current_player_data.get("task"): # Hat der Spieler eine aktive Aufgabe?
                                    if current_player_data.get("task_skips_available", 0) > 0: # Hat der Spieler Skips übrig?
                                        current_player_data["task_skips_available"] -= 1 # Skip verbrauchen
                                        skipped_task_desc = current_player_data["task"].get("description", "Unbekannte Aufgabe")
                                        current_player_data["task"] = None # Aktuelle Aufgabe entfernen
                                        current_player_data["task_deadline"] = None # Deadline entfernen
                                        assign_task_to_hider(player_id) # Neue Aufgabe zuweisen
                                        task_skipped_successfully = True
                                        
                                        ack_message = f"Aufgabe '{skipped_task_desc}' übersprungen. Dir verbleiben {current_player_data['task_skips_available']} Skips."
                                        conn.sendall(json.dumps({"type": "acknowledgement", "message": ack_message}).encode('utf-8') + b'\n')
                                        broadcast_server_text_notification(f"Hider {player_name_for_log} hat eine Aufgabe übersprungen.")
                                        print(f"SERVER TASK: Hider {player_name_for_log} hat Aufgabe '{skipped_task_desc}' übersprungen. Skips übrig: {current_player_data['task_skips_available']}")
                                    else:
                                        error_message_to_client = "Keine Aufgaben-Skips mehr verfügbar."
                                else:
                                    error_message_to_client = "Du hast keine aktive Aufgabe zum Überspringen."
                            else:
                                error_message_to_client = "Aufgabe kann derzeit nicht übersprungen werden."
                            
                            if error_message_to_client: # Wenn ein Fehler aufgetreten ist, Client informieren
                                conn.sendall(json.dumps({"type": "error", "message": error_message_to_client}).encode('utf-8') + b'\n')
                                send_data_to_one_client(conn, player_id) # Client seinen aktuellen (Fehler-)Status senden
                            
                            if task_skipped_successfully: # Wenn erfolgreich geskippt wurde
                                if check_game_conditions_and_end(): pass 
                                broadcast_full_game_state_to_all()
                        
                        # Aktion: Hider fangen
                        elif action == "CATCH_HIDER": 
                            hider_id_to_catch = message.get("hider_id_to_catch"); caught = False
                            if current_player_data["current_role"] == "seeker" and hider_id_to_catch in game_data.get("players", {}):
                                hider_player_data = game_data["players"][hider_id_to_catch]
                                if hider_player_data.get("current_role") == "hider" and hider_player_data.get("status_ingame") == "active":
                                    hider_player_data["current_role"] = "seeker"; hider_player_data["status_ingame"] = "caught" # Rolle und Status ändern
                                    hider_player_data["task"], hider_player_data["task_deadline"] = None, None # Aufgabe entfernen
                                    hider_player_data["task_skips_available"] = 0 # Gefangene Hider verlieren Skips
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Hider {hider_player_data.get('name','N/A')} gefangen!")
                                    caught = True
                            if caught:
                                if check_game_conditions_and_end(): pass
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        # Aktion: Power-Up verwenden
                        elif action == "USE_POWERUP": 
                            powerup_id_to_use = message.get("powerup_id"); powerup_used_successfully = False
                            if current_player_data["current_role"] == "seeker" and powerup_id_to_use in POWER_UPS:
                                pu_info = POWER_UPS[powerup_id_to_use]
                                # Prüfen, ob Cooldown abgelaufen ist
                                if time.time() - current_player_data.get("power_ups_used_time", {}).get(powerup_id_to_use, 0) > pu_info.get("cooldown", POWER_UP_COOLDOWN_SECONDS):
                                    current_player_data.setdefault("power_ups_used_time", {})[powerup_id_to_use] = time.time() # Cooldown setzen
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Power-Up '{pu_info.get('name','N/A')}' eingesetzt!")
                                    powerup_used_successfully = True
                            if powerup_used_successfully: broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id)
                        
                        # Aktion: Spiel verlassen und zum Join-Screen zurückkehren
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN":
                            print(f"SERVER: Spieler {player_name_for_log} ({player_id}) verlässt Spiel (LEAVE_GAME_AND_GO_TO_JOIN).")
                            if player_id in game_data["players"]: 
                                del game_data["players"][player_id] # Spieler aus game_data entfernen
                            
                            player_id_that_left = player_id # Temporär die ID speichern
                            player_id = None # Spieler-ID für diese Verbindung auf None setzen (nicht mehr authentifiziert)
                            
                            try:
                                conn.sendall(json.dumps({"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}).encode('utf-8') + b'\n')
                            except: pass 
                            
                            broadcast_full_game_state_to_all() # Andere Spieler informieren
                            
                            print(f"SERVER: Verbindung für P:{player_id_that_left} (Name: {player_name_for_log}) wird nach LEAVE_GAME geschlossen.")
                            return # Beendet den Handler-Thread für diese Verbindung

                        # Aktion: Frühes Rundenende beantragen
                        elif action == "REQUEST_EARLY_ROUND_END":
                            # Nur wenn Spiel läuft, Spieler aktiv ist und Lobby bestätigt hat
                            if current_game_status_in_handler == GAME_STATE_RUNNING and \
                               current_player_data.get("status_ingame") == "active" and \
                               current_player_data.get("confirmed_for_lobby"):
                                
                                game_data.setdefault("early_end_requests", set()).add(player_id) # Request hinzufügen
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end() # Aktive Spieler neu zählen
                                print(f"SERVER: Spieler {player_name_for_log} ({player_id}) beantragt frühes Rundenende. Stand: {len(game_data['early_end_requests'])}/{game_data['total_active_players_for_early_end']}")
                                
                                # Wenn genügend Spieler (alle aktiven) zugestimmt haben
                                if game_data["total_active_players_for_early_end"] > 0 and \
                                   len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    print("SERVER: Konsens für frühes Rundenende erreicht!")
                                    game_data["status"] = GAME_STATE_SEEKER_WINS # Seeker gewinnen bei frühem Ende (Standard)
                                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
                                    game_data["game_over_message"] = "Spiel durch Konsens der Spieler vorzeitig beendet. Seeker gewinnen!"
                                    game_data["early_end_requests"].clear() 
                                    if check_game_conditions_and_end(): pass # Erneuter Check, falls Kaskaden-Effekt
                                
                                broadcast_full_game_state_to_all()
                            else:
                                send_data_to_one_client(conn, player_id)


            except json.JSONDecodeError as e:
                print(f"SERVER JSON ERROR ({addr[1]}): P:{player_id}. Ungültiges JSON: '{message_str if 'message_str' in locals() else 'N/A'}'. Fehler: {e}"); buffer = ""
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"SERVER CONN ERROR ({addr[1]}): P:{player_id}. Verbindung getrennt: {e}"); break 
            except Exception as e_inner_loop:
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr[1]}): P:{player_id}. Aktion: {action_for_log}. Fehler: {e_inner_loop}"); import traceback; traceback.print_exc()
    
    except Exception as e_outer_handler: 
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr[1]}): P:{player_id}. Fehler: {e_outer_handler}"); import traceback; traceback.print_exc()
    finally:
        print(f"SERVER CLEANUP ({addr[1]}): P:{player_id}, Name: {player_name_for_log}. Verbindung wird geschlossen.")
        player_affected_by_disconnect = False
        with data_lock:
            # Nur client_conn auf None setzen, wenn diese Verbindung die aktuelle war
            if player_id and player_id in game_data.get("players", {}):
                if game_data["players"][player_id].get("client_conn") is conn:
                    game_data["players"][player_id]["client_conn"] = None
                    player_affected_by_disconnect = True
                    print(f"SERVER: Spieler {player_name_for_log} ({player_id}) client_conn auf None gesetzt (Socket {conn.fileno() if conn else 'N/A'}).")
                else:
                    print(f"SERVER: Spieler {player_name_for_log} ({player_id}) hatte bereits eine andere/keine client_conn.")
            elif not player_id: # Falls Spieler-ID bereits None ist (z.B. nach LEAVE_GAME)
                 print(f"SERVER: Spieler {player_name_for_log} (ehemals ID, jetzt None) hatte die Verbindung aktiv beendet oder wurde entfernt.")

        if player_affected_by_disconnect:
            # Wenn ein relevanter Spieler die Verbindung verliert, Spielende prüfen und broadcasten
            if game_data.get("status") == GAME_STATE_RUNNING:
                if check_game_conditions_and_end():
                    print(f"SERVER: Spiel beendet nach Client-Disconnect/Cleanup von {player_name_for_log}.")
            broadcast_full_game_state_to_all() # Zustand an alle anderen senden

        if conn: # Verbindung wirklich schließen
            try: conn.close()
            except: pass

def game_logic_thread():
    """ Der Hauptthread für die Spiellogik, der in regelmäßigen Abständen den Spielzustand aktualisiert. """
    previous_game_status_for_logic = None # Zum Erkennen von Statusänderungen
    while True:
        time.sleep(1) # Jede Sekunde prüfen
        game_ended_this_tick = False
        broadcast_needed_due_to_time_or_state_change = False
        
        with data_lock: # Sperre, um game_data sicher zu modifizieren
            current_time = time.time()
            current_game_status = game_data.get("status")
            if current_game_status is None: # Sicherheitsnetz: Falls game_data leer/defekt ist
                reset_game_to_initial_state()
                current_game_status = game_data.get("status") # Status nach Reset aktualisieren


            # Erkennen von Spielzustandsänderungen
            if previous_game_status_for_logic != current_game_status:
                broadcast_needed_due_to_time_or_state_change = True
                previous_game_status_for_logic = current_game_status
                if current_game_status == GAME_STATE_RUNNING: 
                    game_data["early_end_requests"] = set() # Abstimmungen zurücksetzen
                    game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()


            # Logik für den Lobby-Status
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
                    if active_lobby_player_count == 0: all_in_active_lobby_ready = False # Keine aktiven Spieler
                
                MIN_PLAYERS_TO_START = 1 # Mindestspielerzahl zum Start (könnte 2 oder mehr sein)
                if all_in_active_lobby_ready and active_lobby_player_count >= MIN_PLAYERS_TO_START:
                    print(f"LOGIC LOBBY: Alle {active_lobby_player_count} Spieler bereit. Starte Hider-Wartezeit...")
                    game_data["status"] = GAME_STATE_HIDER_WAIT # Übergang zum Hider-Wartezustand
                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_HIDER_WAIT]
                    game_data["hider_wait_end_time"] = current_time + HIDER_START_DELAY_SECONDS # Wartezeit setzen
                    broadcast_needed_due_to_time_or_state_change = True


            # Logik für die Hider-Wartezeit
            elif current_game_status == GAME_STATE_HIDER_WAIT:
                if game_data.get("hider_wait_end_time"):
                    if current_time >= game_data["hider_wait_end_time"]: # Wartezeit abgelaufen
                        print("LOGIC HIDER_WAIT: Zeit abgelaufen. Spiel startet!")
                        game_data["status"] = GAME_STATE_RUNNING # Spielstatus auf "läuft" setzen
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time # Aktuelle Startzeit
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS # Geplante Endzeit
                        game_data["next_seeker_hider_location_broadcast_time"] = current_time + game_data["current_hider_location_update_interval"] # Erster Standort-Broadcast
                        game_data["early_end_requests"].clear() 
                        game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()
                        
                        # Allen aktiven Hidern eine erste Aufgabe zuweisen
                        for p_id_task, p_info_task in game_data.get("players", {}).items():
                            if p_info_task.get("current_role") == "hider" and p_info_task.get("confirmed_for_lobby") and p_info_task.get("status_ingame") == "active":
                                assign_task_to_hider(p_id_task)
                        
                        # Event "game_started" an alle Clients senden (für Benachrichtigungen)
                        for p_id_event, p_info_event in game_data.get("players", {}).items():
                            if p_info_event.get("client_conn"):
                                event_payload = {"type": "game_event", "event_name": "game_started"}
                                try: p_info_event["client_conn"].sendall(json.dumps(event_payload).encode('utf-8') + b'\n')
                                except: # Fehler beim Senden: Verbindung als None markieren
                                    if "players" in game_data and p_id_event in game_data["players"] and game_data["players"][p_id_event].get("client_conn") == p_info_event.get("client_conn"):
                                        game_data["players"][p_id_event]["client_conn"] = None
                        broadcast_needed_due_to_time_or_state_change = True
                    # Countdown für die Wartezeit anzeigen
                    elif int(game_data["hider_wait_end_time"] - current_time) % 3 == 0: 
                        broadcast_needed_due_to_time_or_state_change = True

            # Logik für den laufenden Spielstatus
            elif current_game_status == GAME_STATE_RUNNING:
                if check_game_conditions_and_end(): # Prüfen, ob das Spielende erreicht ist
                    game_ended_this_tick = True 
                else: 
                    next_broadcast_time = game_data.get("next_seeker_hider_location_broadcast_time", 0)
                    warning_time_trigger = next_broadcast_time - HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS
                    
                    # Warnung an Hider senden, dass Standort bald an Seeker gesendet wird
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

                    # Standort-Broadcast an Seeker (und Prüfung auf Hider, die nicht aktualisiert haben)
                    if current_time >= next_broadcast_time:
                        game_data["hider_warning_active_for_current_cycle"] = False 
                        active_hiders_who_failed_update_names = []
                        
                        player_list_copy = list(game_data.get("players", {}).items()) # Kopie, um Probleme bei Änderungen während Iteration zu vermeiden
                        for p_id_h, p_info_h in player_list_copy:
                            if p_id_h not in game_data.get("players", {}): continue # Spieler könnte inzwischen verlassen haben
                            
                            if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                if p_info_h.get("has_pending_location_warning"): 
                                    if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                        player_name_failed_update = p_info_h.get('name', 'Unbekannt')
                                        active_hiders_who_failed_update_names.append(player_name_failed_update)
                                        print(f"SERVER LOCATION: Hider {player_name_failed_update} hat Standort nach Warnung nicht rechtzeitig aktualisiert. Bleibt im Spiel.")
                                game_data["players"][p_id_h]["has_pending_location_warning"] = False # Warnung für diesen Zyklus zurücksetzen

                        if active_hiders_who_failed_update_names:
                             broadcast_server_text_notification(f"Folgende Hider haben ihren Standort nach Warnung nicht rechtzeitig aktualisiert: {', '.join(active_hiders_who_failed_update_names)}. Sie bleiben im Spiel aktiv.")

                        # Update-Intervall anpassen (wird kürzer, je länger das Spiel läuft)
                        time_since_start = current_time - game_data.get("game_start_time_actual", current_time)
                        progress = min(1.0, time_since_start / GAME_DURATION_SECONDS if GAME_DURATION_SECONDS > 0 else 0)
                        current_interval = MAX_HIDER_LOCATION_UPDATE_INTERVAL - \
                            (MAX_HIDER_LOCATION_UPDATE_INTERVAL - MIN_HIDER_LOCATION_UPDATE_INTERVAL) * progress
                        game_data["current_hider_location_update_interval"] = current_interval
                        game_data["next_seeker_hider_location_broadcast_time"] = current_time + current_interval
                        
                        # Event "seeker_locations_updated" an Seeker senden
                        for p_id_s, p_info_s in game_data.get("players", {}).items():
                            if p_info_s.get("current_role") == "seeker" and p_info_s.get("client_conn"):
                                event_payload_seeker = {"type": "game_event", "event_name": "seeker_locations_updated"}
                                try: p_info_s["client_conn"].sendall(json.dumps(event_payload_seeker).encode('utf-8') + b'\n')
                                except: 
                                     if "players" in game_data and p_id_s in game_data["players"] and game_data["players"][p_id_s].get("client_conn") == p_info_s.get("client_conn"):
                                        game_data["players"][p_id_s]["client_conn"] = None
                        
                        print(f"SERVER LOGIC: Seeker-Standort-Update. Nächstes in {current_interval:.0f}s.")
                        broadcast_needed_due_to_time_or_state_change = True 

                    # Broadcast, um verbleibende Spielzeit zu aktualisieren (alle 5 Sekunden)
                    if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 : 
                        broadcast_needed_due_to_time_or_state_change = True
                    
                    # Broadcast, um Abstimmungsstatus zu aktualisieren (alle 10 Sekunden)
                    if int(current_time) % 10 == 0 : 
                        new_active_count = count_active_players_for_early_end()
                        if game_data.get("total_active_players_for_early_end") != new_active_count:
                            game_data["total_active_players_for_early_end"] = new_active_count
                            broadcast_needed_due_to_time_or_state_change = True


            # Logik für den Spielende-Status
            elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                if game_data.get("game_end_time"): 
                    time_since_game_end = current_time - game_data.get("game_end_time", current_time)
                    # Häufigere Updates direkt nach Spielende, dann seltener
                    if time_since_game_end < 30 and int(current_time) % 5 == 0: 
                         broadcast_needed_due_to_time_or_state_change = True
                    elif time_since_game_end < 120 and int(current_time) % 15 == 0:
                         broadcast_needed_due_to_time_or_state_change = True
                    elif previous_game_status_for_logic != current_game_status : # Immer beim ersten Übergang
                        broadcast_needed_due_to_time_or_state_change = True


        # Bei Änderungen im Spielzustand oder zu bestimmten Zeitpunkten Broadcast auslösen
        if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
            if game_ended_this_tick: 
                 print(f"LOGIC: Spiel beendet durch check_game_conditions_and_end. Finaler Status: {game_data.get('status_display', 'N/A')}.")
            elif broadcast_needed_due_to_time_or_state_change: 
                 print(f"LOGIC: Broadcast ausgelöst. Aktueller Status: {game_data.get('status_display', 'N/A')}. Zeit bis Spielende: {int(game_data.get('game_end_time', 0) - time.time()) if game_data.get('game_end_time') else 'N/A'}s")
            broadcast_full_game_state_to_all() # Sendet aktualisierten Zustand an alle Clients

def main_server():
    """ Hauptfunktion des Servers. Initialisiert den Server und wartet auf Client-Verbindungen. """
    reset_game_to_initial_state() # Spiel initial zurücksetzen
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM) # TCP-Socket erstellen
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Port sofort wiederverwendbar machen
    try:
        server_socket.bind((HOST, PORT)) # Socket an Host und Port binden
    except OSError as e:
        print(f"!!! SERVER FATAL: Fehler beim Binden des Sockets an {HOST}:{PORT}: {e}. Läuft der Server bereits? !!!")
        return # Server beenden bei fatalem Fehler
    server_socket.listen() # Auf eingehende Verbindungen lauschen
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")

    # Startet den Game Logic Thread im Hintergrund
    threading.Thread(target=game_logic_thread, daemon=True).start()
    print("SERVER: Game Logic Thread gestartet.")

    try:
        while True: # Endlosschleife zum Akzeptieren neuer Verbindungen
            conn, addr = server_socket.accept() # Akzeptiert neue Client-Verbindung
            # Startet einen neuen Thread für jeden Client, um parallele Kommunikation zu ermöglichen
            thread = threading.Thread(target=handle_client_connection, args=(conn, addr), daemon=True)
            thread.start()
    except KeyboardInterrupt:
        print("SERVER: KeyboardInterrupt empfangen. Server wird heruntergefahren.")
    except Exception as e:
        print(f"SERVER FATAL: Unerwarteter Fehler in der Haupt-Serverschleife: {e}")
        import traceback; traceback.print_exc()
    finally:
        print("SERVER: Schließe Server-Socket...")
        server_socket.close() # Server-Socket schließen
        print("SERVER: Server-Socket geschlossen. Programm beendet.")

if __name__ == "__main__":
    main_server()
