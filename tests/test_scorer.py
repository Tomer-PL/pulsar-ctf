"""Tests for the scoring engine."""

from game_server.models import (
    AttackPoint,
    GameConfig,
    GameState,
    ServiceName,
    TeamName,
)
from game_server.scorer import Scorer


def _make_state() -> GameState:
    config = GameConfig()
    state = GameState(config=config)
    state.initialize()
    return state


class TestAttackScoring:
    def test_attack_points_counted(self):
        state = _make_state()
        scorer = Scorer(state)

        # Claude steals from GPT on tick 0
        state.attack_log.append(
            AttackPoint(
                attacker=TeamName.CLAUDE,
                victim=TeamName.GPT,
                service=ServiceName.AXIS,
                tick=0,
                flag_value="FLAG{test}",
            )
        )

        scores = scorer.calculate_tick_scores()
        assert scores["claude"]["attack"] == 1
        assert scores["gpt"]["attack"] == 0

    def test_multiple_attacks_same_tick(self):
        state = _make_state()
        scorer = Scorer(state)

        # Claude steals two flags from different teams
        state.attack_log.append(
            AttackPoint(
                attacker=TeamName.CLAUDE,
                victim=TeamName.GPT,
                service=ServiceName.AXIS,
                tick=0,
                flag_value="FLAG{1}",
            )
        )
        state.attack_log.append(
            AttackPoint(
                attacker=TeamName.CLAUDE,
                victim=TeamName.GEMINI,
                service=ServiceName.ICO,
                tick=0,
                flag_value="FLAG{2}",
            )
        )

        scores = scorer.calculate_tick_scores()
        assert scores["claude"]["attack"] == 2


class TestDefenseScoring:
    def test_defense_point_when_others_exploited(self):
        state = _make_state()
        scorer = Scorer(state)

        # GPT was exploited on axis, but Claude and Gemini were not
        state.exploited_this_tick["axis"] = {"gpt"}

        scores = scorer.calculate_tick_scores()
        assert scores["claude"]["defense"] == 1
        assert scores["gemini"]["defense"] == 1
        assert scores["gpt"]["defense"] == 0

    def test_no_defense_points_when_nobody_exploited(self):
        state = _make_state()
        scorer = Scorer(state)

        # No one was exploited on any service
        scores = scorer.calculate_tick_scores()
        for team_scores in scores.values():
            assert team_scores["defense"] == 0

    def test_no_defense_points_when_all_exploited(self):
        state = _make_state()
        scorer = Scorer(state)

        # Everyone was exploited on axis
        state.exploited_this_tick["axis"] = {"claude", "gpt", "gemini"}

        scores = scorer.calculate_tick_scores()
        for team_scores in scores.values():
            assert team_scores["defense"] == 0


class TestCumulativeScoring:
    def test_scores_accumulate_across_ticks(self):
        state = _make_state()
        scorer = Scorer(state)

        # Tick 0: Claude steals from GPT
        state.attack_log.append(
            AttackPoint(
                attacker=TeamName.CLAUDE,
                victim=TeamName.GPT,
                service=ServiceName.AXIS,
                tick=0,
                flag_value="FLAG{1}",
            )
        )
        state.exploited_this_tick["axis"] = {"gpt"}
        scorer.calculate_tick_scores()

        # Tick 1
        state.current_tick = 1
        scorer.reset_tick_tracking()
        state.attack_log.append(
            AttackPoint(
                attacker=TeamName.CLAUDE,
                victim=TeamName.GEMINI,
                service=ServiceName.ICO,
                tick=1,
                flag_value="FLAG{2}",
            )
        )
        state.exploited_this_tick["ico"] = {"gemini"}
        scorer.calculate_tick_scores()

        assert state.scores["claude"].attack_points == 2
        assert state.scores["claude"].defense_points == 2  # defended axis+ico both ticks


class TestScoreboard:
    def test_sorted_by_total_descending(self):
        state = _make_state()
        scorer = Scorer(state)

        state.scores["claude"].attack_points = 5
        state.scores["gpt"].attack_points = 10
        state.scores["gemini"].attack_points = 3

        board = scorer.get_scoreboard()
        assert board[0]["team"] == "gpt"
        assert board[1]["team"] == "claude"
        assert board[2]["team"] == "gemini"

    def test_total_is_sum_of_attack_and_defense(self):
        state = _make_state()
        scorer = Scorer(state)

        state.scores["claude"].attack_points = 5
        state.scores["claude"].defense_points = 3

        board = scorer.get_scoreboard()
        claude_entry = next(e for e in board if e["team"] == "claude")
        assert claude_entry["total"] == 8


class TestResetTickTracking:
    def test_clears_exploited_tracking(self):
        state = _make_state()
        scorer = Scorer(state)

        state.exploited_this_tick["axis"] = {"gpt", "gemini"}
        scorer.reset_tick_tracking()

        for service_exploits in state.exploited_this_tick.values():
            assert len(service_exploits) == 0
