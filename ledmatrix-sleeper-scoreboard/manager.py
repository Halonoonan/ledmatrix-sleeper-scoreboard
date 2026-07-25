"""
Sleeper Fantasy Scoreboard plugin for ChuckBuilds LEDMatrix.

Displays every matchup in a Sleeper fantasy football league and refreshes
scores throughout the fantasy week. Uses Sleeper's public read-only API.
"""

from collections import defaultdict
from datetime import datetime
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.plugin_system.base_plugin import BasePlugin

try:
    import freetype
except ImportError:
    freetype = None


SLEEPER_API = "https://api.sleeper.app/v1"
USER_AGENT = "LEDMatrix-Sleeper-Scoreboard/1.0"


class SleeperScoreboardPlugin(BasePlugin):
    """Cycle through all Sleeper matchups for a configured league."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)

        self.league_id = str(config.get("league_id", "1386603818250158080")).strip()
        self.configured_week = int(config.get("week", 0))
        self.matchup_display_seconds = float(config.get("matchup_display_seconds", 7))
        self.update_interval = int(config.get("update_interval", 60))
        self.show_week_header = bool(config.get("show_week_header", True))
        self.show_matchup_number = bool(config.get("show_matchup_number", True))
        self.name_max_length = int(config.get("name_max_length", 16))

        self.header_color = tuple(config.get("header_color", [255, 215, 0]))
        self.team_color = tuple(config.get("team_color", [255, 255, 255]))
        self.score_color = tuple(config.get("score_color", [0, 255, 255]))

        self.current_week = self.configured_week or 1
        self.matchups = []
        self.last_update = 0.0
        self.rotation_started = time.monotonic()
        self.error_message = ""
        self._load_fallback_font()
        self._register_fonts()

        self.logger.info(
            "Sleeper Scoreboard initialized for league %s", self.league_id
        )

    def _register_fonts(self):
        """Register plugin fonts with the LEDMatrix font manager."""
        try:
            font_manager = getattr(self.plugin_manager, "font_manager", None)
            if font_manager is None:
                return

            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.header",
                family="press_start",
                size_px=7,
                color=self.header_color,
            )
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.team",
                family="press_start",
                size_px=8,
                color=self.team_color,
            )
            font_manager.register_manager_font(
                manager_id=self.plugin_id,
                element_key=f"{self.plugin_id}.score",
                family="press_start",
                size_px=9,
                color=self.score_color,
            )
        except Exception as exc:
            self.logger.warning("Could not register Sleeper fonts: %s", exc)

    def _load_fallback_font(self):
        self.bdf_font = None
        if freetype is None:
            return
        for path in ("assets/fonts/6x9.bdf", "assets/fonts/5x7.bdf"):
            if os.path.exists(path):
                try:
                    self.bdf_font = freetype.Face(path)
                    return
                except Exception:
                    pass

    @staticmethod
    def _get_json(path):
        request = Request(
            f"{SLEEPER_API}{path}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_week(self):
        if self.configured_week > 0:
            return self.configured_week
        state = self._get_json("/state/nfl")
        week = int(state.get("week") or 1)
        return max(1, week)

    def _team_name(self, roster, users_by_id):
        metadata = roster.get("metadata") or {}
        owner_id = roster.get("owner_id")
        user = users_by_id.get(owner_id, {})
        user_metadata = user.get("metadata") or {}

        candidates = (
            metadata.get("team_name"),
            user_metadata.get("team_name"),
            user.get("display_name"),
            f"Roster {roster.get('roster_id', '?')}",
        )
        name = next((str(value).strip() for value in candidates if value), "Unknown")
        if len(name) > self.name_max_length:
            return name[: max(1, self.name_max_length - 1)] + "…"
        return name

    def _fetch_matchups(self):
        week = self._resolve_week()
        users = self._get_json(f"/league/{self.league_id}/users")
        rosters = self._get_json(f"/league/{self.league_id}/rosters")
        matchup_rows = self._get_json(f"/league/{self.league_id}/matchups/{week}")

        users_by_id = {user.get("user_id"): user for user in users}
        rosters_by_id = {int(roster["roster_id"]): roster for roster in rosters}
        teams_by_roster = {
            roster_id: self._team_name(roster, users_by_id)
            for roster_id, roster in rosters_by_id.items()
        }

        grouped = defaultdict(list)
        for row in matchup_rows:
            matchup_id = row.get("matchup_id")
            if matchup_id is None:
                continue
            roster_id = int(row.get("roster_id"))
            points = float(row.get("points") or 0.0)
            grouped[int(matchup_id)].append(
                {
                    "roster_id": roster_id,
                    "name": teams_by_roster.get(roster_id, f"Roster {roster_id}"),
                    "points": points,
                }
            )

        matchups = []
        for matchup_id in sorted(grouped):
            teams = sorted(grouped[matchup_id], key=lambda item: item["roster_id"])
            if len(teams) == 1:
                teams.append({"roster_id": 0, "name": "BYE", "points": 0.0})
            elif len(teams) > 2:
                teams = teams[:2]
            matchups.append({"matchup_id": matchup_id, "teams": teams})

        self.current_week = week
        self.matchups = matchups
        self.last_update = time.time()
        self.error_message = ""
        self.rotation_started = time.monotonic()

    def update(self):
        """Refresh scores when the configured interval has elapsed."""
        if self.last_update and time.time() - self.last_update < self.update_interval:
            return
        try:
            self._fetch_matchups()
            self.logger.info(
                "Loaded %d Sleeper matchups for week %d",
                len(self.matchups),
                self.current_week,
            )
        except HTTPError as exc:
            self.error_message = f"Sleeper HTTP {exc.code}"
            self.logger.error("Sleeper API HTTP error: %s", exc)
        except URLError as exc:
            self.error_message = "Sleeper offline"
            self.logger.error("Sleeper API network error: %s", exc)
        except Exception as exc:
            self.error_message = "Sleeper error"
            self.logger.error("Error loading Sleeper matchups: %s", exc, exc_info=True)
        finally:
            # Prevent a failed request from retrying every display frame.
            if not self.last_update:
                self.last_update = time.time()

    def _font(self, key):
        try:
            font_manager = getattr(self.plugin_manager, "font_manager", None)
            if font_manager:
                return font_manager.get_font(f"{self.plugin_id}.{key}")
        except Exception:
            pass
        return self.bdf_font

    def _draw_centered(self, text, y, font_key, color):
        self.display_manager.draw_text(
            str(text),
            x=self.display_manager.width // 2,
            y=int(y),
            font=self._font(font_key),
            color=color,
        )

    def display(self, force_clear=False):
        """Draw the current matchup."""
        try:
            self.display_manager.clear()

            width = self.display_manager.width
            height = self.display_manager.height

            if self.error_message and not self.matchups:
                self._draw_centered("SLEEPER", height * 0.35, "header", self.header_color)
                self._draw_centered(self.error_message, height * 0.65, "team", (255, 80, 80))
                self.display_manager.update_display()
                return

            if not self.matchups:
                self._draw_centered("SLEEPER", height * 0.35, "header", self.header_color)
                self._draw_centered("NO MATCHUPS", height * 0.65, "team", self.team_color)
                self.display_manager.update_display()
                return

            elapsed = max(0.0, time.monotonic() - self.rotation_started)
            index = int(elapsed / self.matchup_display_seconds) % len(self.matchups)
            matchup = self.matchups[index]
            team_a, team_b = matchup["teams"]

            header_parts = []
            if self.show_week_header:
                header_parts.append(f"WEEK {self.current_week}")
            if self.show_matchup_number:
                header_parts.append(f"{index + 1}/{len(self.matchups)}")
            header = "  ".join(header_parts) or "SLEEPER"

            self._draw_centered(header, max(5, height * 0.13), "header", self.header_color)

            # The layout is optimized for 96x48 and scales proportionally.
            self._draw_centered(team_a["name"], height * 0.36, "team", self.team_color)
            self._draw_centered(f"{team_a['points']:.2f}", height * 0.53, "score", self.score_color)
            self._draw_centered(
                f"{team_b['points']:.2f}", height * 0.72, "score", self.score_color
            )
            self._draw_centered(team_b["name"], height * 0.90, "team", self.team_color)

            self.display_manager.update_display()
        except Exception as exc:
            self.logger.error("Sleeper display error: %s", exc, exc_info=True)

    def validate_config(self):
        if not super().validate_config():
            return False
        if not self.league_id.isdigit():
            self.logger.error("league_id must contain only digits")
            return False
        if self.matchup_display_seconds < 2:
            self.logger.error("matchup_display_seconds must be at least 2")
            return False
        if self.update_interval < 15:
            self.logger.error("update_interval must be at least 15 seconds")
            return False
        return True

    def get_info(self):
        info = super().get_info()
        info.update(
            {
                "league_id": self.league_id,
                "week": self.current_week,
                "matchup_count": len(self.matchups),
                "last_update": self.last_update,
                "error": self.error_message,
            }
        )
        return info

    def cleanup(self):
        self.logger.info("Cleaning up Sleeper Scoreboard plugin")
        super().cleanup()
