"""Scoring engine for the Pulsar game."""

import logging

from .models import GameState

logger = logging.getLogger(__name__)


class Scorer:
    """Calculates attack and defense scores each tick.

    Scoring (matches DEF CON CTF Finals):
    - Attack: +1 per unique flag stolen from another team
    - Defense: +1 per service where your team was NOT exploited,
      but only if at least one other team WAS exploited on that service
    """

    def __init__(self, state: GameState):
        self.state = state

    def calculate_tick_scores(self) -> dict[str, dict[str, int]]:
        """Calculate and apply scores for the current tick.

        Returns a dict of team -> {attack: N, defense: N} for this tick.
        """
        tick_scores: dict[str, dict[str, int]] = {}
        current_tick = self.state.current_tick

        for team in self.state.config.teams:
            tick_scores[team.value] = {"attack": 0, "defense": 0}

        # Attack points: count flags stolen this tick
        for attack in self.state.attack_log:
            if attack.tick == current_tick:
                tick_scores[attack.attacker.value]["attack"] += 1

        # Defense points: for each service, if at least one team was exploited,
        # teams that were NOT exploited get a defense point
        for service in self.state.config.services:
            exploited_teams = self.state.exploited_this_tick.get(service.value, set())
            if not exploited_teams:
                # No one was exploited on this service — no defense points awarded
                continue

            for team in self.state.config.teams:
                if team.value not in exploited_teams:
                    tick_scores[team.value]["defense"] += 1
                    logger.info(
                        "DEFENSE: %s defended %s (tick %d)",
                        team.value,
                        service.value,
                        current_tick,
                    )

        # Apply to cumulative scores
        for team_name, points in tick_scores.items():
            self.state.scores[team_name].attack_points += points["attack"]
            self.state.scores[team_name].defense_points += points["defense"]

        return tick_scores

    def get_scoreboard(self) -> list[dict]:
        """Return sorted scoreboard data."""
        board = []
        for team_name, score in self.state.scores.items():
            board.append(
                {
                    "team": team_name,
                    "attack": score.attack_points,
                    "defense": score.defense_points,
                    "total": score.total,
                }
            )
        board.sort(key=lambda x: x["total"], reverse=True)
        return board

    def reset_tick_tracking(self) -> None:
        """Reset per-tick exploit tracking for the new tick."""
        self.state.exploited_this_tick = {
            service.value: set() for service in self.state.config.services
        }
