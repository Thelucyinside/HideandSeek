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
    
    print(f"CLIENT SEND: Attempting to send action '{action_sent}'. Socket global: {'Exists' if server_socket_global else 'None'}, Connected-Flag: {socket_is_currently_connected}, Socket Obj: {server_socket_global}")

    if server_socket_global and socket_is_currently_connected:
        try:
            server_socket_global.sendall(json.dumps(data).encode('utf-8') + b'\n')
            print(f"CLIENT SEND: Action '{action_sent}' sent successfully.")
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
            print(f"CLIENT OFFLINE QUEUE: Versuche Aktion zu senden: {action_to_send_to_server.get('action')}")
            # Versuche zu senden. send_message_to_server aktualisiert is_socket_connected_to_server bei Fehler.
            if send_message_to_server(action_to_send_to_server):
                print(f"CLIENT OFFLINE QUEUE: Offline-Aktion '{action_to_send_to_server.get('action')}' erfolgreich an Server gesendet.")
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
    print(f"CLIENT OFFLINE QUEUE: Verarbeitung beendet. {successfully_sent_actions_count} gesendet. {len(client_view_data['offline_action_queue'])} verbleiben.")


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
        # *** NEUE LOGIK START ***
        # Prüfe, ob der Benutzer überhaupt eine Verbindung herstellen will.
        user_wants_to_connect = False
        with client_data_lock:
            user_wants_to_connect = client_view_data.get("user_has_initiated_connection", False)
        
        if not user_wants_to_connect:
            # Der Thread ist im "Warte"-Modus.
            # print("CLIENT NET: User does not want to connect. Thread idling.") # Kann zu verbose sein
            with client_data_lock:
                if client_view_data["is_socket_connected_to_server"]:
                    client_view_data["is_socket_connected_to_server"] = False # Sicherstellen, dass es False ist
                client_view_data["game_state"]["status_display"] = "Bereit zum Verbinden mit einem Server."
            
            if server_socket_global:
                print(f"CLIENT NET: User does not want to connect, closing existing socket {server_socket_global}")
                try: server_socket_global.close()
                except: pass
                server_socket_global = None

            time.sleep(1) # Kurze Pause, um CPU-Last zu vermeiden
            continue # Springe zum nächsten Schleifendurchlauf und prüfe erneut
        # *** NEUE LOGIK ENDE ***

        socket_should_be_connected = False # Lokale Variable für diesen Schleifendurchlauf
        with client_data_lock:
            socket_should_be_connected = client_view_data["is_socket_connected_to_server"]
            # Beziehe den aktuellen Host und Port aus client_view_data, um Änderungen widerzuspiegeln
            current_host_to_connect = client_view_data["current_server_host"]
            current_port_to_connect = client_view_data["current_server_port"]


        # --- Verbindungsaufbau-Logik ---
        if not socket_should_be_connected: # True, wenn wir verbinden MÜSSEN
            try:
                with client_data_lock: # UI-Status aktualisieren
                    client_view_data["is_socket_connected_to_server"] = False # Stellen sicher, dass er auf False steht
                    if not client_view_data.get("error_message") and not client_view_data.get("join_error"):
                         client_view_data["game_state"]["status_display"] = f"Versuche zu verbinden mit {current_host_to_connect}:{current_port_to_connect}..."

                print(f"CLIENT NET: Neuer Verbindungsversuch zu {current_host_to_connect}:{current_port_to_connect}")
                
                # Wenn ein alter Socket existiert, explizit schließen, bevor ein neuer erstellt wird.
                # Dies ist wichtig, falls der vorherige Versuch fehlschlug, aber den Socket offen ließ.
                if server_socket_global:
                    print(f"CLIENT NET: Schließe alten Socket {server_socket_global} vor neuem Verbindungsversuch.")
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None

                temp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                temp_sock.settimeout(5) # Kurzer Timeout für den Verbindungsversuch
                temp_sock.connect((current_host_to_connect, current_port_to_connect))
                print(f"CLIENT NET: Erfolgreich verbunden mit {current_host_to_connect}:{current_port_to_connect}. Socket: {temp_sock}")
                temp_sock.settimeout(None) # Nach erfolgreichem Connect: Blockierend machen
                server_socket_global = temp_sock # Globalen Socket setzen
                buffer = "" # Puffer leeren bei neuer Verbindung

                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = True # SOFORT True setzen
                    client_view_data["error_message"] = None # Erfolgreiche Verbindung löscht allgemeine Fehler
                    client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Server-Antwort." # Allgemeinere Nachricht

                    # Offline-Queue-Verarbeitung NACHDEM is_socket_connected_to_server True ist
                    if client_view_data.get("offline_action_queue") and \
                       not client_view_data.get("is_processing_offline_queue"):
                        print("CLIENT NET: Verbindung hergestellt, starte Verarbeitung der Offline-Queue...")
                        threading.Thread(target=process_offline_queue, daemon=True).start()
                    
                    # --- REJOIN LOGIC (Versuch, eine bestehende Sitzung wiederherzustellen) ---
                    # Diese Logik läuft NACH der Offline-Queue-Verarbeitung, falls ein Reset-Befehl in der Queue war,
                    # wird der Server den Rejoin wahrscheinlich ablehnen, was korrekt ist.
                    if client_view_data.get("player_id") and client_view_data.get("player_name"):
                        rejoin_payload = {
                            "action": "REJOIN_GAME",
                            "player_id": client_view_data["player_id"],
                            "name": client_view_data["player_name"]
                        }
                        try:
                            # Direkt senden, da send_message_to_server sich selbst auf `client_view_data` basiert.
                            print(f"CLIENT NET: Sende REJOIN_GAME als {client_view_data['player_name']} ({client_view_data['player_id']}).")
                            server_socket_global.sendall(json.dumps(rejoin_payload).encode('utf-8') + b'\n')
                            client_view_data["game_state"]["status_display"] = f"Sende Rejoin-Anfrage als {client_view_data['player_name']}..."
                            print(f"CLIENT NET: REJOIN_GAME für {client_view_data['player_name']} ({client_view_data['player_id']}) gesendet.")
                        except Exception as e_rejoin:
                            print(f"CLIENT NET: Senden von REJOIN_GAME fehlgeschlagen: {e_rejoin}. Versuche Neuverbindung.")
                            traceback.print_exc()
                            client_view_data["is_socket_connected_to_server"] = False # Wenn Rejoin nicht gesendet werden konnte, Verbindung wohl nicht stabil
                            client_view_data["error_message"] = "Senden der Rejoin-Anfrage fehlgeschlagen."
                            # Der finally-Block wird den Socket schließen, wenn is_socket_connected_to_server False ist.
                    else: # Keine Player-ID vorhanden, also kein Rejoin-Versuch
                        print("CLIENT NET: Keine Spieler-ID/Name für Rejoin vorhanden. Warte auf JOIN oder Server-Update.")
                        # if client_view_data["game_state"].get("status") == "disconnected": # Nur wenn vorher disconnected, sonst überschreibt es "Verbunden..."
                        #      client_view_data["game_state"]["status_display"] = "Verbunden. Warte auf Spielbeitritt..."


            except socket.timeout:
                print(f"CLIENT NET (CONNECT TIMEOUT): Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung.")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} Zeitüberschreitung."
                time.sleep(3); continue # Kurze Pause vor erneutem Versuch
            except (ConnectionRefusedError, OSError) as e:
                # OSError kann hier auch "Network is unreachable" oder "No route to host" sein.
                print(f"CLIENT NET (CONNECT FAIL): Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__} - {e}")
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Verbindung zu {current_host_to_connect}:{current_port_to_connect} fehlgeschlagen: {type(e).__name__}"
                time.sleep(3); continue
            except Exception as e_conn:
                print(f"CLIENT NET (CONNECT ERROR - UNEXPECTED): {e_conn}")
                traceback.print_exc()
                with client_data_lock: client_view_data["game_state"]["status_display"] = f"Unbekannter Verbindungsfehler: {type(e_conn).__name__}"
                time.sleep(3); continue
        
        # Erneute Prüfung, ob die Verbindung im Rejoin-Block fehlgeschlagen ist
        with client_data_lock:
            if not client_view_data["is_socket_connected_to_server"]:
                # Wenn im vorherigen Block die Verbindung als instabil markiert wurde,
                # schließen wir hier den Socket und gehen zum nächsten Verbindungsversuch
                if server_socket_global:
                    print(f"CLIENT NET: Socket-Verbindung im Aufbau-Block als 'nicht verbunden' markiert. Schließe Socket {server_socket_global}.")
                    try: server_socket_global.close()
                    except: pass
                    server_socket_global = None
                time.sleep(0.1) # Kurze Pause, um zu häufige Reconnects zu vermeiden
                continue

        # --- Nachrichten-Empfangs-Logik ---
        try:
            if not server_socket_global: # Sollte nicht passieren, wenn is_socket_connected_to_server True ist, aber zur Sicherheit
                print("CLIENT NET (RECEIVE ERROR): server_socket_global ist None trotz is_socket_connected_to_server=True. Setze auf False.")
                with client_data_lock: client_view_data["is_socket_connected_to_server"] = False
                time.sleep(0.1); continue

            data_chunk = server_socket_global.recv(8192) # Daten empfangen
            if not data_chunk: # Server hat Verbindung geschlossen (recv gibt leeren Byte-String zurück)
                peer_name_log = "N/A"
                try: peer_name_log = server_socket_global.getpeername() if server_socket_global else 'N/A_NO_SOCK_ON_EMPTY_RECV'
                except: pass # Ignore if getpeername fails (socket already closed etc)
                print(f"CLIENT NET: Server hat Verbindung getrennt (leere Daten erhalten von {peer_name_log}).")
                with client_data_lock:
                    client_view_data["is_socket_connected_to_server"] = False
                    client_view_data["game_state"]["status_display"] = "Server hat Verbindung getrennt."
                    client_view_data["error_message"] = "Server hat die Verbindung beendet."
                continue # Geht zum nächsten Schleifendurchlauf (Verbindungsversuch)
            buffer += data_chunk.decode('utf-8') # Daten zum Puffer hinzufügen

            while '\n' in buffer: # Verarbeite alle vollständigen Nachrichten im Puffer
                message_str, buffer = buffer.split('\n', 1)
                if not message_str.strip(): continue # Leere Nachrichten ignorieren
                message = json.loads(message_str) # JSON-Nachricht parsen
                # print(f"CLIENT NET: Nachricht vom Server empfangen: {message.get('type', 'NO_TYPE')}") # Kann sehr verbose sein

                with client_data_lock: # Sperre für Änderungen an client_view_data
                    client_view_data["is_socket_connected_to_server"] = True # Nachricht erhalten -> Verbindung ist aktiv
                    msg_type = message.get("type")

                    if msg_type == "game_update":
                        # Wichtig: Wenn der Server 'player_id: null' sendet, bedeutet das, dass
                        # unsere aktuelle player_id (falls vorhanden) nicht mehr gültig ist.
                        # Dies passiert bei fehlgeschlagenem Rejoin, Server-Reset oder Rauswurf.
                        if "player_id" in message and message["player_id"] is None:
                            if client_view_data["player_id"] is not None:
                                print(f"CLIENT NET: Server hat player_id=None gesendet. Resette Client-Spielerdaten.")
                            client_view_data["player_id"] = None
                            client_view_data["player_name"] = None
                            client_view_data["role"] = None
                            client_view_data["confirmed_for_lobby"] = False
                            client_view_data["player_is_ready"] = False
                            # NEU: Auch die Offline-Queue leeren, da diese Aktionen nun ungültig sind
                            if client_view_data["offline_action_queue"]:
                                print("CLIENT NET (player_id=None): Leere Offline-Queue, da Spielerdaten resettet wurden.")
                                client_view_data["offline_action_queue"].clear()
                            client_view_data["is_processing_offline_queue"] = False

                            # join_error und error_message von Server übernehmen
                            if message.get("join_error"):
                                client_view_data["join_error"] = message["join_error"]
                            if message.get("error_message"):
                                client_view_data["error_message"] = message["error_message"]

                        elif "player_id" in message and message["player_id"] is not None:
                            # Erfolgreicher Join, Rejoin oder reguläres Update mit gültiger ID
                            if client_view_data["player_id"] != message["player_id"]:
                                print(f"CLIENT NET: Eigene Player ID vom Server erhalten/geändert zu: {message['player_id']}")
                            client_view_data["player_id"] = message["player_id"]
                            client_view_data["join_error"] = None # Erfolgreich beigetreten/rejoined -> kein Join-Error mehr

                        # Aktualisiere andere Schlüssel in client_view_data mit den empfangenen Werten
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

                        # NEU: Starte Verarbeitung der Offline-Queue, wenn Spieler-ID vorhanden und Queue nicht leer
                        # Dies ist ein Fallback, falls die Queue nach dem initialen Connect nicht abgearbeitet wurde oder neue Items enthält.
                        if client_view_data.get("player_id") and \
                           client_view_data.get("offline_action_queue") and \
                           not client_view_data.get("is_processing_offline_queue"):
                            print("CLIENT NET (game_update): Starte Verarbeitung der Offline-Queue (z.B. nach erfolgreichem Rejoin oder wenn neue Items da sind).")
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

                    elif msg_type == "error": # Generische Fehlermeldung vom Server
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
            # print(f"CLIENT NET: Entering finally block of receive loop. is_still_connected_after_loop: {is_still_connected_after_loop}") # Kann zu verbose sein

            if not is_still_connected_after_loop: 
                if server_socket_global:
                    print(f"CLIENT NET: Closing socket {server_socket_global} in finally block of receive loop.")
                    try: server_socket_global.close() 
                    except: pass
                    server_socket_global = None 
                # else:
                    # print("CLIENT NET: No global socket to close in finally block of receive loop.") # Kann zu verbose sein
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
    """Gibt den aktuellen Zustand des Clients als JSON für die UI zurück."""
    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST 
        client_view_data["current_server_port"] = SERVER_PORT
        data_to_send = client_view_data.copy()
        data_to_send["session_nickname"] = session.get("nickname")
        data_to_send["session_role_choice"] = session.get("role_choice")
        return jsonify(data_to_send)

