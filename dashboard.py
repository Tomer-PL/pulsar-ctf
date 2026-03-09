"""Local dashboard server for monitoring the LLM Attack-Defense CTF.

Runs on the host (not in Docker) to serve:
- Live scoreboard (proxied from game server)
- Per-team LLM agent logs (tailed from logs/ directory)
- Attack feed
- Game event log

Usage: python dashboard.py
Opens at: http://localhost:9999
"""

import glob
import os
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.request

GAME_SERVER = "http://localhost:8888"
LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
PORT = 9999


def proxy_game_api(path: str) -> bytes:
    """Proxy a request to the game server API."""
    try:
        with urllib.request.urlopen(f"{GAME_SERVER}{path}", timeout=3) as resp:
            return resp.read()
    except Exception as e:
        return json.dumps({"error": str(e)}).encode()


def tail_log(pattern: str, lines: int = 50, filter_fn=None) -> str:
    """Get the last N lines of the most recent log matching pattern."""
    matches = sorted(glob.glob(os.path.join(LOG_DIR, pattern)), key=os.path.getmtime, reverse=True)
    if not matches:
        return f"No log files matching {pattern}"
    try:
        with open(matches[0], "r", errors="replace") as f:
            all_lines = f.readlines()
            if filter_fn:
                all_lines = [l for l in all_lines if filter_fn(l)]
            return "".join(all_lines[-lines:])
    except Exception as e:
        return f"Error reading log: {e}"


DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>AttDef Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Menlo', 'Monaco', monospace; background: #0a0a0a; color: #ccc; }
        .header { background: #111; padding: 15px 30px; border-bottom: 2px solid #333;
                   display: flex; justify-content: space-between; align-items: center; }
        .header h1 { color: #00ff00; font-size: 1.4em; }
        .header .meta { color: #888; font-size: 0.9em; }
        .meta span { margin-left: 20px; }
        .meta .running { color: #00ff00; }
        .meta .stopped { color: #ff4444; }

        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0; height: calc(100vh - 52px); }
        .panel { border: 1px solid #222; overflow: hidden; display: flex; flex-direction: column; }
        .panel-header { background: #1a1a1a; padding: 8px 15px; font-size: 0.85em; font-weight: bold;
                        border-bottom: 1px solid #333; display: flex; justify-content: space-between; }
        .panel-body { flex: 1; overflow-y: auto; padding: 10px 15px; font-size: 0.75em; line-height: 1.5; }
        .panel-body pre { white-space: pre-wrap; word-wrap: break-word; }

        .scores-panel .panel-body { padding: 0; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 10px 15px; text-align: center; border-bottom: 1px solid #222; }
        th { background: #1a1a1a; color: #00ff00; font-size: 0.85em; }
        td { font-size: 1em; }
        .team-claude { color: #d4a574; }
        .team-gpt { color: #74b9ff; }
        .team-gemini { color: #a29bfe; }
        .total { font-weight: bold; font-size: 1.2em; color: #00ff00; }

        .attack-entry { color: #ff6b6b; padding: 3px 0; border-bottom: 1px solid #1a1a1a; }
        .log-claude { color: #d4a574; }
        .log-gpt { color: #74b9ff; }
        .log-gemini { color: #a29bfe; }
        .log-event { color: #00ff00; }

        .tabs { display: flex; gap: 0; }
        .tab { padding: 8px 15px; cursor: pointer; background: #111; border: 1px solid #333;
               border-bottom: none; color: #888; font-size: 0.8em; }
        .tab.active { background: #1a1a1a; color: #fff; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
    </style>
</head>
<body>
    <div class="header">
        <h1>AttDef - LLM Attack-Defense CTF</h1>
        <div class="meta">
            <span id="tick">Tick: -</span>
            <span id="next-tick">Next tick: -</span>
            <span id="remaining">Game: -</span>
            <span id="status" class="running">-</span>
        </div>
    </div>
    <div class="grid">
        <!-- Top Left: Scoreboard + Attacks -->
        <div class="panel scores-panel">
            <div class="panel-header">Scoreboard</div>
            <div class="panel-body" data-no-scroll="true">
                <table>
                    <thead><tr><th>#</th><th>Team</th><th>ATK</th><th>DEF</th><th>Total</th></tr></thead>
                    <tbody id="scoreboard"></tbody>
                </table>
                <div style="padding: 15px;">
                    <div style="color: #ff6b6b; font-weight: bold; margin-bottom: 8px;">Attack Feed (newest first)</div>
                    <div id="attack-log"></div>
                </div>
            </div>
        </div>

        <!-- Top Right: Game Events -->
        <div class="panel">
            <div class="panel-header"><span>Game Events</span></div>
            <div class="panel-body"><pre id="events" class="log-event"></pre></div>
        </div>

        <!-- Bottom Left: Team Logs (tabbed) -->
        <div class="panel">
            <div class="panel-header">
                <div class="tabs">
                    <div class="tab active log-claude" onclick="switchTab('claude')">Claude</div>
                    <div class="tab log-gpt" onclick="switchTab('gpt')">GPT</div>
                    <div class="tab log-gemini" onclick="switchTab('gemini')">Gemini</div>
                </div>
            </div>
            <div class="panel-body">
                <pre id="log-claude" class="tab-content active log-claude"></pre>
                <pre id="log-gpt" class="tab-content log-gpt"></pre>
                <pre id="log-gemini" class="tab-content log-gemini"></pre>
            </div>
        </div>

        <!-- Bottom Right: Audit / Cheat Detection -->
        <div class="panel">
            <div class="panel-header"><span>Audit / Cheat Detection</span></div>
            <div class="panel-body"><pre id="audit" style="color: #ff6b6b;"></pre></div>
        </div>
    </div>

    <script>
        let activeTab = 'claude';
        function switchTab(team) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById('log-' + team).classList.add('active');
            document.querySelector(`.tab.log-${team}`).classList.add('active');
            activeTab = team;
        }

        async function update() {
            try {
                const [tickR, scoresR, attacksR, claudeR, gptR, geminiR, eventsR, auditR] = await Promise.all([
                    fetch('/api/tick'), fetch('/api/scores'), fetch('/api/attacks'),
                    fetch('/api/logs/claude'), fetch('/api/logs/gpt'), fetch('/api/logs/gemini'),
                    fetch('/api/logs/events'), fetch('/api/logs/audit'),
                ]);
                const tick = await tickR.json();
                const scores = await scoresR.json();
                const attacks = await attacksR.json();

                document.getElementById('tick').textContent = `Tick: ${tick.tick}/${tick.total_ticks}`;
                const m = Math.floor(tick.seconds_remaining / 60), s = tick.seconds_remaining % 60;
                document.getElementById('remaining').textContent = `Game: ${m}m ${String(s).padStart(2,'0')}s`;
                const nt = tick.seconds_to_next_tick || 0;
                const ntm = Math.floor(nt / 60), nts = nt % 60;
                document.getElementById('next-tick').textContent = `Next tick: ${ntm}m ${String(nts).padStart(2,'0')}s`;
                const st = document.getElementById('status');
                st.textContent = tick.game_running ? 'LIVE' : 'ENDED';
                st.className = tick.game_running ? 'running' : 'stopped';

                document.getElementById('scoreboard').innerHTML = scores.map((s, i) =>
                    `<tr><td>${i+1}</td><td class="team-${s.team}">${s.team.toUpperCase()}</td>`
                    + `<td>${s.attack}</td><td>${s.defense}</td><td class="total">${s.total}</td></tr>`
                ).join('');

                document.getElementById('attack-log').innerHTML = attacks.slice(-20).reverse().map(a =>
                    `<div class="attack-entry">[tick ${a.tick}] ${a.attacker} &#8594; ${a.victim} (${a.service})</div>`
                ).join('') || '<div style="color:#555">No attacks yet</div>';

                document.getElementById('log-claude').textContent = await claudeR.text();
                document.getElementById('log-gpt').textContent = await gptR.text();
                document.getElementById('log-gemini').textContent = await geminiR.text();
                // Game events — reverse so newest is on top
                const eventsText = await eventsR.text();
                document.getElementById('events').textContent = eventsText.split('\\n').reverse().join('\\n');

                const auditText = await auditR.text();
                document.getElementById('audit').textContent = auditText
                    ? auditText.split('\\n').reverse().join('\\n')
                    : 'No cheat attempts detected';

                // Only auto-scroll log panels, NOT the scoreboard
                document.querySelectorAll('.panel-body:not([data-no-scroll])').forEach(el => el.scrollTop = el.scrollHeight);
            } catch(e) { console.error(e); }
        }
        update();
        setInterval(update, 3000);
    </script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == "/":
            self._html(DASHBOARD_HTML)
        elif self.path.startswith("/api/logs/"):
            name = self.path.split("/api/logs/")[1]
            if name == "claude":
                self._text(tail_log("claude_*.log", 80))
            elif name == "gpt":
                self._text(tail_log("gpt_*.log", 80))
            elif name == "gemini":
                self._text(tail_log("gemini_*.log", 80))
            elif name == "events":
                # Filter out noisy audit/docker-exec lines from game server's own flag planting
                self._text(tail_log("game_events.log", 60, filter_fn=lambda l: "AUDIT" not in l and "HTTP/1.1" not in l))
            elif name == "audit":
                audit = ""
                for team in ["claude", "gpt", "gemini"]:
                    audit += tail_log(f"audit_{team}.log", 20)
                self._text(audit or "No audit entries")
            else:
                self._json({"error": "unknown log"}, 404)
        elif self.path.startswith("/api/"):
            # Proxy to game server
            data = proxy_game_api(self.path)
            self._raw(data, "application/json")
        else:
            self._json({"error": "not found"}, 404)

    def _html(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(content.encode())

    def _text(self, content):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(content.encode())

    def _json(self, obj, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def _raw(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    print(f"Dashboard running at http://localhost:{PORT}")
    print(f"Reading logs from: {LOG_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
