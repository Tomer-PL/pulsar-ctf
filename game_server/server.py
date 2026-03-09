"""FastAPI game server for the LLM Attack-Defense CTF."""

import asyncio
import logging
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .audit import start_docker_audit
from .flag_manager import FlagManager
from .models import (
    FlagSubmission,
    GameConfig,
    GameState,
    ServiceName,
    TeamName,
)
from .patch_validator import validate_and_deploy_patch
from .scorer import Scorer

import os as _os
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Console logging
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

# File logging — persistent game event log
_os.makedirs("/app/logs", exist_ok=True)
_file_handler = logging.FileHandler("/app/logs/game_events.log")
_file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
_file_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(_file_handler)

logger = logging.getLogger(__name__)

# Port mapping: team -> service -> host port
# LLMs connect to localhost:<host_port>
HOST_PORTS = {
    "claude": {"axis": 14000, "ico": 14265, "nilua": 18080},
    "gpt": {"axis": 24000, "ico": 24265, "nilua": 28080},
    "gemini": {"axis": 34000, "ico": 34265, "nilua": 38080},
}

# --- Game initialization ---
config = GameConfig()
state = GameState(config=config)
flag_manager = FlagManager(state)
scorer = Scorer(state)

app = FastAPI(title="AttDef - LLM Attack-Defense CTF", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic request/response models ---

class FlagSubmitRequest(BaseModel):
    flag: str
    team: str


class FlagSubmitResponse(BaseModel):
    accepted: bool
    message: str


class PatchRequest(BaseModel):
    team: str
    service: str
    build_context: str  # path to the directory with the patched Dockerfile


class PatchResponse(BaseModel):
    accepted: bool
    message: str


class TickInfo(BaseModel):
    tick: int
    total_ticks: int
    seconds_remaining: int
    seconds_to_next_tick: int
    game_running: bool


# --- Tick loop ---

async def tick_loop() -> None:
    """Main game loop that runs every tick_duration_seconds."""
    state.initialize()
    logger.info(
        "GAME_START total_ticks=%d tick_duration=%ds game_duration=%ds",
        config.total_ticks,
        config.tick_duration_seconds,
        config.game_duration_seconds,
    )
    logger.info("HOST_PORTS %s", HOST_PORTS)

    # Plant initial flags (tick 0)
    flags = flag_manager.generate_tick_flags()
    try:
        flag_manager.plant_flags(flags)
    except Exception as e:
        logger.error("FLAG_PLANT_CRASH tick=0 error=%s", e)
    logger.info("TICK_START tick=0")

    while state.running and state.current_tick < config.total_ticks:
        await asyncio.sleep(config.tick_duration_seconds)

        # Score the completed tick
        tick_scores = scorer.calculate_tick_scores()
        board = scorer.get_scoreboard()

        logger.info(
            "TICK_END tick=%d scores=%s",
            state.current_tick,
            {t: f"atk={s['attack']},def={s['defense']}" for t, s in tick_scores.items()},
        )
        logger.info(
            "SCOREBOARD tick=%d %s",
            state.current_tick,
            " | ".join(f"{e['team']}:{e['total']}(a={e['attack']},d={e['defense']})" for e in board),
        )

        # Advance tick
        state.current_tick += 1
        scorer.reset_tick_tracking()

        # Expire old flags and plant new ones
        flag_manager.expire_old_flags()
        flags = flag_manager.generate_tick_flags()
        try:
            flag_manager.plant_flags(flags)
        except Exception as e:
            logger.error("FLAG_PLANT_CRASH tick=%d error=%s", state.current_tick, e)
        logger.info("TICK_START tick=%d", state.current_tick)

    state.running = False
    logger.info("GAME_OVER")
    for entry in scorer.get_scoreboard():
        logger.info(
            "FINAL_SCORE team=%s total=%d attack=%d defense=%d",
            entry["team"], entry["total"], entry["attack"], entry["defense"],
        )


@app.on_event("startup")
async def startup() -> None:
    """Start the tick loop and audit monitor when the server starts."""
    start_docker_audit()
    asyncio.create_task(tick_loop())


# --- API endpoints ---

@app.post("/api/flags/submit", response_model=FlagSubmitResponse)
async def submit_flag(req: FlagSubmitRequest) -> FlagSubmitResponse:
    """Submit a captured flag."""
    if not state.running:
        raise HTTPException(status_code=400, detail="Game is not running")

    try:
        team = TeamName(req.team)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown team: {req.team}. Valid: {[t.value for t in TeamName]}",
        )

    submission = FlagSubmission(flag_value=req.flag, submitting_team=team)
    result = flag_manager.validate_submission(submission)

    if result:
        return FlagSubmitResponse(
            accepted=True,
            message=f"Flag accepted! Stole from {result.victim.value}/{result.service.value}",
        )
    return FlagSubmitResponse(accepted=False, message="Flag rejected (invalid, expired, duplicate, or own flag)")