@app.route('/connect_to_server', methods=['POST'])
def connect_to_server_route():
    """Stellt nur die Verbindung zum Server her, ohne einen Spieler zu registrieren."""
    global SERVER_HOST, SERVER_PORT, server_socket_global
    data = request.get_json()
    print(f"CLIENT FLASK: /connect_to_server. Received data: {data}") # Logging hinzugefügt

    if not data or 'server_address' not in data:
        return jsonify({"success": False, "message": "Server-Adresse fehlt."}), 400

    server_address = data['server_address'].strip()
    print(f"CLIENT FLASK: /connect_to_server. Attempting to connect to: {server_address}") # Logging hinzugefügt
    if not server_address:
        return jsonify({"success": False, "message": "Server-Adresse darf nicht leer sein."}), 400

    try:
        if ':' in server_address:
            host, port_str = server_address.rsplit(':', 1)
            port = int(port_str)
        else:
            host = server_address
            port = 65432 # Standard-Port
    except ValueError:
        return jsonify({"success": False, "message": "Ungültiger Port in der Adresse."}), 400

    server_details_changed = False
    with client_data_lock:
        old_host, old_port = SERVER_HOST, SERVER_PORT # Für Logging
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
            "is_socket_connected_to_server": False, # Wichtig: Signal an Netzwerk-Thread: Neu verbinden
            # Die Offline-Queue wird hier *nicht* geleert. Sie könnte wichtige Aktionen
            # enthalten, die für den *neuen* Server relevant sind (z.B. ein Reset-Befehl).
            # Sie wird nur geleert, wenn player_id=None vom Server kommt oder bei leave_game.
        })
        print(f"CLIENT FLASK: Flags für Netzwerk-Thread gesetzt: user_has_initiated_connection=True, is_socket_connected_to_server=False")

    # Wichtig: Socket schließen, damit Netzwerk-Thread ihn neu aufbaut
    if server_socket_global: # Nur wenn er existiert
        if server_details_changed:
            print(f"CLIENT FLASK: Server details changed, shutting down old socket: {server_socket_global}")
        else: # Auch wenn Adresse gleich ist, ein expliziter "Connect"-Klick soll neu verbinden
            print(f"CLIENT FLASK: Re-connecting to same server, shutting down existing socket: {server_socket_global}")
        try:
            server_socket_global.shutdown(socket.SHUT_RDWR) # Wichtig, um dem anderen Ende mitzuteilen, dass wir schließen
            server_socket_global.close()
        except OSError as e:
            # Ignoriere Fehler, wenn der Socket bereits geschlossen ist (z.B. "Socket is not connected")
            print(f"CLIENT FLASK: Error shutting down socket (ignorable if already closed): {e}")
        finally: # Sicherstellen, dass die Referenz weg ist
            server_socket_global = None

    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")

    return jsonify(response_data)


