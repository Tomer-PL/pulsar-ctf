"""Tests for the flag manager module."""

from unittest.mock import patch

from game_server.flag_manager import FlagManager
from game_server.models import (
    Flag,
    FlagSubmission,
    GameConfig,
    GameState,
    ServiceName,
    TeamName,
)


def _make_state() -> GameState:
    config = GameConfig()
    state = GameState(config=config)
    state.initialize()
    return state


class TestFlagGeneration:
    def test_generates_flags_for_all_teams_and_services(self):
        state = _make_state()
        fm = FlagManager(state)
        flags = fm.generate_tick_flags()
        # 2 teams * 3 services = 6 flags
        assert len(flags) == 6

    def test_flags_have_correct_format(self):
        state = _make_state()
        fm = FlagManager(state)
        flags = fm.generate_tick_flags()
        for flag in flags:
            assert flag.value.startswith("FLAG{")
            assert flag.value.endswith("}")
            assert flag.team.value in flag.value
            assert flag.service.value in flag.value

    def test_flags_are_unique(self):
        state = _make_state()
        fm = FlagManager(state)
        flags = fm.generate_tick_flags()
        values = [f.value for f in flags]
        assert len(set(values)) == len(values)


class TestFlagSubmission:
    def test_valid_flag_accepted(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        result = fm.validate_submission(submission)
        assert result is not None
        assert result.attacker == TeamName.CLAUDE
        assert result.victim == TeamName.GPT

    def test_own_flag_rejected(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.CLAUDE, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        result = fm.validate_submission(submission)
        assert result is None

    def test_unknown_flag_rejected(self):
        state = _make_state()
        fm = FlagManager(state)

        submission = FlagSubmission(
            flag_value="FLAG{fake_flag}", submitting_team=TeamName.CLAUDE
        )
        result = fm.validate_submission(submission)
        assert result is None

    def test_expired_flag_rejected(self):
        state = _make_state()
        fm = FlagManager(state)

        # Create a flag from tick 0
        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        # Advance to tick 3 (beyond lifetime of 3)
        state.current_tick = 3

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        result = fm.validate_submission(submission)
        assert result is None

    def test_flag_still_valid_within_lifetime(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        # Tick 2 is still within lifetime (0, 1, 2 = 3 ticks)
        state.current_tick = 2

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        result = fm.validate_submission(submission)
        assert result is not None

    def test_duplicate_submission_rejected(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        # First submission succeeds
        result1 = fm.validate_submission(submission)
        assert result1 is not None

        # Duplicate rejected
        result2 = fm.validate_submission(submission)
        assert result2 is None

    def test_other_team_can_submit_stolen_flag(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        # Claude submits GPT's flag
        sub = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        assert fm.validate_submission(sub) is not None

    def test_submission_tracks_exploited_teams(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        submission = FlagSubmission(
            flag_value=flag.value, submitting_team=TeamName.CLAUDE
        )
        fm.validate_submission(submission)

        assert "gpt" in state.exploited_this_tick["axis"]


class TestFlagExpiry:
    def test_old_flags_removed(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        state.current_tick = 3  # past lifetime
        removed = fm.expire_old_flags()
        assert removed == 1
        assert flag.value not in state.active_flags

    def test_current_flags_kept(self):
        state = _make_state()
        fm = FlagManager(state)

        flag = Flag.generate(TeamName.GPT, ServiceName.AXIS, tick=0)
        state.active_flags[flag.value] = flag

        state.current_tick = 1  # within lifetime
        removed = fm.expire_old_flags()
        assert removed == 0
        assert flag.value in state.active_flags