@app.post("/api/patch/submit", response_model=PatchResponse)
async def submit_patch(req: PatchRequest) -> PatchResponse:
    """Submit a patched service for validation and deployment."""
    if not state.running:
        raise HTTPException(status_code=400, detail="Game is not running")

    try:
        team = TeamName(req.team)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown team: {req.team}. Valid: {[t.value for t in TeamName]}",
        )

    try:
        service = ServiceName(req.service)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown service: {req.service}. Valid: {[s.value for s in ServiceName]}",
        )

    # Remap host paths to container paths
    # LLMs send paths like /usr/local/workspace/AttDef/challenges-source/axis
    # but inside this container, source is at /app/challenges-source/axis
    build_context = req.build_context
    if "/challenges-source/" in build_context:
        service_dir = build_context.split("/challenges-source/")[-1]
        build_context = f"/app/challenges-source/{service_dir}"
    logger.info("PATCH_REQUEST team=%s service=%s path=%s", team.value, service.value, build_context)

    # Run validation in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    success, message = await loop.run_in_executor(
        None, validate_and_deploy_patch, team, service, build_context
    )

    logger.info(
        "PATCH %s/%s: %s - %s",
        team.value, service.value,
        "ACCEPTED" if success else "REJECTED",
        message,
    )
    return PatchResponse(accepted=success, message=message)


@app.get("/api/tick", response_model=TickInfo)
async def get_tick() -> TickInfo:
    """Get current tick information."""
    elapsed = time.time() - state.start_time if state.start_time else 0
    remaining = max(0, config.game_duration_seconds - int(elapsed))
    time_in_current_tick = elapsed - (state.current_tick * config.tick_duration_seconds)
    seconds_to_next = max(0, config.tick_duration_seconds - int(time_in_current_tick))
    return TickInfo(
        tick=state.current_tick,
        total_ticks=config.total_ticks,
        seconds_remaining=remaining,
        seconds_to_next_tick=seconds_to_next,
        game_running=state.running,
    )


@app.get("/api/scores")
async def get_scores() -> list[dict]:
    """Get current scoreboard."""
    return scorer.get_scoreboard()


@app.get("/api/scores/{team_name}")
async def get_team_score(team_name: str) -> dict:
    """Get score for a specific team."""
    try:
        team = TeamName(team_name)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown team: {team_name}")

    score = state.scores.get(team.value)
    if not score:
        raise HTTPException(status_code=404, detail="Team not found in scores")

    return {
        "team": score.team.value,
        "attack": score.attack_points,
        "defense": score.defense_points,
        "total": score.total,
    }


@app.get("/api/attacks")
async def get_attacks(tick: int | None = None) -> list[dict]:
    """Get attack log, optionally filtered by tick."""
    attacks = state.attack_log
    if tick is not None:
        attacks = [a for a in attacks if a.tick == tick]
    return [
        {
            "attacker": a.attacker.value,
            "victim": a.victim.value,
            "service": a.service.value,
            "tick": a.tick,
            "timestamp": a.timestamp,
        }
        for a in attacks
    ]


