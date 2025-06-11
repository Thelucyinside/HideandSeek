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
app.secret_key = "dein_super_geheimer_und_einzigartiger_schluessel_hier_aendern_DRINGEND" # TODO: Ändern!

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

    if server_socket_global and socket_is_currently_connected:
        try:
            message_to_send = json.dumps(data).encode('utf-8') + b'\n'
            # print(f"CLIENT SEND: Sende an Server: {data}") # DEBUG LOG
            server_socket_global.sendall(message_to_send)
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
        with client_data_lock:
            client_view_data["is_socket_connected_to_server"] = False
            current_error = client_view_data.get("error_message")
            if not current_error or "Nicht mit Server verbunden" not in current_error: # Nur setzen, wenn nicht schon ein spezifischerer Fehler da ist
                 client_view_data["error_message"] = f"Nicht mit Server verbunden. Aktion '{action_sent}' nicht gesendet."
            print(f"CLIENT SEND (NO CONN): Aktion '{action_sent}' nicht gesendet. Socket: {server_socket_global}, Connected-Flag: {socket_is_currently_connected}")
    return False

def process_offline_queue():
    """
    Verarbeitet die gesammelten Offline-Aktionen und sendet sie an den Server.
    Wird in einem separaten Thread ausgeführt.
    """
    with client_data_lock:
        if not client_view_data.get("offline_action_queue") or client_view_data.get("is_processing_offline_queue"):
            if client_view_data.get("is_processing_offline_queue"):
                print("CLIENT OFFLINE QUEUE: Verarbeitung läuft bereits, überspringe.")
            return
        client_view_data["is_processing_offline_queue"] = True
        queue_to_process = list(client_view_data["offline_action_queue"]) # Kopie erstellen
        # client_view_data["offline_action_queue"].clear() # Nicht hier leeren, erst nach erfolgreichem Senden
        # Stattdessen markieren wir die gesendeten und entfernen sie später.
    
    if not queue_to_process:
        with client_data_lock:
            client_view_data["is_processing_offline_queue"] = False
        return

    print(f"CLIENT OFFLINE QUEUE: Starte Verarbeitung von {len(queue_to_process)} Offline-Aktionen.")
    successfully_sent_actions_count = 0
    remaining_actions_in_queue = list(queue_to_process) # Arbeite mit einer Kopie für Entfernungen

    for i, offline_action_package in enumerate(queue_to_process):
        action_to_send_to_server = offline_action_package.get("action_for_server")
        if action_to_send_to_server:
            print(f"CLIENT OFFLINE QUEUE: Versuche Aktion zu senden: {action_to_send_to_server.get('action')}")
            if send_message_to_server(action_to_send_to_server):
                print(f"CLIENT OFFLINE QUEUE: Aktion '{action_to_send_to_server.get('action')}' erfolgreich an Server gesendet.")
                successfully_sent_actions_count += 1
                # Markiere gesendete Aktion zum Entfernen (z.B. durch None ersetzen oder eine separate Liste)
                # Sicherer ist es, die globale Queue am Ende neu zu schreiben.
                # Für den Moment: Wir entfernen es direkt aus remaining_actions_in_queue
                # ACHTUNG: Das ist tricky, wenn wir die Originalliste `queue_to_process` iterieren.
                # Besser: Eine neue Liste aufbauen.
                # Dieser Teil wird unten korrigiert.
            else:
                print(f"CLIENT OFFLINE QUEUE: Senden der Aktion '{action_to_send_to_server.get('action')}' fehlgeschlagen.")
                with client_data_lock:
                    if not client_view_data["is_socket_connected_to_server"]:
                        print("CLIENT OFFLINE QUEUE: Verbindung während Verarbeitung verloren. Breche ab.")
                        break 
                # Aktion bleibt in remaining_actions_in_queue
        else:
            print(f"CLIENT OFFLINE QUEUE ERROR: Ungültiges Offline-Aktions-Paket: {offline_action_package}")
            # Dieses ungültige Paket sollte auch aus der Queue entfernt werden.
            # remaining_actions_in_queue.remove(offline_action_package) # Auch hier, besser am Ende neu schreiben.

    # Korrekte Methode, um die Queue zu aktualisieren:
    new_offline_queue = []
    processed_ids = set() # Um sicherzustellen, dass erfolgreich gesendete Aktionen nicht wieder hinzugefügt werden
    
    # Zuerst die erfolgreich gesendeten Aktionen identifizieren (angenommen, wir hätten sie markiert)
    # Da wir das oben nicht gemacht haben, müssen wir die Logik etwas anpassen.
    # Einfacher: Die `queue_to_process` war eine Kopie. Wir rekonstruieren die globale Queue.
    
    failed_actions_to_re_queue = []
    # Iteriere über die ursprüngliche Kopie und entscheide, was wieder in die Queue kommt
    original_queue_before_processing = []
    with client_data_lock:
        original_queue_before_processing = list(client_view_data["offline_action_queue"])

    # Temporäre Liste der Aktionen, die *nicht* erfolgreich gesendet wurden in diesem Durchlauf
    temp_failed_or_not_attempted = []
    
    # Identifiziere, welche Aktionen in `queue_to_process` NICHT gesendet wurden
    # Dies ist komplex, da `send_message_to_server` keine Unterscheidung macht, welche Aktion fehlschlug,
    # wenn mehrere in der Queue waren und die Verbindung abbrach.
    # Vereinfachung: Wenn die Verbindung während des Prozesses abbricht,
    # werden alle Aktionen, die in `queue_to_process` ab diesem Punkt waren, als nicht gesendet betrachtet.

    # NOCH EINFACHER UND ROBUSTER:
    # Wenn send_message_to_server() fehlschlägt, bricht die Schleife (fast) ab.
    # Alle Aktionen in `queue_to_process` ab dem Fehlschlagspunkt + die, die vorher schon da waren,
    # aber nicht Teil von `queue_to_process` (weil sie später hinzugefügt wurden),
    # müssen in der `offline_action_queue` bleiben oder wieder hinzugefügt werden.

    final_queue = []
    with client_data_lock:
        # Die Aktionen, die in diesem Durchgang verarbeitet werden sollten: `queue_to_process`
        # Die Aktionen, die nach dem Start der Verarbeitung neu in die globale Queue kamen:
        newly_added_during_processing = [
            item for item in client_view_data["offline_action_queue"] 
            if item not in queue_to_process # Geht von Objektidentität aus, was bei dicts schwierig sein kann.
                                            # Besser wäre es, IDs zu verwenden, wenn Aktionen IDs hätten.
                                            # Für den Moment nehmen wir an, dass die Objekte vergleichbar sind
                                            # oder dass die globale Queue nur während des Lockens modifiziert wird.
        ]
        
        # Rekonstruiere:
        # Wenn `send_message_to_server` fehlschlug, ist `is_socket_connected_to_server` False.
        # Alle Aktionen in `queue_to_process`, die NICHT erfolgreich gesendet wurden (implizit alle,
        # wenn die Verbindung verloren ging), müssen drin bleiben.
        
        # `queue_to_process` ist die Liste, die wir versucht haben zu senden.
        # `client_view_data["offline_action_queue"]` ist die globale Queue.
        # Wenn eine Aktion aus `queue_to_process` erfolgreich gesendet wurde,
        # muss sie aus `client_view_data["offline_action_queue"]` entfernt werden.
        
        # Korrekte Aktualisierung der globalen Queue
        current_global_queue = list(client_view_data["offline_action_queue"])
        actions_successfully_sent_this_run = [] # Speichere hier die Payloads der erfolgreich gesendeten Aktionen

        # Die Schleife oben muss modifiziert werden, um `actions_successfully_sent_this_run` zu füllen.
        # Dann hier:
        # client_view_data["offline_action_queue"] = [
        #    pkg for pkg in current_global_queue 
        #    if pkg.get("action_for_server") not in actions_successfully_sent_this_run
        # ]
        # Dies ist immer noch nicht perfekt, da action_for_server dicts sind.
        # Die ursprüngliche Idee mit "failed_actions_to_re_queue" ist besser.

    # Zurück zur Logik mit `failed_actions_to_re_queue`, die oben begonnen wurde:
    # `successfully_sent_actions_count` zählt, wie viele *dieses Durchlaufs* gesendet wurden.
    # `queue_to_process` war die Liste, die *dieser Durchlauf* versucht hat zu senden.
    
    # Wenn die Verbindung während der Verarbeitung abbricht, enthält `queue_to_process`
    # ab dem Fehlerpunkt die nicht gesendeten Aktionen DIESES DURCHLAUFS.

    # Richtige Logik für die Aktualisierung der Queue:
    with client_data_lock:
        temp_offline_queue = list(client_view_data["offline_action_queue"]) # Aktuelle globale Queue holen
        
        # Entferne die Aktionen, die erfolgreich gesendet wurden in diesem Durchlauf
        # (angenommen, die ersten `successfully_sent_actions_count` von `queue_to_process` waren erfolgreich)
        successfully_sent_in_this_run_objects = queue_to_process[:successfully_sent_actions_count]

        # Die neue Queue besteht aus:
        # 1. Aktionen, die in der globalen Queue waren, aber NICHT zu den erfolgreich gesendeten dieses Laufs gehören.
        client_view_data["offline_action_queue"] = [
            pkg for pkg in temp_offline_queue if pkg not in successfully_sent_in_this_run_objects
        ]
        
        # Setze Nachrichten basierend auf dem Ergebnis
        if successfully_sent_actions_count > 0 and not client_view_data["offline_action_queue"]:
             client_view_data["game_message"] = "Alle Offline-Aktionen erfolgreich synchronisiert."
        elif successfully_sent_actions_count > 0 and client_view_data["offline_action_queue"]:
             client_view_data["game_message"] = f"{successfully_sent_actions_count} Offline-Aktion(en) synchronisiert. Einige verbleiben in der Queue."
        elif client_view_data["offline_action_queue"]: # Keine erfolgreich gesendet, aber es gibt noch welche
             client_view_data["error_message"] = f"{len(client_view_data['offline_action_queue'])} Offline-Aktion(en) konnte(n) nicht synchronisiert werden."
        else: # Weder gesendet noch welche in der Queue (sollte nicht passieren, wenn queue_to_process nicht leer war)
            client_view_data["game_message"] = None 

        client_view_data["is_processing_offline_queue"] = False
        print(f"CLIENT OFFLINE QUEUE: Verarbeitung beendet. {successfully_sent_actions_count} gesendet. {len(client_view_data['offline_action_queue'])} verbleiben.")


