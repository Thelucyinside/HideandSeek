<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
    <title>Hide and Seek JS Client</title>
    <link rel="manifest" href="manifest.json">
    <meta name="theme-color" content="#007bff">

    <style>
        /* Allgemeine Stile für Body und Container */
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            margin: 0;
            padding: 10px;
            background-color: #f4f4f8;
            color: #333;
            font-size: 16px;
            line-height: 1.5;
        }
        .container {
            background-color: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 15px;
        }
        h1, h2, h3, h4 {
            color: #333;
            margin-top: 0;
            margin-bottom: 0.5em;
        }
        h1 { font-size: 1.8em; }
        h2 { font-size: 1.5em; }
        h3 { font-size: 1.2em; }
        h4 { font-size: 1.1em; }
        .info {
            margin-bottom: 8px;
            padding: 8px 0;
            border-bottom: 1px solid #eee;
        }
        .info:last-child { border-bottom: none; }
        .info strong { color: #555; }

        /* Listen-Stile */
        .player-list { list-style: none; padding-left: 0; }
        .player-list li { padding: 8px; border-bottom: 1px solid #f0f0f0; }
        .player-list li:last-child { border-bottom: none; }
        .highlight { background-color: #e6f7ff; font-weight: bold; }

        /* --- NEUES, JITTER-FREIES BENACHRICHTIGUNGSSYSTEM --- */
        #notification-container {
            position: fixed; /* Absolut entscheidend: Nimmt das Element aus dem Dokumentenfluss */
            top: 15px;
            left: 50%;
            transform: translateX(-50%); /* Zentriert das Element horizontal */
            width: 90%;
            max-width: 500px;
            z-index: 1000; /* Stellt sicher, dass es über allem anderen liegt */
            pointer-events: none; /* Klicks "fallen durch" den leeren Container */
        }

        .notification {
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            text-align: center;
            opacity: 0;
            transform: translateY(-20px);
            transition: opacity 0.3s ease-out, transform 0.3s ease-out;
            pointer-events: auto; /* Benachrichtigungen selbst sind wieder klickbar (falls nötig) */
            color: #fff;
            font-weight: 500;
        }

        .notification.visible {
            opacity: 1;
            transform: translateY(0);
        }

        .notification.error {
            background-color: #dc3545; /* Roter Hintergrund */
        }

        .notification.success {
            background-color: #28a745; /* Grüner Hintergrund */
        }
        /* --- ENDE DES NEUEN SYSTEMS --- */


        /* Button- und Input-Stile */
        button, input[type="submit"] {
            display: block; width: 100%; padding: 12px 15px; margin: 10px 0;
            background-color: #007bff; color: white; border: none; border-radius: 5px;
            cursor: pointer; font-size: 1em; transition: background-color 0.2s ease;
        }
        button:hover, input[type="submit"]:hover { background-color: #0056b3; }
        button:disabled { background-color: #ccc; cursor: not-allowed; }
        button.ready { background-color: #28a745; }
        button.ready:hover { background-color: #1e7e34; }
        button.unready { background-color: #ffc107; color: #333; }
        button.unready:hover { background-color: #d39e00; }
        button.action-btn { background-color: #17a2b8; margin-top: 5px; font-size: 0.9em; padding: 8px 10px; }
        button.action-btn:hover { background-color: #117a8b; }
        button.warning-btn { background-color: #ffc107; color: #212529; }
        button.warning-btn:hover { background-color: #e0a800; }
        button.danger-btn { background-color: #dc3545; }
        button.danger-btn:hover { background-color: #c82333; }
        input[type="text"], input[type="number"], select {
            width: calc(100% - 22px); padding: 10px; margin-bottom: 10px;
            border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; font-size: 1em;
        }
        label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }

        /* Countdown und Statusanzeigen */
        .countdown {
            font-size: 1.8em; font-weight: bold; color: #dc3545; text-align: center;
            padding:10px; background-color: #fff3cd; border-radius: 5px; margin: 10px 0;
        }
        .status-active { color: green; font-weight: bold; }
        .status-caught { color: orange; font-weight: bold; }
        .status-failed, .status-failed-loc, .status-failed_task, .status-failed_loc_update { color: red; font-weight: bold; }
        .status-offline { color: #888; font-style: italic; }
        .status-connected { color: green; font-weight: bold; }
        .status-disconnected { color: red; font-weight: bold; }
        .status-connecting { color: orange; font-weight: bold; }

        /* Leaderboard */
        .leaderboard { width: 100%; border-collapse: collapse; margin-top:10px; }
        .leaderboard th, .leaderboard td { text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }
        .leaderboard th { background-color: #f8f9fa; color: #333; }

        /* Haupt-Sichtbarkeitssteuerung */
        .section { display: none; }
        .section.visible { display: block; }

        .visibility-container { visibility: hidden; opacity: 0; height: 0; transition: visibility 0s 0.2s, opacity 0.2s, height 0.2s; }
        .visibility-container.visible { visibility: visible; opacity: 1; height: auto; transition: opacity 0.2s, height 0.2s; }

        /* Hilfsstile */
        .centered-text { text-align: center; }
        .dimmed { color: #777; }
        #server-management-container {
            margin-top: 30px;
            padding: 15px;
            border-top: 2px dashed #ccc;
            background-color: #f8f9fa; /* Leichter Hintergrund zur Abgrenzung */
            border-radius: 8px;
        }
        #server-management-container p { font-size: 0.8em; color: #777; margin-bottom: 0; }
        #server-management-container button {
            font-size: 0.9em;
            padding: 8px 10px;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div id="notification-container">
        <div id="game-message" class="notification success"></div>
        <div id="error-message" class="notification error"></div>
        <div id="location-error-message" class="notification error"></div>
    </div>

    <div id="app-container">
        <!-- Schritt 1: Server-Verbindung herstellen -->
        <div id="connect-section" class="container section visible">
            <h1>Server-Verbindung herstellen</h1>
            <p class="info">Server-Status: <span id="connect-socket-status-display" class="dimmed">Prüfe...</span></p>
            <div>
                <label for="server-address">Server-Adresse (z.B. 192.168.1.5 oder mein-server.de:12345):</label>
                <input type="text" id="server-address" name="server_address" placeholder="host:port (Standard-Port: 65432)" required>
                <button id="connect-to-server-button">Mit Server verbinden</button>
            </div>
        </div>

        <!-- Schritt 2: Lobby-Registrierung -->
        <div id="lobby-registration-section" class="container section">
            <h2>Lobby beitreten</h2>
            <p>Du bist mit dem Server verbunden. Gib deinen Namen und deine gewünschte Rolle ein, um der Lobby beizutreten.</p>
            <div>
                <label for="lobby-nickname">Nickname:</label>
                <input type="text" id="lobby-nickname" name="nickname" required>
                <label for="lobby-role-choice">Gewünschte Rolle:</label>
                <select id="lobby-role-choice" name="role">
                    <option value="hider">Hider</option>
                    <option value="seeker">Seeker</option>
                </select>
                <button id="register-in-lobby-button">Lobby beitreten</button>
            </div>
        </div>

        <!-- Schritt 3: Lobby-Ansicht -->
        <div id="lobby-view-section" class="section">
            <div class="container">
                <h2>Spiel-Lobby</h2>
                <p class="info">Server Socket: <span id="lobby-socket-connection-status" class="dimmed">Prüfe...</span></p>
                <ul id="lobby-player-list" class="player-list"></ul>
                 <form id="ready-form">
                     <button type="submit" id="ready-button">Bereit zum Spielstart!</button>
                 </form>
                 <button id="change-details-button" type="button" class="action-btn warning-btn" style="margin-top: 5px;">Name/Rolle ändern</button>
            </div>
            <div class="container">
                <h3>Deine Informationen</h3>
                <p class="info"><strong>Name:</strong> <span id="lobby-player-name">N/A</span> (ID: <span id="lobby-player-id" class="dimmed">N/A</span>)</p>
                <p class="info"><strong>Zugewiesene Rolle:</strong> <span id="lobby-player-role">N/A</span></p>
                <p class="info dimmed" style="font-size:0.8em">Standort-Genauigkeit: <span id="lobby-player-accuracy">N/A</span> m</p>
            </div>
        </div>

        <!-- Schritt 4: Spiel-Ansicht -->
        <div id="ingame-view-section" class="section">
            <!-- Wichtigste Info: Zeit & Status -->
            <div class="container">
                 <h1>Hide and Seek</h1>
                 <p class="info">Spielphase: <span id="game-status-display" class="dimmed">Lade...</span></p>
                 <div id="hider-wait-countdown-container" class="visibility-container">
                    <p class="countdown">Vorbereitungszeit: <span id="hider-wait-time-left">0</span> Sek</p>
                </div>
                <div id="game-time-left-container" class="visibility-container">
                    <p class="centered-text" style="font-size: 1.2em;"><strong>Verbleibende Spielzeit</strong></p>
                    <p id="game-time-left" class="countdown" style="font-size:2em; color:#007bff; padding: 15px 0;">0</p>
                </div>
            </div>

            <!-- Rollenspezifische Werkzeuge -->
            <div id="hider-section" class="container section">
                <h2>Hider Werkzeuge</h2>
                <div id="hider-task-info" class="visibility-container">
                    <h3>Aktuelle Aufgabe</h3>
                    <p class="info"><strong>Beschreibung:</strong> <span id="task-description"></span></p>
                    <p class="info"><strong>Punkte:</strong> <span id="task-points"></span></p>
                    <p class="info"><strong>Verbleibende Zeit:</strong> <span id="task-time-left" class="countdown" style="font-size:1em; color:#dc3545; padding: 5px;"></span> Sek</p>
                    <form id="complete-task-form" style="margin-bottom: 5px;"><button type="submit" class="action-btn">Aufgabe als erledigt markieren!</button></form>
                    <button id="skip-task-button" class="action-btn warning-btn" style="display:none;">
                        Aufgabe überspringen (<span id="skips-left-in-button">0</span> übrig)
                    </button>
                </div>
                <p id="hider-no-task-message" class="dimmed visibility-container">Warte auf eine neue Aufgabe vom Server...</p>
                 <p id="hider-warning-text" class="error visibility-container" style="font-weight:bold; text-align:center; background-color: #fff3cd; color: #856404; padding: 10px; border-radius: 5px;">
                    ACHTUNG HIDER! Dein Standort wird bald an die Seeker gesendet.
                </p>
            </div>
            <div id="seeker-section" class="container section">
                <h2>Seeker Werkzeuge</h2>
                <div id="seeker-hider-locations-container">
                    <h3>Sichtbare Hider</h3>
                    <ul id="seeker-hider-list" class="player-list"></ul>
                    <p id="seeker-no-hiders-message" class="dimmed centered-text visibility-container">Momentan keine Hider sichtbar.</p>
                </div>
            </div>

            <!-- Leaderboards & Spielerlisten -->
            <div class="container">
                <h3>Leaderboard & Spieler</h3>
                <div id="hider-leaderboard-container" class="visibility-container">
                    <h4>Hider Leaderboard</h4>
                    <table id="hider-leaderboard" class="leaderboard">
                        <thead><tr><th>Name</th><th>Punkte</th><th>Status</th></tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
                <div id="all-players-container">
                    <h4>Alle Spieler im Spiel</h4>
                    <ul id="all-players-list" class="player-list"></ul>
                </div>
            </div>

            <!-- Eigene Spieler-Informationen im Spiel -->
            <div class="container">
                <h3>Deine Informationen</h3>
                <p class="info"><strong>Server Socket: <span id="ingame-socket-connection-status" class="dimmed">Prüfe...</span></strong></p>
                <p class="info"><strong>Name:</strong> <span id="ingame-player-name">N/A</span></p>
                <p class="info"><strong>Aktuelle Rolle:</strong> <span id="ingame-player-role">N/A</span></p>
                <p class="info"><strong>Dein Status:</strong> <span id="ingame-player-status">N/A</span></p>
                <p class="info dimmed" style="font-size:0.8em">Standort-Genauigkeit: <span id="ingame-player-accuracy">N/A</span> m</p>
            </div>

            <!-- Spielende-Optionen -->
            <div class="container">
                <div id="early-end-vote-container" class="visibility-container">
                     <button id="request-early-end-button" class="warning-btn">Runde vorzeitig beenden</button>
                     <p id="early-end-vote-info" class="dimmed centered-text" style="margin-top: 10px;">0/0 Spieler wollen Runde beenden.</p>
                </div>
            </div>
        </div>

        <!-- Abschnitt: Spielende-Anzeige -->
        <div id="game-over-section" class="container section">
            <h2>Spiel Vorbei!</h2>
            <p id="game-over-message" style="font-size: 1.2em; font-weight: bold; text-align: center;"></p>
            <div id="game-over-leaderboard-container" class="visibility-container">
                <h3>Finale Hider Rangliste</h3>
                <table id="game-over-leaderboard" class="leaderboard">
                    <thead><tr><th>Name</th><th>Punkte</th><th>Status</th></tr></thead>
                    <tbody></tbody>
                </table>
            </div>
             <p class="dimmed centered-text" style="margin-top:15px;">Du wirst in Kürze zur Lobby zurückgebracht...</p>
             <!-- Der "sofort zurück" Button wurde wie gewünscht entfernt -->
        </div>
        
        <!-- Unauffälliger Server-Reset am Ende der Seite -->
        <div id="server-management-container">
            <h4 style="margin-bottom: 10px; text-align: center;">Notfall-Verwaltung</h4>
            <button id="force-server-reset-button" class="danger-btn">Server für alle zurücksetzen (Notfall)</button>
            <p>Achtung: Nutzt die oben im Verbindungs-Abschnitt eingegebene Adresse. Setzt das Spiel für alle Spieler auf eine neue Lobby zurück.</p>
        </div>
    </div>

    <script>
        // Service Worker
        if ('serviceWorker' in navigator) {
            window.addEventListener('load', () => {
                navigator.serviceWorker.register('sw.js', { scope: '/' })
                    .then(registration => console.log('ServiceWorker Registrierung erfolgreich, Scope:', registration.scope))
                    .catch(error => console.error('ServiceWorker Registrierung fehlgeschlagen:', error));
            });
        }

        let currentPlayerData = {};
        const GAME_STATE_LOBBY = "lobby";
        const GAME_STATE_HIDER_WAIT = "hider_wait";
        const GAME_STATE_RUNNING = "running";
        const GAME_STATE_HIDER_WINS = "hider_wins";
        const GAME_STATE_SEEKER_WINS = "seeker_wins";

        const LOCATION_UPDATE_INTERVAL_MS = 10000;
        let locationWatchId = null;
        let lastLocationSentTime = 0;
        const SERVER_ADDRESS_KEY = 'hideAndSeekServerAddress';
        let statusUpdateInterval;

        // --- DOM Hilfsfunktionen ---
        function $(selector) { return document.querySelector(selector); }
        function setText(id, textContent) { const el = $(`#${id}`); if (el) el.textContent = textContent || ''; }
        function setHtml(id, htmlContent) { const el = $(`#${id}`); if (el) el.innerHTML = htmlContent || ''; }
        function toggleVisibility(id, showFlag) {
            const el = $(`#${id}`);
            if (el) {
                if (showFlag) el.classList.add('visible');
                else el.classList.remove('visible');
            }
        }
        
        function toggleNotification(id, message) {
            const el = $(`#${id}`);
            if (el) {
                if (message) {
                    el.textContent = message;
                    el.classList.add('visible');
                } else {
                    el.classList.remove('visible');
                }
            }
        }

        function saveServerAddress(address) { try { localStorage.setItem(SERVER_ADDRESS_KEY, address); } catch (e) { console.warn("localStorage nicht verfügbar:", e); } }
        function loadServerAddress() { try { return localStorage.getItem(SERVER_ADDRESS_KEY); } catch (e) { console.warn("localStorage nicht verfügbar:", e); return null; } }

        function initializeServerInput() {
            const loadedAddress = loadServerAddress();
            const serverAddressInput = $('#server-address');
            if (serverAddressInput && loadedAddress) {
                serverAddressInput.value = loadedAddress;
            }
        }

        function resetAllSections() {
            document.querySelectorAll('#app-container > .section').forEach(section => {
                 section.classList.remove('visible');
            });
        }

        function updateUI(data) {
            currentPlayerData = JSON.parse(JSON.stringify(data)); // Deep copy
            resetAllSections();

            const userHasInitiatedConnection = data.user_has_initiated_connection === true;
            const isSocketConnected = data.is_socket_connected_to_server === true;
            const hasPlayerId = !!data.player_id;
            const serverGameStatus = data.game_state?.status;
            const serverGameStatusDisplay = data.game_state?.status_display || "Lade...";
            const isGameOver = serverGameStatus === GAME_STATE_HIDER_WINS || serverGameStatus === GAME_STATE_SEEKER_WINS;

            // --- Globale Elemente (Benachrichtigungen etc.) ---
            if (data.is_processing_offline_queue) {
                 toggleNotification('game-message', 'Synchronisiere Offline-Aktionen mit dem Server...');
            } else if (data.game_message) {
                toggleNotification('game-message', data.game_message);
                setTimeout(() => {
                    if ($('#game-message').textContent === data.game_message) {
                        toggleNotification('game-message', null);
                    }
                }, 5000);
            } else {
                toggleNotification('game-message', null);
            }
            toggleNotification('error-message', data.error_message || data.join_error);
            if($('#force-server-reset-button')) $('#force-server-reset-button').disabled = false;


            // =================================================================
            // --- HIER IST DIE NEUE, KORRIGIERTE HAUPT-ANSICHTEN-LOGIK ---
            // =================================================================

            // Prio 1: Verbindung herstellen oder wiederherstellen.
            if (!userHasInitiatedConnection || !isSocketConnected) {
                $('.section#connect-section').classList.add('visible');
                let statusText = "Bereit zum Verbinden";
                let statusClass = "dimmed";
                if (userHasInitiatedConnection && !isSocketConnected) {
                    statusText = serverGameStatusDisplay;
                    statusClass = (data.error_message || data.join_error) ? 'status-disconnected' : 'status-connecting';
                }
                setText('connect-socket-status-display', statusText);
                $('#connect-socket-status-display').className = statusClass;

            // Prio 2: Wenn verbunden, aber keine Spieler-ID -> Registrieren!
            // Dies ist der entscheidende Fix, der den "Stuck on Game Over"-Bug löst.
            } else if (!hasPlayerId) {
                $('.section#lobby-registration-section').classList.add('visible');
                $('#register-in-lobby-button').disabled = false;
                const nicknameInput = $('#lobby-nickname');
                if (nicknameInput && document.activeElement !== nicknameInput) {
                    nicknameInput.value = data.session_nickname || data.prefill_nickname || '';
                }
                const roleChoiceInput = $('#lobby-role-choice');
                if (roleChoiceInput && document.activeElement !== roleChoiceInput) {
                    roleChoiceInput.value = data.session_role_choice || 'hider';
                }
            
            // Prio 3: Wenn verbunden und Spieler-ID vorhanden -> Spielzustand anzeigen.
            } else { 
                const playerAccuracy = data.location?.length > 2 && data.location[2] !== null ? parseFloat(data.location[2]).toFixed(1) : 'N/A';
                
                if (isGameOver) {
                    $('.section#game-over-section').classList.add('visible');
                    setText('game-over-message', data.game_state?.game_over_message || "Das Spiel ist vorbei.");
                    updateHiderLeaderboard(data.hider_leaderboard, String(data.player_id), 'game-over-leaderboard');
                
                } else if (serverGameStatus === GAME_STATE_LOBBY) {
                    $('.section#lobby-view-section').classList.add('visible');
                    const lobbySocketStatusEl = $('#lobby-socket-connection-status');
                    setText(lobbySocketStatusEl.id, 'Verbunden');
                    lobbySocketStatusEl.className = 'status-connected';
                    updateLobbyPlayerList(data.lobby_players, String(data.player_id));
                    
                    const readyButton = $('#ready-button');
                    readyButton.textContent = data.player_is_ready ? 'Status: Bereit (Klick zum Ändern)' : 'Klicken: Ich bin bereit!';
                    readyButton.className = data.player_is_ready ? 'unready' : 'ready';
                    readyButton.disabled = false;
                    
                    setText('lobby-player-name', data.player_name);
                    setText('lobby-player-id', data.player_id);
                    setText('lobby-player-role', data.role);
                    setText('lobby-player-accuracy', playerAccuracy);

                } else { // HIDER_WAIT oder RUNNING
                    $('.section#ingame-view-section').classList.add('visible');
                    const ingameSocketStatusEl = $('#ingame-socket-connection-status');
                    setText(ingameSocketStatusEl.id, 'Verbunden');
                    ingameSocketStatusEl.className = 'status-connected';
                    
                    setText('ingame-player-name', data.player_name);
                    setText('ingame-player-role', data.role);
                    const statusClass = `status-${data.player_status || 'unknown'}`;
                    setHtml('ingame-player-status', `<span class="${statusClass}">${data.player_status}</span>`);

                    setText('game-status-display', serverGameStatusDisplay);
                    setText('ingame-player-accuracy', playerAccuracy);

                    toggleVisibility('hider-wait-countdown-container', serverGameStatus === GAME_STATE_HIDER_WAIT);
                    setText('hider-wait-time-left', data.game_state?.hider_wait_time_left || '0');
                    
                    toggleVisibility('game-time-left-container', serverGameStatus === GAME_STATE_RUNNING);
                    const timeLeft = data.game_state?.game_time_left || 0;
                    setText('game-time-left', `${Math.floor(timeLeft / 60)} Min ${timeLeft % 60} Sek`);
                    
                    toggleVisibility('hider-section', data.role === 'hider');
                    toggleVisibility('seeker-section', data.role === 'seeker');

                    if (data.role === 'hider') {
                        toggleVisibility('hider-warning-text', data.hider_location_update_imminent && data.player_status === 'active');
                        updateHiderTask(data.current_task, data.task_skips_available);
                        updateHiderLeaderboard(data.hider_leaderboard, String(data.player_id), 'hider-leaderboard');
                    }
                    if (data.role === 'seeker') {
                        updateSeekerHiderList(data.hider_locations, isSocketConnected);
                    }
                    
                    updateAllPlayersList(data.all_players_status, String(data.player_id));
                    
                    const canVote = (serverGameStatus === GAME_STATE_RUNNING || serverGameStatus === GAME_STATE_HIDER_WAIT) && data.player_status === 'active';
                    toggleVisibility('early-end-vote-container', canVote);
                    if(canVote) {
                        const earlyEndBtn = $('#request-early-end-button');
                        earlyEndBtn.disabled = data.player_has_requested_early_end;
                        earlyEndBtn.textContent = data.player_has_requested_early_end ? 'Abstimmung gesendet' : 'Runde vorzeitig beenden';
                        setText('early-end-vote-info', `${data.early_end_requests_count || 0} / ${data.total_active_players_for_early_end || 0} Spieler wollen Runde beenden.`);
                    }
                }
            }

            // Standort-Updates nur starten, wenn wir ein eingeloggter Spieler im Spiel sind
            if (hasPlayerId && !isGameOver) {
                startLocationUpdates();
            } else {
                stopLocationUpdates();
            }
        }

        function updateLobbyPlayerList(lobbyPlayers, currentPlayerIdStr) {
            const ul = $('#lobby-player-list'); setHtml(ul.id, '');
            if (lobbyPlayers && Object.keys(lobbyPlayers).length > 0) {
                Object.entries(lobbyPlayers).forEach(([pid, p_data]) => {
                    const li = document.createElement('li');
                    let roleDisplay = p_data.role === 'hider' ? 'Hider' : (p_data.role === 'seeker' ? 'Seeker' : 'Unbekannt');
                    let readyDisplay = p_data.is_ready ? '<span class="status-active">Bereit</span>' : '<span class="dimmed">Wartet...</span>';
                    li.innerHTML = `${p_data.name} (Rolle: ${roleDisplay}) - Status: ${readyDisplay}`;
                    if (pid === currentPlayerIdStr) li.classList.add('highlight');
                    ul.appendChild(li);
                });
            } else { ul.innerHTML = '<li class="dimmed">Warte auf weitere Spieler...</li>'; }
        }

        function updateAllPlayersList(allPlayers, currentPlayerIdStr) {
            const el = $('#all-players-list'); setHtml(el.id, '');
            if (allPlayers && Object.keys(allPlayers).length > 0) {
                Object.entries(allPlayers).forEach(([pid, p]) => {
                    const li = document.createElement('li');
                    const statusClass = `status-${p.status || 'unknown'}`;
                    const statusText = p.status || 'Unbekannt';
                    const statusDisplay = `<span class="${statusClass}">${statusText}</span>`;
                    li.innerHTML = `${p.name} (Rolle: ${p.role || 'N/A'}) - ${statusDisplay}`;
                    if (pid === currentPlayerIdStr) li.classList.add('highlight');
                    el.appendChild(li);
                });
            } else { el.innerHTML = '<li class="dimmed">Keine Spielerinformationen.</li>'; }
        }

        function updateHiderTask(task, taskSkipsAvailable) {
            const isActiveHider = currentPlayerData?.role === 'hider' && currentPlayerData?.player_status === 'active';
            const skipTaskButton = $('#skip-task-button');
            const completeTaskButton = $('#complete-task-form button');

            if (task && isActiveHider) {
                toggleVisibility('hider-task-info', true);
                toggleVisibility('hider-no-task-message', false);
                setText('task-description', task.description);
                setText('task-points', task.points);
                setText('task-time-left', task.time_left_seconds);
                if (completeTaskButton) completeTaskButton.disabled = false;
                if (skipTaskButton) {
                    const numSkips = taskSkipsAvailable || 0;
                    toggleVisibility(skipTaskButton.id, true);
                    skipTaskButton.disabled = numSkips <= 0;
                    $('#skips-left-in-button').textContent = numSkips;
                }
            } else {
                toggleVisibility('hider-task-info', false);
                if (completeTaskButton) completeTaskButton.disabled = true;
                if (skipTaskButton) toggleVisibility(skipTaskButton.id, false);
                toggleVisibility('hider-no-task-message', isActiveHider);
            }
        }

        function updateHiderLeaderboard(leaderboardData, currentPlayerIdStr, tableId = 'hider-leaderboard') {
            const containerId = tableId === 'game-over-leaderboard' ? 'game-over-leaderboard-container' : 'hider-leaderboard-container';
            const tbody = $(`#${tableId} tbody`);
            if (!tbody) return;
            tbody.innerHTML = '';

            const shouldShow = leaderboardData && leaderboardData.length > 0;
            toggleVisibility(containerId, shouldShow);

            if (shouldShow) {
                leaderboardData.forEach(entry => {
                    const row = tbody.insertRow();
                    row.insertCell().textContent = entry.name;
                    row.insertCell().textContent = entry.points;
                    const statusClass = `status-${entry.status || 'unknown'}`;
                    const statusText = entry.status || 'Unbekannt';
                    const statusDisplay = `<span class="${statusClass}">${statusText}</span>`;
                    row.insertCell().innerHTML = statusDisplay;
                    if (String(entry.id) === currentPlayerIdStr) row.classList.add('highlight');
                });
            }
        }

        function updateSeekerHiderList(hiderLocations, isSocketConnected) {
            const ul = $('#seeker-hider-list');
            ul.innerHTML = '';
            const isActiveSeeker = currentPlayerData?.role === 'seeker' && currentPlayerData?.player_status === 'active';
            const hasHiders = isActiveSeeker && hiderLocations && Object.keys(hiderLocations).length > 0;
            toggleVisibility('seeker-no-hiders-message', !hasHiders && isActiveSeeker);
            if (hasHiders) {
                Object.entries(hiderLocations).forEach(([hiderId, hider]) => {
                    const li = document.createElement('li');
                    li.innerHTML = `<strong>${hider.name}</strong> (Gesehen: ${hider.timestamp || 'N/A'})
                        <a href="https://www.google.com/maps?q=${hider.lat},${hider.lon}" target="_blank" style="margin-left: 5px;">Karte</a>
                        <button class="catch-hider-btn action-btn" data-hider-id="${hiderId}" ${!isSocketConnected ? 'disabled' : ''}>Fangen!</button>`;
                    ul.appendChild(li);
                });
                document.querySelectorAll('.catch-hider-btn').forEach(button => {
                    button.onclick = async function() {
                        this.disabled = true;
                        await sendClientAction('/catch_hider', { hider_id_to_catch: this.dataset.hiderId }, this);
                    };
                });
            }
        }

        async function sendClientAction(endpoint, bodyPayload = null, triggeringButton = null) {
             if (triggeringButton) triggeringButton.disabled = true;
            try {
                const options = { method: 'POST', headers: {'Content-Type': 'application/json'}};
                if (bodyPayload) options.body = JSON.stringify(bodyPayload);
                const response = await fetch(endpoint, options);
                const responseData = await response.json();
                updateUI(responseData);
            } catch (error) {
                console.error(`Netzwerkfehler an Client-Backend (${endpoint}):`, error);
                const errorData = JSON.parse(JSON.stringify(currentPlayerData || {}));
                errorData.error_message = `Netzwerkfehler: Aktion fehlgeschlagen. Der lokale Client-Server antwortet nicht.`;
                if (!errorData.game_state) errorData.game_state = {};
                errorData.game_state.status_display = "Lokaler Client nicht erreichbar";
                errorData.is_socket_connected_to_server = false;
                updateUI(errorData);
            } finally {
                if (triggeringButton && !['/complete_task', '/set_ready', '/return_to_registration'].includes(endpoint)) {
                    triggeringButton.disabled = false;
                }
            }
        }

        function handleLocationSuccess(position) {
            const { latitude: lat, longitude: lon, accuracy } = position.coords;
            setText('lobby-player-accuracy', accuracy.toFixed(1));
            setText('ingame-player-accuracy', accuracy.toFixed(1));
            toggleNotification('location-error-message', null);
            const now = Date.now();
            if (currentPlayerData?.player_id && (now - lastLocationSentTime > LOCATION_UPDATE_INTERVAL_MS / 2 || lastLocationSentTime === 0)) {
                sendLocationToClientBackend(lat, lon, accuracy);
                lastLocationSentTime = now;
            }
        }

        function handleLocationError(error) {
            let message = "Unbekannter Standortfehler";
            if (error.code === error.PERMISSION_DENIED) message = "Zugriff auf Standort blockiert.";
            else if (error.code === error.POSITION_UNAVAILABLE) message = "Standort nicht verfügbar.";
            else if (error.code === error.TIMEOUT) message = "Timeout bei der Standortabfrage.";
            toggleNotification('location-error-message', message);
        }

        async function sendLocationToClientBackend(lat, lon, accuracy) {
            try {
                const response = await fetch('/update_location_from_browser', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ lat: lat, lon: lon, accuracy: accuracy })
                });
                if (!response.ok) console.error("Fehler beim Senden des Standorts an Client-Backend:", response.status);
            } catch (error) {
                console.error("Netzwerkfehler beim Senden des Standorts an Client-Backend:", error);
            }
        }

        function startLocationUpdates() {
            if (navigator.geolocation && locationWatchId === null) {
                locationWatchId = navigator.geolocation.watchPosition(handleLocationSuccess, handleLocationError, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
            }
        }

        function stopLocationUpdates() {
            if (navigator.geolocation && locationWatchId !== null) {
                navigator.geolocation.clearWatch(locationWatchId);
                locationWatchId = null;
            }
        }
        
        async function fetchStatusAndUpdateUI() {
            try {
                const response = await fetch('/status');
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                const data = await response.json();
                updateUI(data);
            } catch (error) {
                console.error("Netzwerkfehler zum lokalen Client-Backend:", error);
                const tempErrorData = JSON.parse(JSON.stringify(currentPlayerData || {}));
                if (!tempErrorData.game_state) tempErrorData.game_state = {};
                tempErrorData.game_state.status_display = "Client-Server (Python) nicht erreichbar.";
                tempErrorData.error_message = "Lokaler Client-Server (Python) antwortet nicht.";
                tempErrorData.is_socket_connected_to_server = false;
                updateUI(tempErrorData);
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            initializeServerInput();
            fetchStatusAndUpdateUI();
            clearInterval(statusUpdateInterval);
            statusUpdateInterval = setInterval(fetchStatusAndUpdateUI, 2500);

            $('#connect-to-server-button')?.addEventListener('click', async (event) => {
                const serverAddress = $('#server-address').value;
                if (!serverAddress) {
                    toggleNotification('error-message', 'Bitte eine Server-Adresse eingeben.');
                    return;
                }
                saveServerAddress(serverAddress);
                await sendClientAction('/connect_to_server', { server_address: serverAddress }, event.target);
            });
            $('#register-in-lobby-button')?.addEventListener('click', async (event) => {
                const nickname = $('#lobby-nickname').value;
                const role = $('#lobby-role-choice').value;
                if (!nickname) { alert("Bitte einen Nicknamen eingeben."); return; }
                await sendClientAction('/register_player_details', { nickname, role }, event.target);
            });
            $('#ready-form').addEventListener('submit', async (event) => {
                event.preventDefault();
                const newReadyStatus = !(currentPlayerData.player_is_ready || false);
                await sendClientAction('/set_ready', { ready_status: newReadyStatus }, event.submitter);
            });
            $('#change-details-button')?.addEventListener('click', async (event) => {
                if (confirm("Möchtest du zur Namens- und Rollenauswahl zurückkehren?")) {
                    await sendClientAction('/return_to_registration', null, event.target);
                }
            });
            $('#complete-task-form button')?.addEventListener('click', async (event) => {
                event.preventDefault();
                await sendClientAction('/complete_task', null, event.target);
            });
            $('#request-early-end-button')?.addEventListener('click', (event) => sendClientAction('/request_early_round_end_action', null, event.target));
            $('#skip-task-button')?.addEventListener('click', (event) => sendClientAction('/skip_task', null, event.target));
            
            $('#force-server-reset-button')?.addEventListener('click', async (event) => {
                let serverAddress = '';
                const connectSection = $('#connect-section');
                const isConnectSectionVisible = connectSection && connectSection.classList.contains('visible');

                if (isConnectSectionVisible) {
                    serverAddress = $('#server-address').value.trim();
                    if (!serverAddress) {
                        toggleNotification('error-message', 'Bitte zuerst eine Server-Adresse für den Reset eingeben.');
                        setTimeout(() => toggleNotification('error-message', null), 4000);
                        return;
                    }
                } else {
                    if (!currentPlayerData || !currentPlayerData.current_server_host || !currentPlayerData.current_server_port) {
                        toggleNotification('error-message', 'Client-Status noch nicht geladen. Bitte kurz warten und erneut versuchen.');
                        setTimeout(() => toggleNotification('error-message', null), 4000);
                        return;
                    }
                    serverAddress = `${currentPlayerData.current_server_host}:${currentPlayerData.current_server_port}`;
                }
                
                if (confirm(`Bist du sicher, dass du den Server unter '${serverAddress}' für ALLE Spieler zurücksetzen möchtest?`)) {
                    await sendClientAction(
                        '/force_server_reset_from_ui',
                        { server_address: serverAddress },
                        event.target
                    );
                }
            });
        });
    </script>
</body>
</html>
```

---

### `server.py` (Der zentrale Spielserver)

Auch diese Datei bleibt unverändert, da das Problem clientseitig war.

```python
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
            "player_id": None, # WICHTIG: player_id auf None setzen, damit Client sich neu registriert
            "error_message": reset_message,
            "join_error": reset_message, # join_error zwingt UI zur Registrierung/Connect-Seite
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
                if e_shutdown.errno not in [socket.EBADF, socket.ENOTCONN]: # Bad file descriptor, Not connected
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
            if p_info.get("confirmed_for_lobby", False): # Nur Spieler, die im aktuellen Lobby-Zyklus sind
                active_lobby_players[p_id] = {
                    "name": p_info.get("name", "Unbekannt"),
                    "role": p_info.get("current_role", "hider"), # Die Rolle, die sie für dieses Spiel haben
                    "is_ready": p_info.get("is_ready", False)
                }
    return active_lobby_players

def get_all_players_public_status():
    all_players = {}
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            # Hier zeigen wir Infos für alle Spieler, die dem Server bekannt sind (auch wenn sie nicht "confirmed_for_lobby" sind)
            # Solange sie eine Verbindung haben oder relevant für das Spiel waren.
            # Der "is_waiting_for_lobby" Status wird clientseitig verwendet, um zu entscheiden, ob diese Infos relevant sind.
            all_players[p_id] = {
                "name": p_info.get("name", "Unbekannt"),
                "role": p_info.get("current_role", "hider"),
                "status": p_info.get("status_ingame", "active") # z.B. active, caught, offline
            }
    return all_players

def get_hider_leaderboard():
    leaderboard = []
    with data_lock:
        for p_id, p_info in game_data.get("players", {}).items():
            if p_info.get("original_role") == "hider": # Zeige alle, die als Hider gestartet sind
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
            return # Kann keine Aufgabe zuweisen

        available_tasks_list = game_data.get("available_tasks")
        if not player.get("task") and available_tasks_list: # Spieler hat keine Aufgabe und es gibt verfügbare
            # Finde Aufgaben, die noch nicht von anderen aktiven Hidern bearbeitet werden
            assigned_tasks_ids = {p_info.get("task", {}).get("id")
                                for p_info in game_data["players"].values()
                                if p_info.get("task") and p_info.get("status_ingame") == "active"}

            possible_tasks = [t for t in available_tasks_list if t.get("id") not in assigned_tasks_ids]

            if possible_tasks:
                task = random.choice(possible_tasks)
                player["task"] = task
                player["task_deadline"] = time.time() + task.get("time_limit_seconds", 180) # Standard 3 Min
                print(f"SERVER TASK: Hider {player.get('name','N/A')} ({player_id}): Neue Aufgabe: {task.get('description','N/A')}")
            else:
                print(f"SERVER TASK: Keine unzugewiesenen Aufgaben mehr verfügbar für Hider {player.get('name','N/A')}")
        elif not available_tasks_list:
            print(f"SERVER TASK: Keine Aufgaben mehr im globalen Pool verfügbar für Hider {player.get('name','N/A')}")
        # else: Spieler hat bereits eine Aufgabe oder ist nicht berechtigt

def count_active_players_for_early_end():
    with data_lock:
        return sum(1 for p_info in game_data.get("players", {}).values()
                   if p_info.get("status_ingame") == "active" and p_info.get("confirmed_for_lobby"))


def _calculate_and_set_next_broadcast_time(current_time):
    with data_lock:
        phase_idx = game_data.get("current_phase_index", -1)

        if phase_idx < 0 or phase_idx >= len(PHASE_DEFINITIONS):
            game_data["next_location_broadcast_time"] = float('inf') # Keine weiteren Broadcasts geplant
            if phase_idx >= len(PHASE_DEFINITIONS) and game_data.get("status") == GAME_STATE_RUNNING:
                 print("SERVER LOGIC: Alle Update-Phasen abgeschlossen. Standort-Updates beendet (Spiel läuft weiter bis Zeitende).")
            return

        phase_def = PHASE_DEFINITIONS[phase_idx]

        # Prüfe, ob die aktuelle Phase beendet ist (entweder durch Dauer oder Anzahl der Updates)
        phase_ended_by_duration = False
        if not phase_def.get("is_initial_reveal"): # Der Initial Reveal hat keine Dauer
            phase_ended_by_duration = (phase_def["duration_seconds"] != float('inf') and
                                   current_time >= game_data.get("current_phase_start_time", 0) + phase_def["duration_seconds"])

        phase_ended_by_updates = ("updates_in_phase" in phase_def and
                                  game_data.get("updates_done_in_current_phase", 0) >= phase_def["updates_in_phase"])

        # Wenn Phase beendet, zur nächsten wechseln
        if (phase_def.get("is_initial_reveal") and game_data.get("updates_done_in_current_phase", 0) > 0) or \
           phase_ended_by_duration or phase_ended_by_updates:
            game_data["current_phase_index"] += 1
            phase_idx = game_data["current_phase_index"] # Aktualisiere lokalen Index

            # Wenn alle Phasen durchlaufen sind, keine weiteren Broadcasts
            if phase_idx >= len(PHASE_DEFINITIONS):
                game_data["next_location_broadcast_time"] = float('inf')
                print("SERVER LOGIC: Alle Update-Phasen abgeschlossen (nach Inkrement). Standort-Updates beendet.")
                return

            # Neue Phase beginnt: Startzeit und Update-Zähler zurücksetzen
            game_data["current_phase_start_time"] = current_time
            game_data["updates_done_in_current_phase"] = 0 # Wichtig: Zähler für neue Phase zurücksetzen
            phase_def = PHASE_DEFINITIONS[phase_idx] # Definition für die neue Phase laden
            print(f"SERVER LOGIC: Starte/Weiter mit Phase {phase_idx}: {phase_def['name']}")


        # Berechne den nächsten Broadcast-Zeitpunkt basierend auf der aktuellen (ggf. neuen) Phase
        if "update_interval_seconds" in phase_def: # Phase mit festem Intervall
            game_data["next_location_broadcast_time"] = current_time + phase_def["update_interval_seconds"]
        elif "updates_in_phase" in phase_def and phase_def["updates_in_phase"] > 0:
            if phase_def["duration_seconds"] > 0: # Updates verteilt über eine Dauer
                interval = phase_def["duration_seconds"] / phase_def["updates_in_phase"]
                game_data["next_location_broadcast_time"] = current_time + interval
            else: # z.B. Initial Reveal, der sofort nach Phasenstart passiert
                 game_data["next_location_broadcast_time"] = current_time # Sofortiger Broadcast
        else: # Keine Updates in dieser Phase definiert (sollte nicht vorkommen, wenn Phase aktiv)
            game_data["next_location_broadcast_time"] = float('inf')

        # Logging für den geplanten Broadcast
        if game_data["next_location_broadcast_time"] != float('inf'):
            delay_seconds = int(game_data['next_location_broadcast_time'] - current_time)
            target_time_str = time.strftime('%H:%M:%S', time.localtime(game_data['next_location_broadcast_time']))
            # Das folgende Log kann sehr gesprächig sein.
            # print(f"SERVER LOGIC: Nächster Hider-Standort-Broadcast geplant für: {target_time_str} (in ca. {delay_seconds}s) in Phase '{phase_def['name']}'.")


def send_data_to_one_client(conn, player_id_for_perspective):
    payload = {}
    player_name_for_log = "N/A_IN_SEND_INIT" # Für Logging, falls Spieler nicht gefunden wird
    try:
        with data_lock: # Sicherer Zugriff auf game_data
            if player_id_for_perspective not in game_data.get("players", {}):
                # Spieler existiert nicht mehr im Spiel (z.B. nach Reset oder Disconnect)
                if conn: # Nur senden, wenn eine Verbindung besteht
                    null_player_payload = {
                        "type": "game_update", "player_id": None, # Signalisiert Client, dass er nicht mehr im Spiel ist
                        "message": "Du wurdest aus dem Spiel entfernt oder der Server wurde zurückgesetzt.",
                        "join_error": "Du bist nicht mehr Teil des aktuellen Spiels. Bitte neu beitreten.",
                        "game_state": { "status": "disconnected", "status_display": "Sitzung ungültig." }
                    }
                    _safe_send_json(conn, null_player_payload, player_id_for_perspective, "N/A (Player not in game_data)")
                return False # Kein gültiger Spieler

            player_info = game_data["players"].get(player_id_for_perspective)
            if not player_info: return False # Sollte nicht passieren, wenn ID in players ist, aber zur Sicherheit

            player_name_for_log = player_info.get("name", f"Unbekannt_{player_id_for_perspective}")
            p_role = player_info.get("current_role", "hider")
            is_waiting_for_lobby = player_info.get("is_waiting_for_lobby", False)

            current_game_status = game_data.get("status", GAME_STATE_LOBBY)
            current_status_display = game_data.get("status_display", GAME_STATE_DISPLAY_NAMES.get(current_game_status, "Unbekannter Status"))

            # Erstelle den game_state Teil der Payload
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

            # Haupt-Payload zusammenstellen
            payload = {
                "type": "game_update", "player_id": player_id_for_perspective, # Wichtig für den Client zur Identifikation
                "player_name": player_name_for_log, "role": p_role, "location": player_info.get("location"),
                "confirmed_for_lobby": player_info.get("confirmed_for_lobby", False),
                "player_is_ready": player_info.get("is_ready", False),
                "player_status": player_info.get("status_ingame", "active"),
                "is_waiting_for_lobby": is_waiting_for_lobby, # Informiert den Client, ob er auf die nächste Runde wartet
                "game_state": payload_game_state,
                "lobby_players": get_active_lobby_players_data() if current_game_status == GAME_STATE_LOBBY and not is_waiting_for_lobby else {},
                "all_players_status": get_all_players_public_status(), # Immer alle Spieler senden für die Gesamtübersicht
                "hider_leaderboard": get_hider_leaderboard() if p_role == "hider" or current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS] else None,
                "hider_location_update_imminent": player_info.get("has_pending_location_warning", False) if p_role == "hider" and not is_waiting_for_lobby else False,
                "early_end_requests_count": len(game_data.get("early_end_requests", set())) if not is_waiting_for_lobby else 0,
                "total_active_players_for_early_end": game_data.get("total_active_players_for_early_end", 0) if not is_waiting_for_lobby else 0,
                "player_has_requested_early_end": player_id_for_perspective in game_data.get("early_end_requests", set()) if not is_waiting_for_lobby else False
            }

            # Hider-spezifische Daten
            if p_role == "hider" and not is_waiting_for_lobby:
                payload["task_skips_available"] = player_info.get("task_skips_available", 0)
                if player_info.get("status_ingame") == "active" and player_info.get("task"):
                    p_task_info = player_info["task"]
                    payload["current_task"] = {
                        "id": p_task_info.get("id", "N/A"), "description": p_task_info.get("description", "Keine Beschreibung"),
                        "points": p_task_info.get("points", 0),
                        "time_left_seconds": max(0, int(player_info.get("task_deadline", 0) - time.time())) if player_info.get("task_deadline") else 0
                    }
                else: # Kein aktiver Task
                    payload["current_task"] = None

                # Pre-caching von Aufgaben für Hider
                payload["pre_cached_tasks"] = []
                if player_info.get("status_ingame") == "active": # Nur für aktive Hider
                    available_tasks_list_copy = list(game_data.get("available_tasks", [])) # Kopie für Modifikationen
                    # IDs aller aktuell zugewiesenen Aufgaben (auch die des aktuellen Spielers)
                    assigned_task_ids = {p.get("task", {}).get("id") for p in game_data.get("players", {}).values() if p.get("task")}

                    # Filtere Aufgaben, die noch nicht zugewiesen sind
                    unassigned_tasks = [t for t in available_tasks_list_copy if t.get("id") not in assigned_task_ids]
                    random.shuffle(unassigned_tasks) # Mische für eine zufällige Auswahl

                    # Füge bis zu 2 Aufgaben zum Pre-Cache hinzu
                    for i in range(min(2, len(unassigned_tasks))): # Nimmt maximal 2 oder weniger, falls nicht genug da sind
                        task_to_cache = unassigned_tasks[i]
                        payload["pre_cached_tasks"].append({
                            "id": task_to_cache.get("id"), "description": task_to_cache.get("description"),
                            "points": task_to_cache.get("points")
                        })


            # Seeker-spezifische Daten
            if p_role == "seeker" and not is_waiting_for_lobby:
                visible_hiders = {}
                current_players_copy = dict(game_data.get("players", {})) # Kopie für sichere Iteration
                for h_id, h_info in current_players_copy.items():
                    if h_info.get("current_role") == "hider" and \
                       h_info.get("status_ingame") == "active" and \
                       h_info.get("location"): # Nur wenn Standort bekannt
                        visible_hiders[h_id] = {
                            "name": h_info.get("name", "Unbekannter Hider"),
                            "lat": h_info["location"][0], "lon": h_info["location"][1],
                            "timestamp": time.strftime("%H:%M:%S", time.localtime(h_info.get("last_location_timestamp", time.time())))
                        }
                payload["hider_locations"] = visible_hiders
            else: # Für Hider oder wenn der Spieler wartet, keine Hider-Standorte senden
                payload["hider_locations"] = {} # Leeres Objekt, um clientseitige Fehler zu vermeiden

        # Sende die zusammengestellte Payload an den Client
        if conn and payload: # Sicherstellen, dass Verbindung und Payload existieren
             return _safe_send_json(conn, payload, player_id_for_perspective, player_name_for_log)

    except Exception as e: # Fange unerwartete Fehler bei der Payload-Erstellung ab
        print(f"SERVER SEND (ERROR - UNEXPECTED in prep): P:{player_id_for_perspective} ({player_name_for_log}): Unerwarteter Fehler: {e}")
        traceback.print_exc()
    return False # Fehler beim Senden oder Vorbereiten


def broadcast_full_game_state_to_all(exclude_pid=None):
    """Sendet den aktuellen, personalisierten Spielzustand an alle verbundenen Clients."""
    players_to_update_with_conn = []
    with data_lock: # Hole Liste der Spieler und ihrer Verbindungen unter Lock
        for pid, pinfo in game_data.get("players", {}).items():
            if pid != exclude_pid and pinfo.get("client_conn"): # Nur an verbundene Clients, exkl. exclude_pid
                players_to_update_with_conn.append((pid, pinfo["client_conn"]))

    # Sende Daten außerhalb des Locks, um Blockaden zu minimieren
    for p_id_to_update, conn_to_use in players_to_update_with_conn:
        send_data_to_one_client(conn_to_use, p_id_to_update) # Diese Funktion handelt den Lock intern


def broadcast_server_text_notification(message_text, target_player_ids=None, role_filter=None):
    """ Sendet eine einfache Text-Benachrichtigung an bestimmte oder alle Spieler. """
    message_data = {"type": "server_text_notification", "message": message_text}
    players_to_notify = []
    with data_lock:
        player_pool = target_player_ids if target_player_ids is not None else game_data.get("players", {}).keys()
        for p_id in player_pool:
            p_info = game_data.get("players", {}).get(p_id)
            if not p_info or not p_info.get("client_conn"): continue # Spieler nicht vorhanden oder nicht verbunden
            if role_filter and p_info.get("current_role") != role_filter: continue # Rollenfilter
            players_to_notify.append((p_id, p_info["client_conn"], p_info.get("name", "N/A")))

    for p_id, conn, name in players_to_notify:
        _safe_send_json(conn, message_data, p_id, name)


def check_game_conditions_and_end():
    """Prüft, ob das Spiel beendet werden soll (Zeit abgelaufen, alle Hider gefangen etc.)."""
    with data_lock:
        current_game_status = game_data.get("status")
        if current_game_status != GAME_STATE_RUNNING: return False # Nur im laufenden Spiel prüfen

        current_time = time.time()
        original_hiders_exist = False # Gab es überhaupt Hider zu Beginn?
        active_hiders_in_game = 0 # Wie viele Hider sind noch aktiv?

        # Iteriere über eine Kopie der Spielerliste, falls Spieler entfernt werden
        for p_id, p_info in list(game_data.get("players", {}).items()): # list(...) erstellt eine Kopie
            if not p_info: continue # Spieler wurde möglicherweise gerade entfernt

            if p_info.get("original_role") == "hider":
                original_hiders_exist = True
                if p_info.get("status_ingame") == "active": # Zähle aktive Hider
                    active_hiders_in_game += 1

                # Hider-Task-Deadline-Prüfung
                if p_info.get("current_role") == "hider" and p_info.get("status_ingame") == "active":
                    if p_info.get("task") and p_info.get("task_deadline") and current_time > p_info["task_deadline"]:
                        # Task-Zeit abgelaufen
                        task_description_for_log = p_info.get('task',{}).get('description','N/A')
                        player_name_for_log = p_info.get('name','N/A')
                        if p_id in game_data.get("players", {}): # Sicherstellen, dass Spieler noch da ist
                            game_data["players"][p_id]["task"] = None # Aufgabe entfernen
                            game_data["players"][p_id]["task_deadline"] = None
                            broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' NICHT rechtzeitig geschafft! Aufgabe entfernt.")
                            assign_task_to_hider(p_id) # Neue Aufgabe zuweisen

        # Gewinnbedingung: Alle Hider gefangen/ausgeschieden
        if original_hiders_exist and active_hiders_in_game == 0:
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Alle Hider ausgeschieden/gefangen. Seeker gewinnen!"
            game_data["early_end_requests"].clear() # Abstimmung zurücksetzen
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (alle Hider gefangen).")
            return True # Spiel ist beendet

        # Gewinnbedingung: Keine Hider zu Spielbeginn (oder alle haben vor Start verlassen)
        if not original_hiders_exist and len(game_data.get("players", {})) >= 1 and \
           any(p.get("confirmed_for_lobby") for p in game_data.get("players", {}).values()):
            game_data["status"] = GAME_STATE_SEEKER_WINS
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
            game_data["game_over_message"] = "Keine Hider im Spiel gestartet. Seeker gewinnen!"
            game_data["early_end_requests"].clear()
            print("SERVER LOGIC: Spiel beendet - Seeker gewinnen (keine Hider gestartet).")
            return True

        # Gewinnbedingung: Spielzeit abgelaufen
        if game_data.get("game_end_time") and current_time > game_data["game_end_time"]:
            # Zähle finale aktive Hider
            final_active_hiders_at_timeout = sum(1 for p_info_final in game_data.get("players", {}).values()
                                                 if p_info_final.get("current_role") == "hider" and p_info_final.get("status_ingame") == "active")
            if final_active_hiders_at_timeout > 0:
                game_data["status"] = GAME_STATE_HIDER_WINS
                game_data["game_over_message"] = "Zeit abgelaufen. Hider gewinnen!"
            else:
                game_data["status"] = GAME_STATE_SEEKER_WINS
                game_data["game_over_message"] = "Zeit abgelaufen. Keine Hider übrig. Seeker gewinnen!"
            game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[game_data["status"]]
            game_data["early_end_requests"].clear()
            print(f"SERVER LOGIC: Spiel beendet - Zeit abgelaufen. Status: {game_data['status_display']}.")
            return True

        return False # Spiel läuft weiter

def handle_client_connection(conn, addr):
    player_id = None
    player_name_for_log = "Unbekannt_Init" # Für Logs, bevor Spieler-ID bekannt ist
    action_for_log = "N/A" # Für Logging bei Fehlern
    # NEUES LOG
    print(f"SERVER HANDLER: Thread für {addr} gestartet. Socket: {conn}")
    try:
        buffer = ""
        while True: # Schleife für Nachrichtenempfang
            try:
                # Das folgende Log kann sehr gesprächig sein. Für Debugging von Verbindungsabbrüchen aktivieren.
                # print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Wartet auf Daten (recv)...")
                data_chunk = conn.recv(4096) # Empfange bis zu 4KB Daten
                # NEUES LOG - Dieses ist sehr wichtig!
                print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Empfangen {len(data_chunk)} bytes.")
                if not data_chunk: # Client hat Verbindung geschlossen
                    print(f"SERVER COMM: Client {addr} (P:{player_id}, Name:{player_name_for_log}) hat Verbindung geschlossen (recv returned empty).")
                    break # Beendet die while True Schleife -> führt zu finally Block
                buffer += data_chunk.decode('utf-8') # Dekodiere und füge zum Puffer hinzu

                # Verarbeite alle vollständigen Nachrichten im Puffer (durch '\n' getrennt)
                while '\n' in buffer:
                    message_str, buffer = buffer.split('\n', 1) # Trenne erste Nachricht ab
                    if not message_str.strip(): continue # Ignoriere leere Zeilen
                    message = json.loads(message_str) # Parse JSON
                    action = message.get("action"); action_for_log = action # Für Logging
                    # NEUES LOG
                    print(f"SERVER HANDLER ({addr}, P:{player_id}, Name:{player_name_for_log}): Aktion '{action}' empfangen.")


                    # *** BEGINN der Nachrichtenverarbeitung unter Lock ***
                    with data_lock:
                        current_game_status_in_handler = game_data.get("status")

                        # --- FORCE_SERVER_RESET_FROM_CLIENT ---
                        if action == "FORCE_SERVER_RESET_FROM_CLIENT":
                            client_name_for_reset_log = player_name_for_log if player_id else f"Client {addr[0]}:{addr[1]}"
                            print(f"SERVER ADMIN: {client_name_for_reset_log} hat Server-Reset (FORCE_SERVER_RESET_FROM_CLIENT) angefordert.")
                            reset_message_for_clients = f"Server wurde von '{client_name_for_reset_log}' zurückgesetzt. Bitte neu beitreten."
                            reset_game_to_initial_state(notify_clients_about_reset=True, reset_message=reset_message_for_clients)
                            ack_payload = {"type": "acknowledgement", "message": "Server wurde erfolgreich zurückgesetzt."}
                            _safe_send_json(conn, ack_payload, player_id, player_name_for_log)
                            # NEUES LOG
                            print(f"SERVER ADMIN: Reset durch {client_name_for_reset_log} abgeschlossen. Handler-Thread wird beendet.")
                            return # Beendet den Handler-Thread nach Reset

                        # --- JOIN_GAME (Neuer Spieler) ---
                        if action == "JOIN_GAME" and player_id is None: # Nur wenn noch keine player_id für diesen Handler
                            p_name = message.get("name", f"Anon_{random.randint(1000,9999)}")
                            MAX_NICKNAME_LENGTH = 50
                            if len(p_name) > MAX_NICKNAME_LENGTH:
                                p_name = p_name[:MAX_NICKNAME_LENGTH] + "..."
                                print(f"SERVER JOIN WARN: Nickname von {addr} auf {MAX_NICKNAME_LENGTH} Zeichen gekürzt.")
                            p_role_pref = message.get("role_preference", "hider") # Standard "hider"
                            if p_role_pref not in ["hider", "seeker"]: p_role_pref = "hider"
                            player_name_for_log = p_name # Aktualisiere Log-Namen

                            # Prüfe, ob Name bereits von einem aktiven Spieler verwendet wird
                            is_name_taken = False
                            for pid_check, pinfo_check in game_data.get("players", {}).items():
                                if pinfo_check.get("name") == p_name and pinfo_check.get("client_conn") is not None and pid_check != player_id: # Ignoriere eigenen Eintrag, falls Rejoin-Logik später angepasst wird
                                    is_name_taken = True; break
                            if is_name_taken:
                                print(f"SERVER JOIN (FAIL): Name '{p_name}' ist bereits von einem aktiven Spieler belegt. {addr}")
                                error_payload = {
                                    "type": "game_update", "player_id": None, # Wichtig: Client ID bleibt None
                                    "error_message": f"Name '{p_name}' bereits vergeben. Wähle einen anderen Namen.",
                                    "join_error": f"Name '{p_name}' bereits vergeben.", # Spezifischer Fehler für Join-Screen
                                    "game_state": { "status": "disconnected", "status_display": "Beitritt fehlgeschlagen."}
                                }
                                _safe_send_json(conn, error_payload, "N/A_JOIN_FAIL_NAME_TAKEN", p_name)
                                return # Beendet Handler, Client muss neuen Namen wählen

                            # Generiere eindeutige Player-ID
                            base_id = str(addr[1]) + "_" + str(random.randint(1000, 9999)) # Port + Zufallszahl
                            id_counter = 0; temp_id_candidate = base_id
                            while temp_id_candidate in game_data.get("players", {}): # Sicherstellen, dass ID wirklich neu ist
                                id_counter += 1; temp_id_candidate = f"{base_id}_{id_counter}"
                            player_id = temp_id_candidate # Eindeutige ID für diesen Handler/Spieler
                            player_entry_data = {
                                "addr": addr, "name": p_name, "original_role": p_role_pref, "current_role": p_role_pref,
                                "location": None, "last_seen": time.time(), "client_conn": conn,
                                "confirmed_for_lobby": True, "is_ready": False, "status_ingame": "active",
                                "status_before_offline": "active", "points": 0, "has_pending_location_warning": False,
                                "last_location_update_after_warning": 0, "warning_sent_time": 0, "last_location_timestamp": 0,
                                "task": None, "task_deadline": None,
                                "task_skips_available": INITIAL_TASK_SKIPS if p_role_pref == "hider" else 0,
                                "is_waiting_for_lobby": False # Standardmäßig nicht wartend
                            }

                            if current_game_status_in_handler in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                                # Wenn das Spiel gerade beendet wurde und ein neuer Spieler joined, resette den Server für eine neue Runde
                                print(f"SERVER JOIN: Spiel war beendet. Server wird für neue Runde zurückgesetzt, {p_name} ({player_id}) tritt bei.")
                                reset_game_to_initial_state(notify_clients_about_reset=False) # Kein Broadcast an alte Spieler nötig hier
                                current_game_status_in_handler = game_data.get("status") # Status ist jetzt 'lobby'
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                send_data_to_one_client(conn, player_id) # Sende Zustand an neuen Spieler
                                broadcast_full_game_state_to_all(exclude_pid=player_id) # Informiere andere
                            elif current_game_status_in_handler in [GAME_STATE_HIDER_WAIT, GAME_STATE_RUNNING]:
                                # Spiel läuft, Spieler kommt auf die Warteliste
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
                            else: # Spiel ist in der Lobby, normaler Beitritt
                                game_data.setdefault("players", {})[player_id] = player_entry_data
                                print(f"SERVER JOIN-PLAYER-CREATED (lobby): {p_name} ({player_id}) von {addr}.")
                                send_data_to_one_client(conn, player_id) # Sende Zustand an neuen Spieler
                                broadcast_full_game_state_to_all(exclude_pid=player_id) # Informiere andere (falls vorhanden)
                            continue # Zurück zum Anfang der recv-Schleife für diesen Client

                        # --- REJOIN_GAME (Spieler kehrt zurück) ---
                        elif action == "REJOIN_GAME" and player_id is None: # Nur wenn dieser Handler noch keine ID hat
                            rejoin_player_id = message.get("player_id")
                            rejoin_player_name = message.get("name") # Client sendet seinen gespeicherten Namen
                            action_for_log = f"REJOIN_GAME (Attempt ID: {rejoin_player_id}, Name: {rejoin_player_name})"
                            found_player_to_rejoin = False
                            if rejoin_player_id and rejoin_player_id in game_data.get("players", {}):
                                player_entry = game_data["players"][rejoin_player_id]
                                # Überprüfe, ob der Name übereinstimmt (optional, aber gut für Konsistenz)
                                if player_entry.get("name") != rejoin_player_name:
                                    print(f"SERVER REJOIN WARN: Name mismatch for ID {rejoin_player_id}. Client: '{rejoin_player_name}', Server: '{player_entry.get('name')}'. Rejoin trotzdem erlaubt.")
                                
                                # Alte Verbindung des Spielers (falls vorhanden und anders) schließen
                                old_conn = player_entry.get("client_conn")
                                if old_conn and old_conn != conn:
                                    print(f"SERVER REJOIN: Spieler {player_entry.get('name')} ({rejoin_player_id}) hatte alte Verbindung. Aktualisiere auf neue.")
                                    try: # Versuche alte Verbindung sauber zu schließen
                                        old_conn.shutdown(socket.SHUT_RDWR)
                                        old_conn.close()
                                    except Exception as e: print(f"SERVER REJOIN WARN: Fehler beim Schließen alter Verbindung für {rejoin_player_id}: {e}")
                                
                                # Aktualisiere Spielerdaten mit neuer Verbindung
                                player_entry["client_conn"] = conn # Neue Verbindung zuweisen
                                player_entry["addr"] = addr
                                player_entry["last_seen"] = time.time() # Update "zuletzt gesehen"
                                player_id = rejoin_player_id # Handler ist jetzt diesem Spieler zugeordnet
                                player_name_for_log = player_entry.get("name", rejoin_player_name) # Für Logs
                                found_player_to_rejoin = True

                                # Wenn Spieler als "offline" markiert war, wieder aktivieren
                                if player_entry.get("status_ingame") == "offline":
                                    previous_status = player_entry.get("status_before_offline", "active")
                                    player_entry["status_ingame"] = previous_status
                                    player_entry.pop("status_before_offline", None) # Entferne temporären Status
                                    broadcast_server_text_notification(f"Spieler {player_entry.get('name', rejoin_player_name)} ist wieder online (Status: {previous_status}).")
                                    print(f"SERVER REJOIN: Spieler {player_name_for_log} ({player_id}) Status von 'offline' auf '{previous_status}' gesetzt.")
                                
                                print(f"SERVER REJOIN (SUCCESS): Spieler {player_name_for_log} ({player_id}) re-assoziiert mit neuer Verbindung von {addr}")
                                send_data_to_one_client(conn, player_id) # Sende aktuellen Zustand an den re-joined Spieler
                                broadcast_full_game_state_to_all(exclude_pid=player_id) # Informiere andere
                            else:
                                print(f"SERVER REJOIN (FAIL): Spieler-ID '{rejoin_player_id}' nicht gefunden für {addr}.")
                                rejoin_fail_payload = {
                                    "type": "game_update", "player_id": None, # Signalisiert Client, dass Rejoin fehlgeschlagen
                                    "error_message": f"Rejoin fehlgeschlagen. Spieler-ID '{rejoin_player_id}' nicht mehr gültig oder gefunden.",
                                    "join_error": f"Rejoin fehlgeschlagen. Spieler-ID '{rejoin_player_id}' nicht mehr gültig oder gefunden.",
                                    "game_state": { "status": "disconnected", "status_display": "Rejoin fehlgeschlagen."}
                                }
                                _safe_send_json(conn, rejoin_fail_payload, "N/A_REJOIN_FAIL", "N/A_REJOIN_FAIL")
                                return # Beendet Handler, Client muss sich neu als neuer Spieler registrieren
                            continue # Zurück zum Anfang der recv-Schleife

                        # --- Authentifizierung für weitere Aktionen ---
                        if not player_id or player_id not in game_data.get("players", {}):
                            print(f"SERVER WARN: Unauthentifizierter/Entfernter Client von {addr} sendet Aktion '{action}'. Player_id im Handler: {player_id}. Verbindung wird getrennt.")
                            error_payload_unauth = {
                                "type":"game_update", "player_id": None, # Wichtig: Client ID entfernen
                                "message":"Nicht authentifiziert oder aus Spiel entfernt. Bitte neu beitreten.",
                                "join_error": "Sitzung ungültig oder abgelaufen. Bitte neu beitreten.",
                                "game_state": {"status": "disconnected", "status_display": "Sitzung ungültig."}
                            }
                            _safe_send_json(conn, error_payload_unauth, "N/A_UNAUTH", "N/A_UNAUTH")
                            return # Beendet Handler-Thread

                        # Ab hier hat der Client eine gültige player_id und ist im Spiel
                        current_player_data = game_data["players"][player_id]
                        current_player_data["last_seen"] = time.time() # Update "zuletzt gesehen"
                        if current_player_data.get("client_conn") != conn: # Falls sich Conn geändert hat (sollte durch Rejoin abgedeckt sein)
                            current_player_data["client_conn"] = conn
                        player_name_for_log = current_player_data.get("name", "N/A") # Aktualisiere für Logs


                        # --- Weitere Spielaktionen ---
                        if action == "SET_READY":
                            if current_game_status_in_handler == GAME_STATE_LOBBY and current_player_data.get("confirmed_for_lobby"):
                                current_player_data["is_ready"] = message.get("ready_status") == True
                                print(f"SERVER ACTION: P:{player_id} ({player_name_for_log}) gesetzt auf is_ready={current_player_data['is_ready']}.")
                                broadcast_full_game_state_to_all()
                            else:
                                print(f"SERVER ACTION DENIED: P:{player_id} ({player_name_for_log}) SET_READY in falschem Status/Konf. ({current_game_status_in_handler}, confirmed={current_player_data.get('confirmed_for_lobby')}).")
                                send_data_to_one_client(conn, player_id) # Sende aktuellen (unveränderten) Zustand
                        elif action == "UPDATE_LOCATION":
                            lat, lon = message.get("lat"), message.get("lon")
                            accuracy = message.get("accuracy") # Kann None sein, wenn nicht vom Client gesendet
                            if isinstance(lat, (float, int)) and isinstance(lon, (float, int)):
                                current_player_data["location"] = [lat, lon, accuracy]
                                current_player_data["last_location_timestamp"] = time.time()
                                # Prüfe, ob dies ein Update nach einer Warnung ist
                                if current_player_data.get("has_pending_location_warning"):
                                    if time.time() > current_player_data.get("warning_sent_time", 0): # Nur wenn Warnung schon gesendet wurde
                                         current_player_data["last_location_update_after_warning"] = time.time()
                                # Kein voller Broadcast hier, da Standortupdates häufig sind.
                                # Der Client erhält eine Bestätigung indirekt durch das nächste reguläre game_update.
                                # Optional: eine kleine Ack-Nachricht senden, wenn Performance kein Problem ist.
                                send_data_to_one_client(conn, player_id) # Update an den Client selbst ist ok
                            else:
                                print(f"SERVER WARN: Ungültige Standortdaten von P:{player_id} ({player_name_for_log}): lat={lat}, lon={lon}")
                                _safe_send_json(conn, {"type":"error", "message":"Ungültige Standortdaten empfangen."}, player_id, player_name_for_log)
                        elif action == "TASK_COMPLETE":
                            status_changed = False
                            if current_player_data["current_role"] == "hider" and \
                               current_player_data["status_ingame"] == "active" and \
                               current_player_data.get("task"): # Spieler muss eine aktive Aufgabe haben
                                task_details = current_player_data["task"]
                                if time.time() <= current_player_data.get("task_deadline", 0): # Innerhalb der Zeit
                                    current_player_data["points"] += task_details.get("points", 0)
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_details.get('description', 'N/A')}' erledigt!")
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None
                                    assign_task_to_hider(player_id); status_changed = True
                                else: # Aufgabe zu spät
                                    task_description_for_log = current_player_data.get("task",{}).get('description','N/A')
                                    current_player_data["task"], current_player_data["task_deadline"] = None, None
                                    broadcast_server_text_notification(f"Hider {player_name_for_log} hat Aufgabe '{task_description_for_log}' zu spät eingereicht! Aufgabe entfernt.")
                                    assign_task_to_hider(player_id); status_changed = True # Status änderte sich (Aufgabe weg)
                            if status_changed:
                                if check_game_conditions_and_end(): pass # Prüfe ob Spiel vorbei
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
                                 current_player_data.get("status_ingame") not in ["caught", "failed_task", "failed_loc_update"]: # Muss noch im Spiel sein
                                server_task_info = current_player_data.get("task")
                                server_task_deadline = current_player_data.get("task_deadline")
                                if server_task_info and server_task_info.get("id") == task_id_offline:
                                    # Aufgabe stimmt überein
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
                                        # Aufgabe trotzdem entfernen und neue zuweisen
                                        current_player_data["task"], current_player_data["task_deadline"] = None, None
                                        assign_task_to_hider(player_id) ; status_changed_offline = True # Aufgabe hat sich geändert
                                else: # Client meldet eine Aufgabe, die nicht (mehr) die aktuelle serverseitige ist
                                    err_msg_to_client = f"Gemeldete Offline-Aufgabe (ID: {task_id_offline}) ist nicht (mehr) deine aktuelle Server-Aufgabe."
                            else: err_msg_to_client = "Offline-Aufgabe kann nicht angerechnet werden (falsche Rolle oder Spielerstatus)."

                            if err_msg_to_client: _safe_send_json(conn, {"type": "error", "message": err_msg_to_client}, player_id, player_name_for_log)
                            if ack_msg_to_client: _safe_send_json(conn, {"type": "acknowledgement", "message": ack_msg_to_client}, player_id, player_name_for_log)

                            if status_changed_offline:
                                if check_game_conditions_and_end(): pass # Prüfe ob Spiel vorbei
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id) # Nur eigenen Status aktualisieren
                        elif action == "SKIP_TASK":
                            task_skipped_successfully = False; error_message_to_client = None; ack_message_to_client = None
                            if current_player_data["current_role"] == "hider" and current_player_data["status_ingame"] == "active":
                                if current_player_data.get("task"): # Hat eine Aufgabe
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
                            else: send_data_to_one_client(conn,player_id) # Nur eigenen Status aktualisieren (z.B. für Fehlermeldung)
                        elif action == "CATCH_HIDER":
                            hider_id_to_catch = message.get("hider_id_to_catch"); caught = False
                            if current_player_data["current_role"] == "seeker" and \
                               current_game_status_in_handler == GAME_STATE_RUNNING and \
                               hider_id_to_catch in game_data.get("players", {}): # Hider muss existieren
                                hider_player_data = game_data["players"][hider_id_to_catch]
                                if hider_player_data.get("current_role") == "hider" and hider_player_data.get("status_ingame") == "active":
                                    hider_player_data["current_role"] = "seeker" # Gefangener Hider wird zum Seeker
                                    hider_player_data["status_ingame"] = "caught"
                                    hider_player_data["task"], hider_player_data["task_deadline"] = None, None # Keine Aufgaben mehr
                                    hider_player_data["task_skips_available"] = 0 # Keine Skips mehr
                                    broadcast_server_text_notification(f"Seeker {player_name_for_log} hat Hider {hider_player_data.get('name','N/A')} gefangen!")
                                    print(f"SERVER ACTION: Seeker {player_name_for_log} ({player_id}) hat Hider {hider_player_data.get('name','N/A')} ({hider_id_to_catch}) gefangen.")
                                    caught = True
                                else: _safe_send_json(conn, {"type":"error", "message":f"Hider {hider_player_data.get('name','N/A')} kann nicht gefangen werden (falsche Rolle/Status oder Offline)."}, player_id, player_name_for_log)
                            else: _safe_send_json(conn, {"type":"error", "message":f"Aktion 'Fangen' nicht möglich (falsche Rolle/Status oder Hider nicht gefunden)."}, player_id, player_name_for_log)
                            if caught:
                                if check_game_conditions_and_end(): pass # Prüfe, ob Spiel vorbei ist
                                broadcast_full_game_state_to_all()
                            else: send_data_to_one_client(conn, player_id) # Nur eigenen Status aktualisieren
                        elif action == "RETURN_TO_REGISTRATION": # Spieler will Name/Rolle in Lobby ändern
                            if current_game_status_in_handler == GAME_STATE_LOBBY and player_id in game_data.get("players", {}):
                                print(f"SERVER ACTION: Spieler {player_name_for_log} ({player_id}) kehrt zur Registrierung zurück.")
                                del game_data["players"][player_id] # Spieler aus dem Spiel entfernen
                                # Client-seitig wird player_id auf None gesetzt durch diese Nachricht
                                reset_payload = { "type": "game_update", "player_id": None, "join_error": None, "game_message": "Bitte gib deine Details erneut ein." }
                                _safe_send_json(conn, reset_payload, player_id, player_name_for_log)
                                player_id = None; player_name_for_log = "Unbekannt_Nach_Reset" # Handler hat keine ID mehr
                                broadcast_full_game_state_to_all() # Andere Spieler informieren
                            else: send_data_to_one_client(conn, player_id) # Nicht erlaubte Aktion, nur Status senden
                        elif action == "LEAVE_GAME_AND_GO_TO_JOIN": # Spieler verlässt das Spiel komplett
                            print(f"SERVER LEAVE: Spieler {player_name_for_log} ({player_id}) verlässt das Spiel.")
                            if player_id in game_data.get("players", {}):
                                # Markiere Spieler als "ausgeschieden" oder ähnlich, falls das Spiel noch läuft
                                if game_data["players"][player_id].get("status_ingame") == "active":
                                     game_data["players"][player_id]["status_ingame"] = "failed_loc_update" # Oder ein spezifischer "left_game" Status
                                     game_data["players"][player_id]["current_role"] = "seeker" # Verhindert, dass er als Hider gewinnt
                                     game_data["players"][player_id]["task"] = None; game_data["players"][player_id]["task_deadline"] = None
                                     game_data["players"][player_id]["task_skips_available"] = 0
                                     game_data["players"][player_id].pop("status_before_offline", None) # Offline Status irrelevant
                                     broadcast_server_text_notification(f"Spieler {player_name_for_log} hat das Spiel vorzeitig verlassen.")
                                # Spieler wird nicht aus game_data["players"] gelöscht, um ihn im Leaderboard etc. zu behalten,
                                # aber seine Verbindung wird getrennt und er kann nicht mehr teilnehmen.
                            # Sende eine Bestätigung, aber setze player_id in der Antwort nicht auf None.
                            # Der Client wird selbst user_has_initiated_connection auf False setzen.
                            _safe_send_json(conn, {"type": "acknowledgement", "message": "Du hast das Spiel verlassen."}, player_id, player_name_for_log)
                            # Wichtig: Der Handler-Thread wird durch return beendet, Client muss Socket schließen.
                            # Der player_id bleibt für diesen Handler-Aufruf bestehen, wird aber im finally-Block behandelt.
                            player_id = None # Signalisiert dem finally Block, dass dieser Spieler nicht mehr aktiv ist.
                            broadcast_full_game_state_to_all() # Andere informieren
                            return # Beendet den Handler-Thread
                        elif action == "REQUEST_EARLY_ROUND_END":
                            if current_game_status_in_handler in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT] and \
                               current_player_data.get("status_ingame") == "active" and \
                               current_player_data.get("confirmed_for_lobby"):
                                game_data.setdefault("early_end_requests", set()).add(player_id)
                                game_data["total_active_players_for_early_end"] = count_active_players_for_early_end() # Neu zählen
                                # Prüfe, ob genug Spieler für ein vorzeitiges Ende gestimmt haben
                                if game_data["total_active_players_for_early_end"] > 0 and \
                                   len(game_data["early_end_requests"]) >= game_data["total_active_players_for_early_end"]:
                                    # Alle aktiven Spieler wollen das Spiel beenden
                                    game_data["status"] = GAME_STATE_SEEKER_WINS # Standardmäßig gewinnen Seeker bei Abbruch
                                    game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_SEEKER_WINS]
                                    game_data["game_over_message"] = f"Spiel durch Konsens vorzeitig beendet (während {GAME_STATE_DISPLAY_NAMES.get(current_game_status_in_handler, current_game_status_in_handler)}). Seeker gewinnen!"
                                    game_data["early_end_requests"].clear()
                                    print(f"SERVER LOGIC: Spiel vorzeitig beendet durch Konsens ({len(game_data.get('early_end_requests',set()))}/{game_data['total_active_players_for_early_end']}).") # .get mit default für early_end_requests
                                broadcast_full_game_state_to_all()
                            else:
                                print(f"SERVER ACTION DENIED: P:{player_id} ({player_name_for_log}) REQUEST_EARLY_ROUND_END in falschem Status/Konf. ({current_game_status_in_handler}, active={current_player_data.get('status_ingame')}).")
                                send_data_to_one_client(conn, player_id) # Nur eigenen Status aktualisieren
                        else: # Unbekannte Aktion
                            print(f"SERVER WARN: Unbekannte/unerwartete Aktion '{action}' von P:{player_id} ({player_name_for_log}) empfangen.")
                            _safe_send_json(conn, {"type":"error", "message": f"Aktion '{action}' unbekannt oder derzeit nicht erlaubt."}, player_id, player_name_for_log)
                    # *** ENDE der Nachrichtenverarbeitung unter Lock ***

            except json.JSONDecodeError:
                print(f"SERVER JSON DECODE ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}): Buffer war '{buffer[:200]}...'")
                _safe_send_json(conn, {"type":"error", "message":"Fehlerhafte JSON-Daten empfangen. Verbindung könnte instabil sein."}, player_id, player_name_for_log)
                buffer = "" # Puffer leeren, um Fehler nicht zu wiederholen
            except (ConnectionResetError, BrokenPipeError, OSError) as e_comm_loop:
                print(f"SERVER COMM ERROR in handler loop ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_comm_loop}")
                break # Beendet die while True Schleife für Nachrichtenempfang -> führt zu finally
            except Exception as e_inner_loop: # Fange alle anderen Fehler in der Nachrichtenverarbeitung ab
                print(f"SERVER UNEXPECTED INNER LOOP ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Aktion: {action_for_log}. Fehler: {e_inner_loop}"); traceback.print_exc()
                _safe_send_json(conn, {"type":"error", "message":"Interner Serverfehler bei Nachrichtenverarbeitung."}, player_id, player_name_for_log)
                # Hier nicht breaken, vielleicht erholt sich der Handler für die nächste Nachricht.

    except Exception as e_outer_handler: # Fängt Fehler in der äußeren while True oder beim initialen recv ab
        print(f"SERVER UNEXPECTED HANDLER ERROR ({addr}, P:{player_id}, Name:{player_name_for_log}). Fehler: {e_outer_handler}"); traceback.print_exc()
    finally:
        # --- Aufräumarbeiten beim Beenden des Handler-Threads ---
        # NEUES LOG
        print(f"SERVER CLEANUP ENTERED ({addr}, P:{player_id}, Name: {player_name_for_log}). Socket: {conn}")
        player_affected_by_disconnect = False
        player_rejoined_meanwhile = False # Hat sich der Spieler in der Zwischenzeit mit einem neuen Socket verbunden?
        with data_lock:
            if player_id and player_id in game_data.get("players", {}): # Spieler war dem Spiel bekannt
                player_entry = game_data["players"][player_id]
                # NEUES LOG
                print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler in game_data gefunden. Aktuelle conn des Spielers: {player_entry.get('client_conn')}, Handler conn: {conn}")
                if player_entry.get("client_conn") == conn: # Ist dies die aktuelle Verbindung des Spielers?
                    player_entry["client_conn"] = None # Verbindung als getrennt markieren
                    # Spieler als "offline" markieren, wenn er nicht bereits "gefangen" etc. ist
                    if player_entry.get("status_ingame") not in ["offline", "caught", "failed_task", "failed_loc_update"]:
                        player_entry["status_before_offline"] = player_entry.get("status_ingame", "active") # Alten Status merken
                        player_entry["status_ingame"] = "offline"
                        player_affected_by_disconnect = True
                        print(f"SERVER DISCONNECT: Spieler {player_name_for_log} ({player_id}) Status auf 'offline' gesetzt.")
                    else: # Spieler war bereits in einem Endstatus oder offline
                        print(f"SERVER DISCONNECT: P:{player_id} ({player_name_for_log}) war bereits in End-Status oder offline. Keine Statusänderung.")
                else: # Der Spieler hat sich anscheinend mit einer neuen Verbindung re-joined.
                    player_rejoined_meanwhile = True
                    # NEUES LOG
                    print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler hat sich bereits mit neuer Verbindung verbunden ({player_entry.get('client_conn')}). Alte Handler-Verbindung ({conn}) wird nur geschlossen.")
            elif player_id: # player_id ist nicht None, aber nicht in game_data.players (z.B. nach Server-Reset oder RETURN_TO_REGISTRATION)
                 # NEUES LOG
                 print(f"SERVER CLEANUP ({addr}, P:{player_id}): Spieler-ID bekannt, aber Spieler NICHT MEHR in game_data (z.B. nach Reset oder RETURN_TO_REGISTRATION).")
            else: # player_id war None (z.B. Join nie erfolgt oder nach LEAVE_GAME)
                 # NEUES LOG
                 print(f"SERVER CLEANUP ({addr}): Keine Spieler-ID für diesen Handler gesetzt (z.B. Join nie erfolgt, nach RETURN_TO_REGISTRATION oder LEAVE_GAME).")

        # Broadcast, wenn ein aktiver Spieler offline geht
        if player_affected_by_disconnect: # Nur wenn sich der Status wirklich geändert hat
            if game_data.get("status") == GAME_STATE_RUNNING: # Im laufenden Spiel prüfen, ob Spielende
                if check_game_conditions_and_end(): pass # Prüft und setzt ggf. Spielende-Status
            broadcast_full_game_state_to_all() # Informiere alle über Statusänderung
            broadcast_server_text_notification(f"Spieler {player_name_for_log} ist offline gegangen.")
        elif player_rejoined_meanwhile:
            # NEUES LOG
             print(f"SERVER CLEANUP ({addr}, P:{player_id}): Kein Broadcast nötig, da Spieler bereits rejoined und die neue Verbindung aktiv ist.")
        # Ansonsten (Spieler war nicht in game_data oder schon offline) kein Broadcast nötig.

        # Schließe die Verbindung dieses Handler-Threads
        if conn: # Nur wenn conn existiert
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
            time.sleep(1) # Haupt-Tick des Spiels (1 Sekunde)
            game_ended_this_tick = False # Wird hier nicht direkt verwendet, aber kann für komplexere Logik nützlich sein
            broadcast_needed_due_to_time_or_state_change = False

            with data_lock:
                current_time = time.time()
                current_game_status = game_data.get("status")
                if current_game_status is None: # Sollte nicht passieren, aber als Fallback
                    print("SERVER GAMELOGIC (ERROR): Game status is None. Resetting game to initial state.")
                    reset_game_to_initial_state(); current_game_status = game_data.get("status")

                # Prüfe, ob sich der Spielstatus seit dem letzten Tick geändert hat
                if previous_game_status_for_logic != current_game_status:
                    broadcast_needed_due_to_time_or_state_change = True
                    # NEUES LOG
                    print(f"SERVER GAMELOGIC: Game status changed from '{previous_game_status_for_logic}' to '{current_game_status}'.")
                    previous_game_status_for_logic = current_game_status
                    # Wenn das Spiel gerade erst gestartet wurde (egal ob HIDER_WAIT oder RUNNING), leere die Abstimmungsanfragen.
                    if current_game_status in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]:
                        game_data["early_end_requests"] = set()
                        game_data["total_active_players_for_early_end"] = count_active_players_for_early_end()

                # --- Logik für GAME_STATE_LOBBY ---
                if current_game_status == GAME_STATE_LOBBY:
                    active_lobby_player_count = 0; all_in_active_lobby_ready = True
                    current_players_in_lobby = game_data.get("players", {})
                    if not current_players_in_lobby: all_in_active_lobby_ready = False # Keine Spieler -> nicht bereit
                    else:
                        confirmed_players_for_lobby = [p for p in current_players_in_lobby.values()
                                                       if p.get("confirmed_for_lobby") and p.get("client_conn") is not None]
                        if not confirmed_players_for_lobby: # Keine bestätigten Spieler in der Lobby
                            all_in_active_lobby_ready = False
                        else:
                            active_lobby_player_count = len(confirmed_players_for_lobby)
                            for p_info_check in confirmed_players_for_lobby:
                                if not p_info_check.get("is_ready", False):
                                    all_in_active_lobby_ready = False; break

                    MIN_PLAYERS_TO_START = 1 # Mindestanzahl Spieler, damit das Spiel startet
                    if all_in_active_lobby_ready and active_lobby_player_count >= MIN_PLAYERS_TO_START:
                        # Alle bereit und genug Spieler -> Starte Hider-Vorbereitungszeit
                        game_data["status"] = GAME_STATE_HIDER_WAIT
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_HIDER_WAIT]
                        game_data["hider_wait_end_time"] = current_time + HIDER_INITIAL_DEPARTURE_TIME_SECONDS
                        # NEUES LOG
                        print(f"SERVER GAMELOGIC: Wechsel zu HIDER_WAIT. Endzeit: {time.strftime('%H:%M:%S', time.localtime(game_data['hider_wait_end_time']))}. Spieler: {active_lobby_player_count}")
                        broadcast_needed_due_to_time_or_state_change = True # Wird am Ende des Ticks ausgelöst

                # --- Logik für GAME_STATE_HIDER_WAIT ---
                elif current_game_status == GAME_STATE_HIDER_WAIT:
                    if game_data.get("hider_wait_end_time") and current_time >= game_data["hider_wait_end_time"]:
                        # Hider-Vorbereitungszeit abgelaufen -> Starte das Spiel
                        game_data["status"] = GAME_STATE_RUNNING
                        game_data["status_display"] = GAME_STATE_DISPLAY_NAMES[GAME_STATE_RUNNING]
                        game_data["game_start_time_actual"] = current_time
                        game_data["game_end_time"] = current_time + GAME_DURATION_SECONDS
                        # NEUES LOG
                        print(f"SERVER GAMELOGIC: Wechsel zu RUNNING. Spielende: {time.strftime('%H:%M:%S', time.localtime(game_data['game_end_time']))}")

                        # Initialisiere Phasen-Tracking für Hider-Standort-Updates
                        game_data["current_phase_index"] = 0 # Beginne mit der ersten Phase
                        game_data["current_phase_start_time"] = current_time
                        game_data["updates_done_in_current_phase"] = 0
                        _calculate_and_set_next_broadcast_time(current_time) # Berechne den ersten Broadcast-Zeitpunkt

                        # Aufgaben an Hider verteilen
                        for p_id_task, p_info_task in list(game_data.get("players", {}).items()): # Kopie für sichere Iteration
                            if p_info_task.get("current_role") == "hider" and \
                               p_info_task.get("confirmed_for_lobby") and \
                               p_info_task.get("status_ingame") == "active":
                                assign_task_to_hider(p_id_task)

                        # Event an Clients senden, dass das Spiel gestartet ist
                        event_payload_gs = {"type": "game_event", "event_name": "game_started"}
                        player_list_copy_gs = list(game_data.get("players", {}).items())
                        for p_id_event, p_info_event in player_list_copy_gs:
                            conn_gs = p_info_event.get("client_conn")
                            if conn_gs: _safe_send_json(conn_gs, event_payload_gs, p_id_event, p_info_event.get("name"))

                        broadcast_needed_due_to_time_or_state_change = True
                    elif game_data.get("hider_wait_end_time") and int(game_data["hider_wait_end_time"] - current_time) % 3 == 0 : # Regelmäßige Updates für Countdown
                        broadcast_needed_due_to_time_or_state_change = True

                # --- Logik für GAME_STATE_RUNNING ---
                elif current_game_status == GAME_STATE_RUNNING:
                    if check_game_conditions_and_end(): # Prüft, ob Spiel vorbei (z.B. alle Hider gefangen, Zeit abgelaufen)
                        game_ended_this_tick = True # Markiere, dass das Spiel in diesem Tick beendet wurde
                        # broadcast_full_game_state_to_all() wird am Ende des Ticks ausgelöst, wenn game_ended_this_tick oder broadcast_needed... True ist.
                    else:
                        # Logik für Hider-Standort-Warnungen und Broadcasts
                        next_b_time = game_data.get("next_location_broadcast_time", float('inf'))
                        warning_time_trigger = next_b_time - HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS

                        current_phase_idx_for_warn = game_data.get("current_phase_index", -1)
                        allow_warning = True # Standardmäßig Warnung erlauben
                        if 0 <= current_phase_idx_for_warn < len(PHASE_DEFINITIONS):
                            phase_def_warn = PHASE_DEFINITIONS[current_phase_idx_for_warn]
                            # Berechne das effektive Intervall der aktuellen Phase
                            interval_check = phase_def_warn.get("update_interval_seconds")
                            if interval_check is None and phase_def_warn.get("updates_in_phase", 0) > 0 and phase_def_warn.get("duration_seconds",0) > 0 :
                                interval_check = phase_def_warn["duration_seconds"] / phase_def_warn["updates_in_phase"]
                            elif interval_check is None:
                                interval_check = 1000 # Hoher Wert, falls nicht anders definiert (z.B. initial reveal)

                            if interval_check < HIDER_WARNING_BEFORE_SEEKER_UPDATE_SECONDS + 5: # Puffer von 5s
                                allow_warning = False # Keine Warnung, wenn das Intervall zu kurz ist

                        if allow_warning and \
                           not game_data.get("hider_warning_active_for_current_cycle", False) and \
                           current_time >= warning_time_trigger and current_time < next_b_time:
                            # Hider-Warnung ist fällig
                            game_data["hider_warning_active_for_current_cycle"] = True
                            hiders_needing_warning_update = False
                            event_payload_warn = {"type": "game_event", "event_name": "hider_location_update_due"}
                            player_list_copy_warn = list(game_data.get("players", {}).items()) # Kopie für sichere Iteration
                            for p_id, p_info in player_list_copy_warn:
                                if p_id not in game_data.get("players",{}): continue # Spieler könnte zwischenzeitlich entfernt worden sein
                                if p_info.get("current_role") == "hider" and \
                                   p_info.get("status_ingame") == "active" and \
                                   p_info.get("client_conn"):
                                    if not p_info.get("has_pending_location_warning"): # Nur einmal pro Zyklus setzen
                                        game_data["players"][p_id]["has_pending_location_warning"] = True
                                        game_data["players"][p_id]["warning_sent_time"] = current_time
                                        game_data["players"][p_id]["last_location_update_after_warning"] = 0 # Zurücksetzen
                                        hiders_needing_warning_update = True
                                        conn_warn = p_info.get("client_conn")
                                        if conn_warn: _safe_send_json(conn_warn, event_payload_warn, p_id, p_info.get("name"))
                            if hiders_needing_warning_update: broadcast_needed_due_to_time_or_state_change = True

                        if current_time >= next_b_time and next_b_time != float('inf'):
                            # Zeit für Hider-Standort-Broadcast an Seeker
                            game_data["hider_warning_active_for_current_cycle"] = False # Reset für den nächsten Zyklus

                            active_hiders_who_failed_update_names = []
                            player_list_copy_bc = list(game_data.get("players", {}).items()) # Kopie für sichere Iteration
                            for p_id_h, p_info_h in player_list_copy_bc:
                                if p_id_h not in game_data.get("players", {}): continue # Spieler könnte zwischenzeitlich entfernt worden sein
                                if p_info_h.get("current_role") == "hider" and p_info_h.get("status_ingame") == "active":
                                    # Überprüfe, ob eine Warnung aktiv war und ob seitdem ein Update kam
                                    if p_info_h.get("has_pending_location_warning") and p_info_h.get("client_conn"):
                                        if p_info_h.get("last_location_update_after_warning", 0) <= p_info_h.get("warning_sent_time", 0):
                                            # Kein Update oder Update war vor der Warnung
                                            active_hiders_who_failed_update_names.append(p_info_h.get('name', 'Unbekannt'))
                                    # Warnflag für diesen Spieler zurücksetzen, egal ob Update kam oder nicht
                                    game_data["players"][p_id_h]["has_pending_location_warning"] = False

                            if active_hiders_who_failed_update_names:
                                 broadcast_server_text_notification(f"Hider haben Standort nach Warnung NICHT aktualisiert: {', '.join(active_hiders_who_failed_update_names)}. Sie bleiben aktiv (keine Strafe).")

                            # Standort-Broadcast durchführen
                            game_data["updates_done_in_current_phase"] += 1
                            print(f"SERVER GAMELOGIC: Hider-Standort-Broadcast durchgeführt (Update {game_data['updates_done_in_current_phase']} in Phase {game_data.get('current_phase_index',0)}).")
                            event_payload_seeker = {"type": "game_event", "event_name": "seeker_locations_updated"}
                            player_list_copy_seek_ev = list(game_data.get("players", {}).items()) # Kopie
                            for p_id_s, p_info_s in player_list_copy_seek_ev:
                                if p_id_s not in game_data.get("players",{}): continue
                                if p_info_s.get("current_role") == "seeker" and p_info_s.get("client_conn"):
                                    conn_seek_ev = p_info_s.get("client_conn")
                                    if conn_seek_ev: _safe_send_json(conn_seek_ev, event_payload_seeker, p_id_s, p_info_s.get("name"))

                            _calculate_and_set_next_broadcast_time(current_time) # Nächsten Broadcast planen
                            broadcast_needed_due_to_time_or_state_change = True

                        # Regelmäßiger Broadcast für Countdown, falls keine andere Aktion einen Broadcast auslöst
                        if game_data.get("game_end_time") and int(game_data.get("game_end_time",0) - current_time) % 5 == 0 :
                            broadcast_needed_due_to_time_or_state_change = True

                        # Regelmäßige Überprüfung der aktiven Spieler für die Early-End-Abstimmung
                        if int(current_time) % 10 == 0 : # Alle 10 Sekunden
                            new_active_count = count_active_players_for_early_end()
                            if game_data.get("total_active_players_for_early_end") != new_active_count:
                                game_data["total_active_players_for_early_end"] = new_active_count
                                broadcast_needed_due_to_time_or_state_change = True # Update an Clients senden

                # --- Logik für GAME_STATE_HIDER_WINS oder GAME_STATE_SEEKER_WINS ---
                elif current_game_status in [GAME_STATE_HIDER_WINS, GAME_STATE_SEEKER_WINS]:
                    if "actual_game_over_time" not in game_data or game_data["actual_game_over_time"] is None:
                        # Spiel ist gerade eben in den Game-Over-Status gewechselt
                        game_data["actual_game_over_time"] = current_time
                        if not game_data.get("game_end_time"): # Sicherstellen, dass ein Endzeitpunkt existiert
                             game_data["game_end_time"] = current_time
                        # Wichtig: Sofort broadcasten, damit Clients den Game-Over-Screen sehen
                        broadcast_needed_due_to_time_or_state_change = True

                    elif current_time >= game_data.get("actual_game_over_time", float('inf')) + POST_GAME_LOBBY_RETURN_DELAY_SECONDS:
                        # Zeit für den Game-Over-Screen ist abgelaufen -> "HARD RESET"
                        print("SERVER GAMELOGIC: Game over screen timeout. Performing hard reset for new game.")
                        reset_message_for_clients = "Das Spiel ist beendet. Der Server wurde für eine neue Runde zurückgesetzt. Bitte neu beitreten."

                        # Führe einen Hard Reset durch. Diese Funktion ändert game_data["status"] zu GAME_STATE_LOBBY
                        # und benachrichtigt die Clients, indem sie player_id auf None setzt und deren Sockets schließt.
                        reset_game_to_initial_state(notify_clients_about_reset=True, reset_message=reset_message_for_clients)

                        print("SERVER GAMELOGIC: Hard-Reset nach Spielende abgeschlossen.")
                        # Der broadcast_needed_due_to_time_or_state_change wird im nächsten Tick durch den
                        # Statuswechsel zu GAME_STATE_LOBBY (der in reset_game_to_initial_state passiert)
                        # automatisch auf True gesetzt und löst einen Broadcast aus.
                    else:
                        # Während der Game-Over-Anzeige: Regelmäßiger Broadcast, um Clients auf dem Laufenden zu halten
                        time_since_actual_game_over = current_time - game_data.get("actual_game_over_time", current_time)
                        if time_since_actual_game_over < 3: # Häufiger am Anfang
                            if int(current_time * 2) % 2 == 0: # Alle 0.5s für die ersten 3s
                                broadcast_needed_due_to_time_or_state_change = True
                        elif int(current_time) % 5 == 0: # Alle 5s danach
                             broadcast_needed_due_to_time_or_state_change = True

            # Führe einen Broadcast durch, wenn sich der Zustand geändert hat oder ein Timer-Update notwendig ist.
            if game_ended_this_tick or broadcast_needed_due_to_time_or_state_change:
                broadcast_full_game_state_to_all()

        except Exception as e:
            print(f"!!! CRITICAL ERROR IN GAME LOGIC THREAD !!!")
            print(f"Error: {e}")
            traceback.print_exc()
            print(f"Game logic thread wird versuchen, nach einer kurzen Pause fortzufahren.")
            time.sleep(5) # Kurze Pause vor dem nächsten Versuch

def main_server():
    # NEUES LOG
    print("SERVER: Initialisiere Spielzustand beim Serverstart...")
    reset_game_to_initial_state() # Initialer Reset ohne Benachrichtigung
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Erlaube Wiederverwendung der Adresse
    try:
        server_socket.bind((HOST, PORT))
    except OSError as e:
        print(f"!!! SERVER FATAL: Fehler beim Binden an {HOST}:{PORT}: {e}. Läuft Server bereits? !!!"); return
    server_socket.listen()
    print(f"Hide and Seek Server lauscht auf {HOST}:{PORT}")

    # Starte den Game Logic Thread als Daemon, damit er mit dem Hauptprogramm beendet wird
    threading.Thread(target=game_logic_thread, daemon=True).start()
    # Das folgende Log wird jetzt im game_logic_thread selbst ausgegeben.
    # print("SERVER: Game Logic Thread gestartet.")

    try:
        while True:
            # NEUES LOG
            print("SERVER MAIN LOOP: Warte auf neue Verbindung (accept)...")
            conn, addr = server_socket.accept() # Blockiert, bis eine Verbindung eingeht
            # NEUES LOG
            print(f"SERVER MAIN LOOP: Verbindung von {addr} akzeptiert. Starte Handler-Thread.")
            # Starte einen neuen Thread für jeden Client
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
```

---

### `client.py` (Der lokale Client-Proxy)

Dies ist die Datei mit der entscheidenden Änderung, um die Offline-Phasen robuster zu handhaben.

```python
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
                        # ===================== ANFANG DER KORREKTUR =====================
                        
                        # Behandelt den Fall, dass der Server uns mitteilt, dass unsere Sitzung ungültig ist.
                        if "player_id" in message and message["player_id"] is None:
                            
                            # Prüfen, ob dies eine endgültige "Du bist raus"-Nachricht ist
                            # (z.B. weil der Server neu gestartet wurde oder der Rejoin explizit fehlschlug).
                            is_definitive_kick_out = bool(message.get("join_error")) or \
                                                     "Du bist nicht mehr Teil des aktuellen Spiels" in message.get("error_message", "") or \
                                                     "Rejoin fehlgeschlagen" in message.get("error_message", "")

                            # Prüfen, ob der Client selbst davon ausgeht, mitten im Spiel zu sein.
                            client_thinks_its_ingame = (
                                client_view_data.get("player_id") is not None and
                                client_view_data.get("game_state", {}).get("status") in [GAME_STATE_RUNNING, GAME_STATE_HIDER_WAIT]
                            )

                            # NUR wenn es eine definitive Rauswurf-Nachricht ist ODER der Client sowieso nicht im Spiel war,
                            # setzen wir die Spielerdaten zurück.
                            if is_definitive_kick_out or not client_thinks_its_ingame:
                                if client_view_data["player_id"] is not None:
                                    print(f"CLIENT NET: Server hat player_id=None mit definitivem Grund gesendet. Resette Client-Spielerdaten.")
                                
                                client_view_data["player_id"] = None
                                client_view_data["player_name"] = None
                                client_view_data["role"] = None
                                client_view_data["confirmed_for_lobby"] = False
                                client_view_data["player_is_ready"] = False
                                
                                # Wichtig: Nur bei definitivem Rauswurf die Offline-Queue leeren.
                                if client_view_data["offline_action_queue"]:
                                    print("CLIENT NET (player_id=None): Leere Offline-Queue, da Spielerdaten resettet wurden.")
                                    client_view_data["offline_action_queue"].clear()
                                client_view_data["is_processing_offline_queue"] = False

                                if message.get("join_error"): client_view_data["join_error"] = message["join_error"]
                                if message.get("error_message"): client_view_data["error_message"] = message["error_message"]
                            
                            else:
                                # ANDERNFALLS: Der Client glaubt, im Spiel zu sein, und hat nur eine transiente `player_id: null`
                                # ohne zwingenden Grund erhalten. Das passiert bei einem kurzen Verbindungs-Hänger.
                                # Wir ignorieren diese eine Nachricht und vertrauen darauf, dass der nächste Rejoin-Versuch
                                # des Netzwerk-Threads erfolgreich sein wird. Wir geben unsere Identität NICHT auf.
                                print(f"CLIENT NET: Ignoriere transienten player_id=None vom Server, da Client sich im Spiel wähnt und kein expliziter 'join_error' vorliegt. Warte auf Rejoin.")

                        elif "player_id" in message and message["player_id"] is not None:
                            # Erfolgreicher Join, Rejoin oder reguläres Update mit gültiger ID
                            if client_view_data["player_id"] != message["player_id"]:
                                print(f"CLIENT NET: Eigene Player ID vom Server erhalten/geändert zu: {message['player_id']}")
                            client_view_data["player_id"] = message["player_id"]
                            client_view_data["join_error"] = None # Erfolgreich beigetreten -> kein Join-Error mehr

                        # ====================== ENDE DER KORREKTUR ======================

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