@app.get("/api/game/config")
async def get_game_config() -> dict:
    """Get game configuration (for LLM harnesses to read)."""
    return {
        "tick_duration_seconds": config.tick_duration_seconds,
        "game_duration_seconds": config.game_duration_seconds,
        "flag_lifetime_ticks": config.flag_lifetime_ticks,
        "total_ticks": config.total_ticks,
        "flag_format": "FLAG{<team>_<service>_<tick>_<hex>}",
        "services": [s.value for s in config.services],
        "teams": [t.value for t in config.teams],
        "host_ports": HOST_PORTS,
        "submission_endpoint": "POST /api/flags/submit {flag: str, team: str}",
        "patch_endpoint": "POST /api/patch/submit {team: str, service: str, build_context: str}",
    }


@app.get("/", response_class=HTMLResponse)
async def scoreboard_page() -> str:
    """Live scoreboard HTML page."""
    return """<!DOCTYPE html>
<html>
<head>
    <title>AttDef - LLM Attack-Defense CTF</title>
    <style>
        body { font-family: monospace; background: #0a0a0a; color: #00ff00; padding: 40px; }
        h1 { text-align: center; font-size: 2em; }
        .info { text-align: center; margin: 20px 0; color: #888; }
        table { width: 100%; max-width: 800px; margin: 30px auto; border-collapse: collapse; }
        th, td { padding: 12px 20px; text-align: center; border: 1px solid #333; }
        th { background: #1a1a1a; color: #00ff00; }
        td { font-size: 1.2em; }
        .team-claude { color: #d4a574; }
        .team-gpt { color: #74b9ff; }
        .team-gemini { color: #a29bfe; }
        .total { font-weight: bold; font-size: 1.4em; }
        #attacks { max-width: 800px; margin: 30px auto; }
        .attack-entry { color: #ff6b6b; margin: 4px 0; }
    </style>
</head>
<body>
    <h1>AttDef - LLM Attack-Defense CTF</h1>
    <div class="info">
        <span id="tick">Tick: -</span> |
        <span id="remaining">Time: -</span> |
        <span id="status">Status: -</span>
    </div>
    <table>
        <thead><tr><th>Rank</th><th>Team</th><th>Attack</th><th>Defense</th><th>Total</th></tr></thead>
        <tbody id="scoreboard"></tbody>
    </table>
    <div id="attacks"><h3>Recent Attacks</h3><div id="attack-log"></div></div>
    <script>
        async function update() {
            try {
                const [tickRes, scoresRes, attacksRes] = await Promise.all([
                    fetch('/api/tick'), fetch('/api/scores'), fetch('/api/attacks')
                ]);
                const tick = await tickRes.json();
                const scores = await scoresRes.json();
                const attacks = await attacksRes.json();

                document.getElementById('tick').textContent = `Tick: ${tick.tick}/${tick.total_ticks}`;
                const mins = Math.floor(tick.seconds_remaining / 60);
                const secs = tick.seconds_remaining % 60;
                document.getElementById('remaining').textContent = `Time: ${mins}m ${secs}s`;
                document.getElementById('status').textContent = `Status: ${tick.game_running ? 'RUNNING' : 'STOPPED'}`;

                const tbody = document.getElementById('scoreboard');
                tbody.innerHTML = scores.map((s, i) =>
                    `<tr><td>${i+1}</td><td class="team-${s.team}">${s.team.toUpperCase()}</td>`
                    + `<td>${s.attack}</td><td>${s.defense}</td>`
                    + `<td class="total">${s.total}</td></tr>`
                ).join('');

                const recent = attacks.slice(-10).reverse();
                document.getElementById('attack-log').innerHTML = recent.map(a =>
                    `<div class="attack-entry">[tick ${a.tick}] ${a.attacker} -> ${a.victim} (${a.service})</div>`
                ).join('');
            } catch(e) { console.error(e); }
        }
        update();
        setInterval(update, 3000);
    </script>
</body>
</html>"""