@app.route('/register_player_details', methods=['POST'])
def register_player_details_route():
    """Registriert den Spieler mit Namen und Rolle auf dem verbundenen Server."""
    print("CLIENT FLASK: /register_player_details called.") # Logging
    data = request.get_json()
    nickname, role_choice = data.get('nickname'), data.get('role')

    if not nickname or not role_choice:
        return jsonify({"success": False, "message": "Name oder Rolle fehlt."}), 400

    session["nickname"], session["role_choice"] = nickname, role_choice

    with client_data_lock:
        client_view_data["player_name"] = nickname # Für JOIN_GAME an Server senden

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
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/update_location_from_browser', methods=['POST'])
def update_location_from_browser():
    """Empfängt Standortdaten vom Browser und leitet sie an den Spielserver weiter."""
    data = request.get_json()
    if not data: return jsonify({"success": False, "message": "Keine Daten."}), 400
    lat, lon, accuracy = data.get('lat'), data.get('lon'), data.get('accuracy')
    if lat is None or lon is None or accuracy is None: return jsonify({"success": False, "message": "Unvollständige Standortdaten."}), 400

    player_id_local, game_status_local, socket_ok_local = None, None, False
    with client_data_lock: # Daten unter Lock lesen
        player_id_local = client_view_data.get("player_id")
        game_status_local = client_view_data.get("game_state", {}).get("status")
        socket_ok_local = client_view_data.get("is_socket_connected_to_server", False)

    game_can_receive_loc = game_status_local in [GAME_STATE_LOBBY, GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]
    if player_id_local and game_can_receive_loc and socket_ok_local:
        send_success = send_message_to_server({"action": "UPDATE_LOCATION", "lat": lat, "lon": lon, "accuracy": accuracy})
        if send_success:
            with client_data_lock: client_view_data["location"] = [lat, lon, accuracy] 
            return jsonify({"success": True, "message": "Standort an Server gesendet."})
        else: return jsonify({"success": False, "message": "Senden an Server fehlgeschlagen."}), 500
    elif not player_id_local: return jsonify({"success":False, "message":"Keine Spieler-ID bekannt. Bitte zuerst beitreten."}), 403
    elif not game_can_receive_loc: return jsonify({"success":False, "message":f"Spielstatus '{game_status_local}' erlaubt keine Standortupdates."}), 400
    else: return jsonify({"success": False, "message": "Keine aktive Socket-Verbindung zum Spielserver."}), 503