def network_communication_thread():
    """
    Dieser Thread verwaltet die persistente Socket-Verbindung zum Spielserver.
    """
    global server_socket_global, client_view_data, SERVER_HOST, SERVER_PORT
    buffer = "" 

    while True:
        user_wants_to_connect = False
        with client_data_lock:
            user_wants_to_connect = client_view_data.get("user_has_initiated_connection", False)
        
        if not user_wants_to_connect:
            with client_data_lock:
                if client_view_data["is_socket_connected_to_server"] or server_socket_global:
                    print("CLIENT NET: Benutzer will nicht verbinden. Schließe bestehende Verbindung.")
                    client_view_data["is_socket_connected_to_server"] = False
                client_view_data["game_state"]["status_display"] = "Bereit zum Verbinden mit einem Server."
            
            if server_socket_global:
                try: 
                    server_socket_global.shutdown(socket.SHUT_RDWR)
                    server_socket_global.close()
                except Exception as e_close_user_wants_not:
                    print(f"CLIENT NET: Fehler beim Schließen des Sockets (user_wants_to_connect=false): {e_close_user_wants_not}")
                server_socket_global = None
            time.sleep(1) 
            continue 

        socket_should_be_connected = False # Lokale Kopie des Flags
        current_host_to_connect = ""
        current_port_to_connect = 0
        with client_data_lock:
            socket_should_be_connected = client_view_data["is_socket_connected_to_server"]
            current_host_to_connect = client_view_data["current_server_host"]
            current_port_to_connect = client_view_data["current_server_port"]

        if not socket_should_be_connected: # Wenn Flag sagt "nicht verbunden" oder Socket-Objekt fehlt
            if server_socket_global: # Wenn Flag false ist, aber Socket-Objekt noch da, schließen
                try:
                    print(f"CLIENT NET: Schließe alten Socket (Flag war false): {server_socket_global}")
                    server_socket_global.shutdown(socket.SHUT_RDWR)
                    server_socket_global.close()
                except Exception as e_close_old:
                    print(f"CLIENT NET: Fehler beim Schließen des alten Sockets: {e_close_old}")
                server_socket_global = None
            
            try:
                with client_data_lock: 
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"): # Nur ändern, wenn kein spezifischer Fehler angezeigt wird
                         client_view_data["game_state"]["status_display"] = f"Verbinde mit {current_host_to_connect}:{current_port_to_connect}..."
                
                print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}")
                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5) 
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                temp_sock.settimeout(None) 
                server_socket_global = temp_sock
                buffer = "" 
                print(f"CLIENT NET: Erfolgreich verbunden mit {current_host_to_connect}:{current_port_to_connect}. Socket: {server_socket_global}")

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True
                    client_view_data["error_message"] = None 
                    client_view_data["join_error"] = None # Join-Fehler auch löschen bei neuer Verbindung

                    if client_view_data.get("offline_action_queue") and not client_view_data.get("is_processing_offline_queue"):
                        print("CLIENT NET: Verbindung hergestellt, starte Verarbeitung der Offline-Queue...")
                        threading.Thread(target=process_offline_queue, daemon=True).start()

                    if client_view_data.get("player_id") and client_view_data.get("player_name"):
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": client_view_data["player_id"],
                            "name": client_view_data["player_name"]
                        }
                        try:
                            # Direkt senden, da send_message_to_server den Status prüft, der hier gerade gesetzt wird.
                            # Hier müssen wir den Socket direkt verwenden.
                            print(f"CLIENT NET: Sende REJOIN_GAME: {rejoin_payload}")
                            server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                            client_view_data["game_state"]["status_display"] = f"Sende Rejoin als {client_view_data['player_name']}..."
                            print(f"CLIENT NET: REJOIN_GAME für {client_view_data['player_name']} ({client_view_data['player_id']}) gesendet.")
                        except Exception as e_rejoin:
                            print(f"CLIENT NET: Senden von REJOIN_GAME fehlgeschlagen: {e_rejoin}. Markiere als nicht verbunden.")
                            traceback.print_exc()
                            client_view_data["is_socket_connected_to_server"] = False 
                            client_view_data["error_message"] = "Senden der Rejoin-Anfrage fehlgeschlagen."
                            if server_socket_global: # Socket schließen, wenn Rejoin-Senden fehlschlägt
                                try: server_socket_global.close()
                                except: pass
                                server_socket_global = None
                    else: 
                        if client_view_data.get("game_state",{}).get("status") == "disconnected": # Nur wenn vorher getrennt
                             client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Spielbeitritt..."

            except socket.timeout:
                print(f"CLIENT NET (TIMEOUT): Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung.")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Timeout: {current_host_to_connect}:{current_port_to_connect}."
                time.sleep(3); continue 
            except (ConnectionRefusedError, OSError) as e:
                print(f"CLIENT NET (CONN_ERROR): Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__} - {e}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Fehler: {current_host_to_connect}:{current_port_to_connect} ({type(e).__name__})."
                time.sleep(3); continue
            except Exception as e_conn:
                print(f"CLIENT NET (UNEXPECTED CONNECT ERROR): {e_conn}")
                traceback.print_exc()
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Unbekannter Verbindungsfehler: {type(e_conn).__name__}"
                time.sleep(3); continue
        
        # Erneute Prüfung des Verbindungsstatus nach dem try-except Block oben
        with client_data_lock:
            if not client_view_data["is_socket_connected_to_server"]:
                if server_socket_global:
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None
                time.sleep(0.1) # Kurze Pause vor erneutem Versuch im Hauptloop
                continue


        try:
            if not server_socket_global: 
                print("CLIENT NET (RECV PRE-CHECK): Kein server_socket_global trotz is_socket_connected_to_server=true. Markiere als getrennt.")
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                time.sleep(0.1); continue

            # print("CLIENT NET: Warte auf Daten vom Server (recv)...") # ZU VERBOSE
            data_chunk = server_socket_global.recv(8192) 
            if not data_chunk: 
                print("CLIENT NET: Server hat Verbindung getrennt (leere Daten erhalten).")
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False
                    if client_view_data.get("player_id"): # Nur wenn man im Spiel war
                        client_view_data["game_state"]["status_display"] = "Server hat Verbindung getrennt."
                        client_view_data["error_message"] = "Server hat die Verbindung beendet."
                    else: # Wenn man noch nicht im Spiel war (z.B. nur verbunden, aber kein Join)
                         client_view_data["game_state"]["status_display"] = "Verbindung zum Server beendet."
                continue 
            buffer += data_chunk.decode('utf-8') 

            while '\n' in buffer: 
                message_str, buffer = buffer.split('\n', 1)
                if not message_str.strip(): continue 
                # print(f"CLIENT RECV: Rohdaten: {message_str[:200]}") # DEBUG LOG
                message = json.loads(message_str) 

                with client_data_lock: 
                    client_view_data["is_socket_connected_to_server"] = True 
                    msg_type = message.get("type")
                    # print(f"CLIENT RECV: Verarbeite Nachricht Typ: {msg_type}") # DEBUG LOG

                    if msg_type == "game_update":
                        # Wichtig für Reset und fehlgeschlagenen Rejoin
                        if "player_id" in message and message["player_id"] is None:
                            if client_view_data["player_id"] is not None: # Nur loggen, wenn sich was ändert
                                print(f"CLIENT: Server hat player_id=None gesendet. Resette Client-Spielerdaten. Alte ID: {client_view_data['player_id']}")
                            client_view_data["player_id"] = None
                            client_view_data["player_name"] = None
                            client_view_data["role"] = None
                            client_view_data["confirmed_for_lobby"] = False
                            client_view_data["player_is_ready"] = False
                            client_view_data["current_task"] = None # Aufgaben zurücksetzen
                            client_view_data["pre_cached_tasks"] = []
                            # Offline-Queue leeren, da Aktionen ohne gültige player_id nicht sinnvoll sind.
                            if client_view_data["offline_action_queue"]:
                                print("CLIENT: player_id=None erhalten, leere Offline-Queue.")
                                client_view_data["offline_action_queue"].clear()
                            client_view_data["is_processing_offline_queue"] = False # Ggf. laufende Verarbeitung stoppen/flag zurücksetzen

                            if message.get("join_error"): client_view_data["join_error"] = message["join_error"]
                            if message.get("error_message"): client_view_data["error_message"] = message["error_message"]
                            # UI soll zum Registrierungs- oder Verbindungsbildschirm zurückkehren.

                        elif "player_id" in message and message["player_id"] is not None:
                            if client_view_data["player_id"] != message["player_id"]:
                                print(f"CLIENT: Player ID vom Server erhalten/geändert zu: {message['player_id']}")
                            client_view_data["player_id"] = message["player_id"]
                            client_view_data["join_error"] = None 

                        update_keys = [
                            "player_name", "role", "confirmed_for_lobby", "player_is_ready",
                            "player_status", "location", "game_state", "lobby_players",
                            "all_players_status", "current_task", "hider_leaderboard",
                            "hider_locations", "hider_location_update_imminent",
                            "early_end_requests_count", "total_active_players_for_early_end",
                            "player_has_requested_early_end", "task_skips_available",
                            "pre_cached_tasks"
                        ]
                        for key in update_keys:
                            if key in message: client_view_data[key] = message[key]
                        
                        # Lösche game_message und error_message nur, wenn sie nicht explizit im Update gesetzt wurden
                        # Dies verhindert, dass ein allgemeines game_update eine spezifische Fehlermeldung überschreibt.
                        if "game_message" not in message and "error_message" not in message and "join_error" not in message :
                            if client_view_data["game_state"]["status"] != "disconnected": # Nur wenn nicht gerade getrennt
                                client_view_data["game_message"] = None # Alte allgemeine Nachrichten löschen
                                # client_view_data["error_message"] = None # Alte Fehler löschen, außer Join-Error

                        # Start der Offline-Queue Verarbeitung, wenn jetzt eine ID da ist
                        if client_view_data.get("player_id") and \
                           client_view_data.get("offline_action_queue") and \
                           not client_view_data.get("is_processing_offline_queue"):
                            print("CLIENT NET: game_update mit player_id erhalten, starte Offline-Queue-Verarbeitung.")
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
                        print(f"CLIENT: Fehlernachricht vom Server: {error_text}")
                        critical_errors = [
                            "Spiel läuft bereits", "Spiel voll", "Nicht authentifiziert",
                            "Bitte neu beitreten", "Du bist nicht mehr Teil des aktuellen Spiels",
                            "Server wurde von einem Spieler zurückgesetzt", "Rejoin fehlgeschlagen",
                            "Name", "bereits vergeben", "Sitzung ungültig oder abgelaufen"
                        ]
                        if any(crit_err.lower() in error_text.lower() for crit_err in critical_errors):
                            client_view_data["join_error"] = error_text 
                            if client_view_data["player_id"] is not None: 
                                print(f"CLIENT: Kritischer Fehler vom Server '{error_text}'. Resette player_id.")
                                client_view_data["player_id"] = None
                                client_view_data["player_name"] = None; client_view_data["role"] = None
                                client_view_data["confirmed_for_lobby"] = False; client_view_data["player_is_ready"] = False
                                if client_view_data["offline_action_queue"]:
                                    print("CLIENT: Kritischer Fehler, leere Offline-Queue.")
                                    client_view_data["offline_action_queue"].clear()
                                client_view_data["is_processing_offline_queue"] = False


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
                # Nicht error_message setzen, wenn es ein erwarteter Disconnect war
                if client_view_data.get("player_id"): # Nur wenn man im Spiel war
                    client_view_data["error_message"] = "Verbindung zum Server beim Empfangen verloren."

        except Exception as e_recv_main:
            print(f"CLIENT NET (RECEIVE ERROR - UNEXPECTED): Unerwarteter Fehler beim Empfang: {e_recv_main}")
            traceback.print_exc()
            with client_data_lock:
                client_view_data["is_socket_connected_to_server"] = False 
                client_view_data["error_message"] = "Interner Client-Fehler beim Empfang von Serverdaten."
        finally:
            # Wird immer ausgeführt, auch wenn die Schleife normal verlassen wird (was sie nicht sollte)
            is_still_connected_after_loop_check = False
            with client_data_lock:
                is_still_connected_after_loop_check = client_view_data["is_socket_connected_to_server"]

            if not is_still_connected_after_loop_check: 
                if server_socket_global:
                    print(f"CLIENT NET (FINALLY): Socket wird geschlossen, da is_socket_connected_to_server=false. Socket: {server_socket_global}")
                    try: server_socket_global.close() 
                    except Exception as e_close_finally:
                         print(f"CLIENT NET (FINALLY): Fehler beim Schließen des Sockets: {e_close_finally}")
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
        # Sicherstellen, dass die UI die aktuellen Werte kennt, die der network_thread verwendet
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT
        data_to_send = client_view_data.copy() # Flache Kopie reicht hier
        data_to_send["session_nickname"] = session.get("nickname")
        data_to_send["session_role_choice"] = session.get("role_choice")
        return jsonify(data_to_send)

@app.route('/connect_to_server', methods=['POST'])
def connect_to_server_route():
    global SERVER_HOST, SERVER_PORT, server_socket_global # Zugriff auf globale Variablen
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

    print(f"CLIENT FLASK: /connect_to_server. Neue Adresse: {host}:{port}")
    server_details_changed = False
    with client_data_lock:
        if SERVER_HOST != host or SERVER_PORT != port:
            print(f"CLIENT FLASK: Serverdetails geändert von {SERVER_HOST}:{SERVER_PORT} zu {host}:{port}")
            SERVER_HOST, SERVER_PORT = host, port # Globale Variablen für network_thread aktualisieren
            client_view_data["current_server_host"] = host # Auch in client_view_data für UI und network_thread
            client_view_data["current_server_port"] = port
            server_details_changed = True

        client_view_data.update({
            "user_has_initiated_connection": True, 
            "player_id": None, "player_name": None, "role": None, # Wichtig: Spielerdaten resetten
            "confirmed_for_lobby": False, "player_is_ready": False,
            "join_error": None, "error_message": None, 
            "game_message": "Versuche Verbindung mit " + server_address,
            "offline_action_queue": [], # Alte Offline-Aktionen löschen bei Serverwechsel
            "is_processing_offline_queue": False,
        })
        # Signal an Netzwerk-Thread: Neu verbinden, auch wenn Adresse gleich blieb (falls z.B. nur Flag geändert wurde)
        client_view_data["is_socket_connected_to_server"] = False 
        print(f"CLIENT FLASK: Flags für Netzwerk-Thread gesetzt: user_has_initiated_connection=True, is_socket_connected_to_server=False")


    if server_details_changed and server_socket_global:
        print(f"CLIENT FLASK: Serverdetails geändert, schließe alten globalen Socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e_close_connect: 
            print(f"CLIENT FLASK: Fehler beim Schließen des alten Sockets bei Serverwechsel: {e_close_connect}")
            pass # Socket könnte bereits geschlossen sein
        server_socket_global = None # Wichtig: Referenz entfernen

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
    print(f"CLIENT FLASK: /register_player_details. Nick: {nickname}, Rolle: {role_choice}")

    with client_data_lock:
        client_view_data["player_name"] = nickname # Für JOIN_GAME (wird von send_message_to_server nicht direkt verwendet, aber vom Server erwartet)
        # player_id ist hier noch None, wird vom Server zugewiesen

    socket_conn_ok = False
    with client_data_lock:
        socket_conn_ok = client_view_data.get("is_socket_connected_to_server", False)

    if socket_conn_ok:
        join_payload = {"action": "JOIN_GAME", "name": nickname, "role_preference": role_choice}
        print(f"CLIENT FLASK: Sende JOIN_GAME: {join_payload}")
        if not send_message_to_server(join_payload):
            with client_data_lock: client_view_data["join_error"] = "Senden der Join-Anfrage fehlgeschlagen."
            print("CLIENT FLASK: Senden von JOIN_GAME fehlgeschlagen.")
        else:
            print("CLIENT FLASK: JOIN_GAME erfolgreich gesendet.")
    else:
        with client_data_lock: client_view_data["join_error"] = "Nicht mit Server verbunden. Bitte zuerst verbinden."
        print("CLIENT FLASK: JOIN_GAME nicht gesendet, da keine Socket-Verbindung.")


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
    if player_id_local and game_can_receive_loc: # Socket-Check erfolgt in send_message_to_server
        send_success = send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy})
        if send_success:
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy] 
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: 
            # send_message_to_server setzt bereits Fehlermeldungen in client_view_data
            return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen (siehe Hauptfehlermeldung)."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID bekannt. Bitte zuerst beitreten."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    # Den Fall "nicht verbunden" fängt send_message_to_server ab.

    # Fallback, sollte nicht erreicht werden, wenn send_message_to_server korrekt arbeitet
    return jsonify({"success": False, "message": "Standort nicht gesendet (unbekannter Grund)."}), 500


