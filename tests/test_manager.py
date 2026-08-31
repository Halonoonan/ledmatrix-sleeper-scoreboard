import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class BasePlugin:
    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        self.plugin_id, self.config = plugin_id, config
        self.display_manager, self.cache_manager, self.plugin_manager = display_manager, cache_manager, plugin_manager
        self.logger = logging.getLogger("test")

    def validate_config(self):
        return True

    def get_info(self):
        return {}

    def cleanup(self):
        pass


base_module = types.ModuleType("src.plugin_system.base_plugin")
base_module.BasePlugin = BasePlugin
sys.modules.update({
    "src": types.ModuleType("src"),
    "src.plugin_system": types.ModuleType("src.plugin_system"),
    "src.plugin_system.base_plugin": base_module,
})
path = Path(__file__).parents[1] / "manager.py"
spec = importlib.util.spec_from_file_location("sleeper_manager", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Display:
    width, height = 96, 48
    def __init__(self): self.calls = []
    def clear(self): self.calls.append(("clear",))
    def draw_text(self, text, **kwargs): self.calls.append(("text", text, kwargs))
    def update_display(self): self.calls.append(("update",))


class PluginManager:
    font_manager = None


class PluginTests(unittest.TestCase):
    def make(self, **config):
        values = {"league_id": "123", **config}
        return module.SleeperScoreboardPlugin("sleeper", values, Display(), None, PluginManager())

    def test_matchups_names_projections_bye_and_standings(self):
        plugin = self.make(name_max_length=8)
        users = {"u1": {"display_name": "Alpha Wolves", "avatar": "abc"}, "u2": {"display_name": "Beta"}}
        rosters = [
            {"roster_id": 1, "owner_id": "u1", "settings": {"wins": 2, "losses": 1, "fpts": 100}},
            {"roster_id": 2, "owner_id": "u2", "settings": {"wins": 3, "losses": 0, "fpts": 90}},
        ]
        teams = {r["roster_id"]: plugin._team(r, users) for r in rosters}
        matchups = plugin._build_matchups([
            {"matchup_id": 1, "roster_id": 1, "points": 12.34, "projected_points": 99},
            {"matchup_id": 2, "roster_id": 2, "points": 4},
        ], teams)
        self.assertEqual(matchups[0]["teams"][0]["name"], "AW")
        self.assertEqual(matchups[0]["teams"][0]["projected"], 99)
        self.assertEqual(matchups[0]["teams"][1]["name"], "BYE")
        self.assertEqual(plugin._build_standings(rosters, teams)[0]["name"], "BETA")

    def test_fetch_is_atomic_and_update_throttles_failures(self):
        plugin = self.make(update_interval=60)
        plugin.matchups = [{"old": True}]
        with patch.object(plugin, "_get_json", side_effect=[{"week": 4}, [], RuntimeError("boom")]):
            with self.assertRaises(RuntimeError):
                plugin._fetch_data()
        self.assertEqual(plugin.matchups, [{"old": True}])
        with patch.object(plugin, "_fetch_data", side_effect=module.URLError("offline")) as fetch:
            plugin.update(); plugin.update()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(plugin.error_message, "OFFLINE")

    def test_display_matchup_standings_and_idle(self):
        plugin = self.make()
        plugin.matchups = [{"teams": [
            {"name": "A", "points": 1, "projected": None},
            {"name": "B", "points": 2, "projected": None},
        ]}]
        plugin.nfl_state = {"season_type": "regular"}
        plugin.display()
        self.assertTrue(any(call[:2] == ("text", "1.0") for call in plugin.display_manager.calls))
        plugin.display_manager.calls.clear(); plugin.matchups = []
        plugin.standings = [{"name": "A", "wins": 1, "losses": 0, "ties": 0, "points": 10}]
        plugin.display()
        self.assertTrue(any("STANDINGS" in call[1] for call in plugin.display_manager.calls if call[0] == "text"))
        plugin.display_manager.calls.clear(); plugin.standings = []
        plugin.display()
        self.assertTrue(any(call[:2] == ("text", "NO MATCHUPS") for call in plugin.display_manager.calls))


if __name__ == "__main__":
    unittest.main()