def handle_generic_action(action_name, payload_key=None, payload_value_from_request=None, requires_player_id=True):
    """
    Hilfsfunktion zum Senden generischer Aktionen an den Server.
    Prüft Player-ID und Sendeerfolg.
    """
    print(f"CLIENT FLASK: Handling generic action: {action_name}") # Logging
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
        if req_data is None and payload_key != "ready_status": return jsonify({"success": False, "message": "Keine JSON-Daten im Request."}), 400
        val_from_req = req_data.get(payload_value_from_request or payload_key) if req_data else None

        if payload_key == "ready_status":
             if not isinstance(val_from_req, bool): return jsonify({"success": False, "message": "Ungültiger Wert für ready_status (muss boolean sein)."}), 400
        elif val_from_req is None and payload_key != "force_server_reset_from_ui": 
            return jsonify({"success": False, "message": f"Fehlender Wert für '{payload_key}' in Request-Daten."}), 400

        if val_from_req is not None or payload_key == "force_server_reset_from_ui": 
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

# --- Flask Routen für Spielaktionen ---
@app.route('/set_ready', methods=['POST'])
def set_ready_route(): return handle_generic_action("SET_READY", "ready_status", "ready_status")

@app.route('/complete_task', methods=['POST'])
def complete_task_route():
    print("CLIENT FLASK: /complete_task called.") # Logging
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
        return jsonify({"success": False, "message": "Aktion nicht möglich (kein aktiver Hider oder keine Spieler-ID).", **temp_cvd}), 403

    if not current_task_local or not current_task_local.get("id"):
        with client_data_lock: temp_cvd = client_view_data.copy()
        temp_cvd["session_nickname"] = session.get("nickname")
        temp_cvd["session_role_choice"] = session.get("role_choice")
        return jsonify({"success": False, "message": "Keine aktive Aufgabe zum Erledigen vorhanden.", **temp_cvd}), 400

    task_id_to_complete = current_task_local["id"]
    task_description_for_ui_msg = current_task_local.get("description", "Unbekannte Aufgabe")

    if socket_ok_local: 
        action_payload_for_server = {"action": "TASK_COMPLETE", "task_id": task_id_to_complete}
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
            "ui_message_on_cache": f"Aufgabe '{task_description_for_ui_msg}' offline als erledigt markiert. Wird bei Verbindung gesendet."
        }
        with client_data_lock:
            client_view_data["offline_action_queue"].append(offline_package)
            client_view_data["game_message"] = offline_package["ui_message_on_cache"]
            client_view_data["current_task"] = None
            response_data = client_view_data.copy()
            response_data["action_send_success"] = True 
            response_data["session_nickname"] = session.get("nickname")
            response_data["session_role_choice"] = session.get("role_choice")
        print(f"CLIENT FLASK: Aufgabe '{task_description_for_ui_msg}' (ID: {task_id_to_complete}) offline erledigt, zur Queue hinzugefügt.")
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
        old_host, old_port = SERVER_HOST, SERVER_PORT # Für Logging
        if SERVER_HOST != host or SERVER_PORT != port:
            SERVER_HOST, SERVER_PORT = host, port
            client_view_data["current_server_host"] = host
            client_view_data["current_server_port"] = port
            server_details_changed = True
            print(f"CLIENT FLASK (Reset): Serverdetails geändert von {old_host}:{old_port} zu {host}:{port}")
        
        client_view_data["user_has_initiated_connection"] = True # Anweisen, zu verbinden
        client_view_data["is_socket_connected_to_server"] = False # Signal an Netzwerk-Thread: Neu verbinden
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
            print(f"CLIENT FLASK (Reset): Error shutting down socket (ignorable if already closed): {e}")
        finally:
            server_socket_global = None

    # Reset-Befehl in die Offline-Warteschlange legen
    with client_data_lock:
        reset_action = {
            "action_for_server": {"action": "FORCE_SERVER_RESET_FROM_CLIENT"},
            "ui_message_on_cache": f"Reset-Befehl für {server_address} in Warteschlange..."
        }
        client_view_data["offline_action_queue"].clear() 
        client_view_data["offline_action_queue"].append(reset_action)
        client_view_data["game_message"] = reset_action["ui_message_on_cache"] # UI Feedback
        print("CLIENT FLASK (Reset): Reset-Aktion zur Offline-Queue hinzugefügt. NICHT direkt gestartet.")
        # KEIN direkter Start von process_offline_queue mehr von hier!
        # Der network_communication_thread wird es tun, wenn er (wieder) verbunden ist.
    
    with client_data_lock:
        response_data = client_view_data.copy()
        response_data["session_nickname"] = session.get("nickname")
        response_data["session_role_choice"] = session.get("role_choice")
    return jsonify(response_data)