def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True):
    action_payload = {"action": action_name}; player_id_for_action = None

    if requires_player_id:
        with client_data_lock: player_id_for_action = client_view_data.get("player_id")
        if not player_id_for_action:
            with client_data_lock:
                # Kopiere den aktuellen Zustand für die Antwort
                temp_cvd = client_view_data.copy()
                temp_cvd["session_nickname"] = session.get("nickname")
                temp_cvd["session_role_choice"] = session.get("role_choice")
                # Setze eine spezifische Fehlermeldung für diese Aktion
                temp_cvd["error_message"] = f"Aktion '{action_name}' nicht möglich (keine Spieler-ID)."
            return jsonify({"success": False, **temp_cvd }), 403 # Kombiniere success=False mit dem Zustand

    if payload_key: 
        req_data = request.get_json()
        # Bei force_server_reset_from_ui ist req_data None, wenn es von /force_server_reset_from_ui kommt,
        # was ok ist, da diese Route die Adresse separat behandelt.
        # Hier gehen wir davon aus, dass andere Aktionen mit Payload JSON-Daten haben.
        if req_data is None and payload_key != "force_server_reset_from_ui": # Ausnahme für Reset
             if payload_key != "ready_status": # ready_status hat keinen req_data, sondern wird direkt übergeben
                return jsonify({"success": False, "message": "Keine JSON-Daten im Request."}), 400
        
        val_from_req = None
        if req_data:
            val_from_req = req_data.get(payload_value_from_request or payload_key)
        elif payload_key == "ready_status" and payload_value_from_request is not None: # Spezialfall für set_ready
            val_from_req = payload_value_from_request # Hier wird der boolesche Wert direkt übergeben

        if payload_key == "ready_status":
             if not isinstance(val_from_req, bool): return jsonify({"success": False, "message": "Ungültiger Wert für ready_status."}), 400
        elif val_from_req is None and payload_key != "force_server_reset_from_ui": # force_server_reset hat keinen Wert
            return jsonify({"success": False, "message": f"Fehlender Wert für '{payload_key}'."}), 400

        if val_from_req is not None or payload_key == "force_server_reset_from_ui": 
            action_payload[payload_key] = val_from_req 
    
    print(f"CLIENT FLASK: Sende generische Aktion: {action_payload}")
    success_sent = send_message_to_server(action_payload)
    
    with client_data_lock:
        if success_sent: client_view_data["error_message"] = None 
        # Die UI braucht immer den aktuellen Stand von SERVER_HOST/PORT für den Reset-Button
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT
        response_data = client_view_data.copy(); 
        response_data["action_send_success"] = success_sent 
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/set_ready', methods=['POST'])
def set_ready_route(): 
    # ready_status wird als boolescher Wert im JSON-Body erwartet
    req_data = request.get_json()
    if req_data is None or "ready_status" not in req_data or not isinstance(req_data.get("ready_status"), bool):
        return jsonify({"success": False, "message": "Ungültiger oder fehlender 'ready_status' (boolean erwartet)."}), 400
    ready_status_val = req_data.get("ready_status")
    # Übergib den Wert direkt an handle_generic_action
    return handle_generic_action("SET_READY", payload_key="ready_status", payload_value_from_request=ready_status_val)


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
        temp_cvd["session_nickname"] = session.get("nickname")
        temp_cvd["session_role_choice"] = session.get("role_choice")
        temp_cvd["error_message"] = "Aktion nicht möglich (kein aktiver Hider oder keine Spieler-ID)."
        return jsonify({"success": False, **temp_cvd}), 403

    if not current_task_local or not current_task_local.get("id"):
        with client_data_lock: temp_cvd = client_view_data.copy()
        temp_cvd["session_nickname"] = session.get("nickname")
        temp_cvd["session_role_choice"] = session.get("role_choice")
        temp_cvd["error_message"] = "Keine aktive Aufgabe zum Erledigen vorhanden."
        return jsonify({"success": False, **temp_cvd}), 400

    task_id_to_complete = current_task_local["id"]
    task_description_for_ui_msg = current_task_local.get("description", "Unbekannte Aufgabe")

    if socket_ok_local: 
        action_payload_for_server = {"action": "TASK_COMPLETE", "task_id": task_id_to_complete}
        print(f"CLIENT FLASK: Sende TASK_COMPLETE (online): {action_payload_for_server}")
        success_sent = send_message_to_server(action_payload_for_server)
        with client_data_lock:
            if success_sent: client_view_data["error_message"] = None
            response_data = client_view_data.copy()
            response_data["action_send_success"] = success_sent
            response_data["session_nickname"] = session.get("nickname")
            response_data["session_role_choice"] = session.get("role_choice")
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
        print(f"CLIENT FLASK: Füge TASK_COMPLETE_OFFLINE zur Queue hinzu: {offline_action_for_server}")
        with client_data_lock:
            client_view_data["offline_action_queue"].append(offline_package)
            client_view_data["game_message"] = offline_package["ui_message_on_cache"]
            client_view_data["current_task"] = None 
            response_data = client_view_data.copy()
            response_data["action_send_success"] = True # Lokales Speichern gilt als Erfolg für die UI
            response_data["session_nickname"] = session.get("nickname")
            response_data["session_role_choice"] = session.get("role_choice")
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
        if ':' in server_address:
            host, port_str = server_address.rsplit(':', 1)
            port = int(port_str)
        else:
            host = server_address
            port = 65432 
    except ValueError:
        return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed_for_reset = False
    with client_data_lock:
        if SERVER_HOST != host or SERVER_PORT != port:
            print(f"CLIENT FLASK (Reset): Serverdetails für Reset geändert von {SERVER_HOST}:{SERVER_PORT} zu {host}:{port}")
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed_for_reset = True
        
        client_view_data["user_has_initiated_connection"] = True # Wichtig: Verbindung soll (neu) aufgebaut werden
        client_view_data["is_socket_connected_to_server"] = False # Signal zum Neuverbinden
        # Alte Spielerdaten etc. werden durch den Reset-Befehl an den Server (und dessen Antwort) gelöscht
        # oder durch die /connect_to_server Logik, falls die Adresse sich ändert.
        # Hier ist es wichtig, dass der Reset-Befehl Priorität hat.
        
        # Leere die Offline-Queue und füge nur den Reset-Befehl hinzu
        print("CLIENT FLASK (Reset): Leere Offline-Queue und füge Reset-Befehl hinzu.")
        client_view_data["offline_action_queue"].clear() 
        reset_action_package = {
            "action_for_server": {"action": "FORCE_SERVER_RESET_FROM_CLIENT"},
            "ui_message_on_cache": f"Sende Reset-Befehl für {server_address}..."
        }
        client_view_data["offline_action_queue"].append(reset_action_package)
        client_view_data["game_message"] = reset_action_package["ui_message_on_cache"]
        client_view_data["is_processing_offline_queue"] = False # Sicherstellen, dass die Queue verarbeitet wird

    if server_details_changed_for_reset and server_socket_global:
        print(f"CLIENT FLASK (Reset): Serverdetails geändert, schließe alten globalen Socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR)
            server_socket_global.close()
        except OSError as e_close_reset:
            print(f"CLIENT FLASK (Reset): Fehler beim Schließen des alten Sockets: {e_close_reset}")
        server_socket_global = None

    # Starte die Offline-Queue-Verarbeitung explizit, wenn sie nicht schon läuft.
    # Der network_thread wird sie auch starten, aber hier können wir es beschleunigen.
    with client_data_lock:
        if client_view_data.get("offline_action_queue") and not client_view_data.get("is_processing_offline_queue"):
            print("CLIENT FLASK (Reset): Starte Offline-Queue-Verarbeitung für Reset-Befehl.")
            threading.Thread(target=process_offline_queue, daemon=True).start()
    
    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/return_to_registration', methods=['POST'])
def return_to_registration_route(): 
    print("CLIENT FLASK: /return_to_registration")
    return handle_generic_action("RETURN_TO_REGISTRATION")

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    print("CLIENT FLASK: /leave_game_and_go_to_join_screen")
    action_sent_successfully = False; message_to_user = "Versuche, Spiel zu verlassen..."
    original_player_id_if_any = None
    with client_data_lock: original_player_id_if_any = client_view_data.get("player_id")

    with client_data_lock:
        client_view_data.update({
            "user_has_initiated_connection": False, 
            "is_socket_connected_to_server": False, # Signal an network_thread zum Trennen
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
            client_view_data["game_state"]["status"] = "disconnected" # Sicherer Status
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None
    
    # Der network_thread wird den server_socket_global schließen, wenn er user_has_initiated_connection=False sieht.

    if original_player_id_if_any:
        # Versuche, Server zu informieren, aber ignoriere Fehler, da Client schon resettet ist.
        # Wichtig: send_message_to_server wird fehlschlagen, da is_socket_connected_to_server
        # gerade auf False gesetzt wurde. Das ist OK für diesen Anwendungsfall.
        # Der Server wird den Spieler nach Timeout als offline markieren oder wenn der Socket bricht.
        # Man könnte hier einen direkten Socket-Send versuchen, aber das macht es komplexer.
        # Die aktuelle Logik ist: Client resetten, Server merkt es irgendwann.
        print(f"CLIENT FLASK (Leave): Lokaler Reset durchgeführt. Player ID war {original_player_id_if_any}. Server wird Disconnect bemerken.")
        message_to_user = "Client zurückgesetzt. Server wird Abwesenheit bemerken."
        action_sent_successfully = False # Da wir nicht aktiv senden
    else:
        message_to_user = "Client zurückgesetzt (war nicht aktiv im Spiel)."
        action_sent_successfully = True 
    
    session.pop("nickname", None); session.pop("role_choice", None) 
    with client_data_lock: 
        if not client_view_data["error_message"]: # Nur setzen, wenn kein anderer Fehler da ist
            client_view_data["game_message"] = message_to_user
        
        # UI braucht immer den aktuellen Stand von SERVER_HOST/PORT für den Reset-Button
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT
        response_payload = client_view_data.copy()
        response_payload["leave_request_info"] = {"sent_successfully": action_sent_successfully, "message": message_to_user}
        response_payload["session_nickname"] = session.get("nickname") 
        response_payload["session_role_choice"] = session.get("role_choice")
    return jsonify(response_payload)


if __name__ == '__main__':
    with client_data_lock:
        client_view_data["game_state"]["status_display"] = "Initialisiere Client Flask-App..."
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT

    print("CLIENT: Starte Netzwerk-Kommunikations-Thread...")
    threading.Thread(target=network_communication_thread, daemon=True).start()

    print(f"CLIENT: Starte Flask-App auf Port {FLASK_PORT}...")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