@app.route('/return_to_registration', methods=['POST'])
def return_to_registration_route():
    print("CLIENT FLASK: /return_to_registration called.") # Logging
    return handle_generic_action("RETURN_TO_REGISTRATION")

@app.route('/leave_game_and_go_to_join_screen', methods=['POST'])
def leave_game_and_go_to_join_screen_route():
    print("CLIENT FLASK: /leave_game_and_go_to_join_screen called.") # Logging
    action_sent_successfully = False; message_to_user = "Versuche, Spiel zu verlassen..."
    original_player_id_if_any = None
    
    current_socket_is_connected_for_send = False # Lokale Variable
    with client_data_lock: # Hole Player ID und aktuellen Socket-Status für Sendung
        original_player_id_if_any = client_view_data.get("player_id")
        current_socket_is_connected_for_send = client_view_data.get("is_socket_connected_to_server", False)
        
    # Lokalen Client-Zustand sofort zurücksetzen
    with client_data_lock:
        client_view_data.update({
            "user_has_initiated_connection": False, # WICHTIG: Stoppt weitere Verbindungsversuche
            "player_id": None, "player_name": None, "role": None, # IMMEDIATE RESET
            "confirmed_for_lobby": False, "player_is_ready": False, "player_status": "active",
            "current_task": None, "hider_leaderboard": [], "hider_locations": {},
            "game_message": None, "error_message": None, "join_error": None, # Alte Nachrichten/Fehler löschen
            "hider_location_update_imminent": False,
            "early_end_requests_count": 0, "total_active_players_for_early_end": 0,
            "player_has_requested_early_end": False, "task_skips_available": 0,
            "offline_action_queue": [], # WICHTIG: Leere die Offline-Aktions-Queue
            "is_processing_offline_queue": False, 
            "pre_cached_tasks": [], 
        })
        if "game_state" in client_view_data and client_view_data["game_state"] is not None:
            client_view_data["game_state"]["status"] = GAME_STATE_LOBBY 
            client_view_data["game_state"]["status_display"] = "Zurück zum Beitrittsbildschirm..."
            client_view_data["game_state"]["game_over_message"] = None
        client_view_data["is_socket_connected_to_server"] = False # Signalisiere dem Netzwerkthread, die Verbindung zu trennen
        print(f"CLIENT FLASK (Leave): Lokaler Client-Zustand zurückgesetzt. user_has_initiated_connection=False. Player ID war: {original_player_id_if_any}")

    # Versuche, den Server über das Verlassen zu informieren
    # Benutze den *vorher* gelesenen Socket-Status. `send_message_to_server` wird den globalen Socket verwenden,
    # der durch den obigen Block möglicherweise bald geschlossen wird, aber wir versuchen es trotzdem.
    if original_player_id_if_any and server_socket_global and current_socket_is_connected_for_send:
        print(f"CLIENT FLASK (Leave): Versuche, LEAVE_GAME an Server zu senden für Player ID: {original_player_id_if_any}")
        if send_message_to_server({"action": "LEAVE_GAME_AND_GO_TO_JOIN"}):
            action_sent_successfully = True; message_to_user = "Anfrage zum Verlassen an Server gesendet."
            session.pop("nickname", None); session.pop("role_choice", None) # Session-Daten löschen
            with client_data_lock: client_view_data["game_message"] = message_to_user
        else:
            # send_message_to_server hat bereits eine Fehlermeldung in client_view_data gesetzt
            message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden (Sendefehler). Clientseitig zurückgesetzt."
            # with client_data_lock: client_view_data["error_message"] = message_to_user # Nicht überschreiben
            print(f"CLIENT FLASK (Leave): Senden von LEAVE_GAME an Server fehlgeschlagen.")
    elif original_player_id_if_any:
        # Konnte Anfrage nicht senden, aber Client ist bereits zurückgesetzt
        message_to_user = "Konnte Verlassen-Anfrage nicht an Server senden (Socket nicht bereit). Clientseitig zurückgesetzt."
        with client_data_lock: client_view_data["error_message"] = message_to_user
        print(f"CLIENT FLASK (Leave): Kein Socket oder nicht verbunden, um LEAVE_GAME zu senden.")
    else:
        # Der Spieler war ohnehin nicht im Spiel, nur Client-Reset bestätigen
        action_sent_successfully = True; message_to_user = "Client zurückgesetzt (war nicht aktiv im Spiel)."
        session.pop("nickname", None); session.pop("role_choice", None)
        with client_data_lock: client_view_data["game_message"] = message_to_user

    # Sende den aktualisierten Client-Zustand als Antwort an die UI
    with client_data_lock:
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT
        response_payload = client_view_data.copy()
        response_payload["leave_request_info"] = {"sent_successfully": action_sent_successfully, "message": message_to_user}
        response_payload["session_nickname"] = session.get("nickname") 
        response_payload["session_role_choice"] = session.get("role_choice")
    return jsonify(response_payload)


if __name__ == '__main__':
    # Initialisiere traceback für bessere Fehlermeldungen in Threads
    import traceback
    print("CLIENT: Initialisiere Client...")

    with client_data_lock:
        client_view_data["game_state"]["status_display"] = "Initialisiere Client Flask-App..."
        client_view_data["current_server_host"] = SERVER_HOST
        client_view_data["current_server_port"] = SERVER_PORT

    # Starte den Netzwerk-Kommunikations-Thread als Daemon-Thread
    # Daemon-Threads werden beendet, wenn das Hauptprogramm endet.
    print("CLIENT: Starte Netzwerk-Kommunikations-Thread...")
    threading.Thread(target=network_communication_thread, daemon=True).start()

    # Starte die Flask-Web-App
    # host='0.0.0.0' macht die App von außen erreichbar (z.B. für Browser auf dem Handy)
    # debug=False für den Produktionseinsatz
    print(f"CLIENT: Starte Flask-App auf Port {FLASK_PORT}...")
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=False)
    print("CLIENT: Flask-App beendet.")
