"""Sleeper Fantasy Football scoreboard V2 for ChuckBuilds LEDMatrix."""

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.plugin_system.base_plugin import BasePlugin

try:
    import freetype
except ImportError:  # depends on the Pi image
    freetype = None

SLEEPER_API = "https://api.sleeper.app/v1"
USER_AGENT = "LEDMatrix-Sleeper-Scoreboard/2.0"
DEFAULT_LEAGUE_IDS = ("1386603818250158080", "1393309596713517056")


class SleeperScoreboardPlugin(BasePlugin):
    """Cycle through league matchup or idle/standings cards."""

    def __init__(self, plugin_id, config, display_manager, cache_manager, plugin_manager):
        super().__init__(plugin_id, config, display_manager, cache_manager, plugin_manager)
        self.league_id = str(config.get("league_id", DEFAULT_LEAGUE_IDS[0])).strip()
        configured_ids = config.get("league_ids")
        has_explicit_league_ids = isinstance(configured_ids, (list, tuple)) and bool(configured_ids)
        if not has_explicit_league_ids:
            configured_ids = DEFAULT_LEAGUE_IDS
        self.league_ids = []
        for value in configured_ids:
            league_id = str(value).strip()
            if league_id and league_id not in self.league_ids:
                self.league_ids.append(league_id)
        if not has_explicit_league_ids and self.league_id not in self.league_ids:
            self.league_ids.insert(0, self.league_id)
        self.configured_week = self._integer(config.get("week", 0), 0)
        self.matchup_display_seconds = self._number(config.get("matchup_display_seconds", 8), 8)
        self.update_interval = self._integer(config.get("update_interval", 60), 60)
        self.show_week_header = self._boolean(config.get("show_week_header", True))
        self.show_matchup_number = self._boolean(config.get("show_matchup_number", True))
        self.show_projected_points = self._boolean(config.get("show_projected_points", False))
        self.show_standings_when_idle = self._boolean(config.get("show_standings_when_idle", True))
        self.show_countdown = self._boolean(config.get("show_countdown", True))
        self.standings_rows = self._integer(config.get("standings_rows", 3), 3)
        self.name_max_length = self._integer(config.get("name_max_length", 12), 12)
        # Retained for compatibility with early V2 configs. The one-frame-per-
        # second display loop cannot render fades smoothly, so V2.0.1 keeps the
        # screen at constant brightness.
        self.transition_seconds = self._number(config.get("transition_seconds", 0), 0)
        self.header_color = self._color(config.get("header_color"), (255, 215, 0))
        self.team_color = self._color(config.get("team_color"), (255, 255, 255))
        self.score_color = self._color(config.get("score_color"), (0, 255, 255))
        self.projection_color = self._color(config.get("projection_color"), (120, 160, 255))
        self.accent_color = self._color(config.get("accent_color"), (255, 96, 32))

        self.current_week = self.configured_week or 1
        self.matchups, self.standings, self.standing_pages, self.nfl_state = [], [], [], {}
        self.league_errors = {}
        self.last_update = self.last_attempt = 0.0
        self.rotation_started = time.monotonic()
        self.error_message = ""
        self.frame_brightness = 1.0
        self.last_frame_key = None
        self.last_display_at = 0.0
        self.fonts = {}
        self._load_bdf_fonts()
        self._register_fonts()
        self.logger.info("Sleeper Scoreboard V2 initialized for leagues %s", ", ".join(self.league_ids))

    @staticmethod
    def _boolean(value):
        return value.strip().lower() in ("1", "true", "yes", "on") if isinstance(value, str) else bool(value)

    @staticmethod
    def _integer(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _number(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _color(value, default):
        try:
            color = tuple(max(0, min(255, int(part))) for part in value)
            return color if len(color) == 3 else default
        except (TypeError, ValueError):
            return default

    def _register_fonts(self):
        font_manager = getattr(self.plugin_manager, "font_manager", None)
        if font_manager is None:
            return
        definitions = (
            ("header", 5, self.header_color), ("team", 10, self.team_color),
            ("score", 14, self.score_color), ("small", 6, self.projection_color),
        )
        for key, size, color in definitions:
            try:
                font_manager.register_manager_font(
                    manager_id=self.plugin_id, element_key=f"{self.plugin_id}.{key}",
                    family="press_start", size_px=size, color=color,
                )
            except Exception as exc:
                self.logger.warning("Could not register Sleeper %s font: %s", key, exc)

    def _load_bdf_fonts(self):
        if freetype is None:
            return
        choices = {
            "header": ("5x7.bdf", "4x6.bdf", "6x9.bdf"),
            "team": ("8x13B.bdf", "7x14B.bdf", "6x13B.bdf"),
            "score": ("10x20.bdf", "9x18B.bdf", "8x13B.bdf"),
            "small": ("5x7.bdf", "4x6.bdf", "6x9.bdf"),
        }
        for key, filenames in choices.items():
            for root in ("assets/fonts", "rpi-rgb-led-matrix-master/fonts"):
                for filename in filenames:
                    path = os.path.join(root, filename)
                    if os.path.exists(path):
                        try:
                            self.fonts[key] = freetype.Face(path)
                            break
                        except Exception:
                            pass
                if key in self.fonts:
                    break

    @staticmethod
    def _get_json(path):
        request = Request(f"{SLEEPER_API}{path}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=12) as response:
            return json.loads(response.read().decode("utf-8"))

    def _resolve_week(self, state):
        if self.configured_week > 0:
            return self.configured_week
        return max(1, min(25, self._integer(state.get("week") or state.get("display_week"), 1)))

    def _fit_name(self, name):
        clean = " ".join(str(name).replace("…", "").split())
        if len(clean) <= self.name_max_length:
            return clean.upper()
        initials = "".join(word[0] for word in clean.split() if word)
        return (initials if 1 < len(initials) <= self.name_max_length else clean[:self.name_max_length]).upper()

    @staticmethod
    def _league_label(name, league_id):
        clean = " ".join(str(name or "").split())
        words = [word for word in clean.split() if word]
        initials = "".join(word[0] for word in words)
        if 1 < len(initials) <= 6:
            return initials.upper()
        return (clean[:6] if clean else f"L{league_id[-3:]}").upper()

    def _team(self, roster, users_by_id):
        metadata = roster.get("metadata") or {}
        user = users_by_id.get(roster.get("owner_id"), {})
        user_metadata = user.get("metadata") or {}
        candidates = (metadata.get("team_name"), user_metadata.get("team_name"), user.get("display_name"), f"Roster {roster.get('roster_id', '?')}")
        name = next((str(value).strip() for value in candidates if value), "Unknown")
        return {"roster_id": self._integer(roster.get("roster_id"), 0), "name": self._fit_name(name),
                "avatar": user.get("avatar") or metadata.get("avatar")}

    @staticmethod
    def _projection(row):
        for key in ("projected_points", "projection", "projected"):
            value = row.get(key)
            if isinstance(value, dict):
                value = value.get("points")
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    def _build_matchups(self, rows, teams_by_roster):
        grouped = defaultdict(list)
        for row in rows or []:
            matchup_id, roster_id = row.get("matchup_id"), self._integer(row.get("roster_id"), 0)
            if matchup_id is None or not roster_id:
                continue
            team = dict(teams_by_roster.get(roster_id, {"name": f"ROSTER {roster_id}"}))
            team.update(roster_id=roster_id, points=self._number(row.get("points"), 0), projected=self._projection(row))
            grouped[self._integer(matchup_id, 0)].append(team)
        matchups = []
        for matchup_id in sorted(grouped):
            teams = sorted(grouped[matchup_id], key=lambda item: item["roster_id"])
            if len(teams) == 1:
                teams.append({"roster_id": 0, "name": "BYE", "points": 0.0, "projected": None})
            if len(teams) >= 2:
                matchups.append({"matchup_id": matchup_id, "teams": teams[:2]})
        return matchups

    def _build_standings(self, rosters, teams_by_roster, league_id=None, league_label=None):
        result = []
        for roster in rosters:
            roster_id = self._integer(roster.get("roster_id"), 0)
            settings = roster.get("settings") or {}
            result.append({
                "name": teams_by_roster.get(roster_id, {"name": f"ROSTER {roster_id}"})["name"],
                "wins": self._integer(settings.get("wins"), 0), "losses": self._integer(settings.get("losses"), 0),
                "ties": self._integer(settings.get("ties"), 0),
                "points": self._number(settings.get("fpts"), 0) + self._number(settings.get("fpts_decimal"), 0) / 100,
                "league_id": league_id,
                "league_label": league_label,
            })
        return sorted(result, key=lambda row: (-row["wins"], row["losses"], -row["points"], row["name"]))

    def _fetch_data(self):
        state = self._get_json("/state/nfl")
        week = self._resolve_week(state)
        all_matchups, all_standings, standing_pages, errors = [], [], [], {}
        for league_id in self.league_ids:
            try:
                league = self._get_json(f"/league/{league_id}")
                users = self._get_json(f"/league/{league_id}/users")
                rosters = self._get_json(f"/league/{league_id}/rosters")
                rows = self._get_json(f"/league/{league_id}/matchups/{week}")
                label = self._league_label(league.get("name"), league_id)
                users_by_id = {user.get("user_id"): user for user in users}
                teams = {self._integer(r.get("roster_id"), 0): self._team(r, users_by_id) for r in rosters}
                matchups = self._build_matchups(rows, teams)
                for matchup in matchups:
                    matchup.update(league_id=league_id, league_label=label, week=week)
                standings = self._build_standings(rosters, teams, league_id, label)
                all_matchups.extend(matchups)
                all_standings.extend(standings)
                for start in range(0, len(standings), max(1, self.standings_rows)):
                    standing_pages.append({"league_label": label, "week": week, "rows": standings[start:start + self.standings_rows]})
            except Exception as exc:
                errors[league_id] = str(exc)
                self.logger.error("Could not load Sleeper league %s: %s", league_id, exc)
        if not all_matchups and not all_standings:
            raise RuntimeError("No configured Sleeper leagues could be loaded")
        # Atomic assignment retains the last good screen if a request fails.
        self.nfl_state, self.current_week = state, week
        self.matchups, self.standings, self.standing_pages = all_matchups, all_standings, standing_pages
        self.league_errors = errors
        self.last_update = time.time()
        self.error_message = f"{len(errors)} LEAGUE OFFLINE" if errors else ""
        self.rotation_started = time.monotonic()

    def update(self):
        now = time.time()
        if self.last_attempt and now - self.last_attempt < self.update_interval:
            return
        self.last_attempt = now
        try:
            self._fetch_data()
            self.logger.info("Loaded %d Sleeper matchups for week %d", len(self.matchups), self.current_week)
        except HTTPError as exc:
            self.error_message = f"HTTP {exc.code}"
            self.logger.error("Sleeper API HTTP error: %s", exc)
        except URLError as exc:
            self.error_message = "OFFLINE"
            self.logger.error("Sleeper API network error: %s", exc)
        except Exception as exc:
            self.error_message = "DATA ERROR"
            self.logger.error("Error loading Sleeper data: %s", exc, exc_info=True)

    def _font(self, key):
        if key in self.fonts:
            return self.fonts[key]
        try:
            manager = getattr(self.plugin_manager, "font_manager", None)
            return manager.get_font(f"{self.plugin_id}.{key}") if manager else self.fonts.get("small")
        except Exception:
            return self.fonts.get("small")

    def _draw(self, text, x, y, font_key="small", color=None):
        base_color = color or self.team_color
        faded_color = tuple(int(part * self.frame_brightness) for part in base_color)
        self.display_manager.draw_text(str(text), x=int(x), y=int(y), font=self._font(font_key), color=faded_color)

    def _draw_centered(self, text, y, font_key="small", color=None):
        self._draw(text, self.display_manager.width // 2, y, font_key, color)

    def _matchup_card(self, index):
        height = self.display_manager.height
        matchup = self.matchups[index]
        team_a, team_b = matchup["teams"]
        # Fixed LED fonts make scores genuinely larger on 96x48 panels.
        for team, y in ((team_a, height * 0.40), (team_b, height * 0.82)):
            score = f"{team['points']:.1f}"
            # 10x20.bdf uses ten horizontal pixels per character. Right-aligning
            # from the measured width keeps scores such as 123.4 on a 96px panel.
            score_x = max(1, self.display_manager.width - len(score) * 10 - 1)
            available_name_chars = max(2, (score_x - 4) // 8)
            self._draw(team["name"][:available_name_chars], 2, y, "team", self.team_color)
            self._draw(score, score_x, y, "score", self.score_color)
        if self.show_projected_points and any(t.get("projected") is not None for t in (team_a, team_b)):
            values = " / ".join("--" if t.get("projected") is None else f"{t['projected']:.1f}" for t in (team_a, team_b))
            self._draw_centered(f"P {values}", height - 2, "small", self.projection_color)

    def _standings_card(self, page):
        height = self.display_manager.height
        if self.standing_pages:
            page_data = self.standing_pages[page]
        else:
            start = page * max(1, self.standings_rows)
            page_data = {"league_label": "SLPR", "week": self.current_week,
                         "rows": self.standings[start:start + self.standings_rows]}
        selected = page_data["rows"]
        start = sum(len(item["rows"]) for item in self.standing_pages[:page] if item["league_label"] == page_data["league_label"])
        self._draw_centered(f"{page_data['league_label']} STAND", 8, "header", self.header_color)
        step = max(9, (height - 8) // max(1, len(selected)))
        for offset, row in enumerate(selected):
            record = f"{row['wins']}-{row['losses']}" + (f"-{row['ties']}" if row["ties"] else "")
            self._draw(f"{start + offset + 1}.{row['name']}", 1, 14 + offset * step, "small", self.team_color)
            self._draw(record, self.display_manager.width - 18, 14 + offset * step, "small", self.score_color)

    def _countdown_text(self):
        if not self.show_countdown:
            return None
        raw = self.nfl_state.get("season_start_date") or self.nfl_state.get("league_season_start_date")
        try:
            start = datetime.strptime(str(raw)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days = max(0, int((start - datetime.now(timezone.utc)).total_seconds() // 86400) + 1)
            return f"KICKOFF IN {days}D" if days else None
        except (TypeError, ValueError):
            return None

    def _idle_card(self):
        height = self.display_manager.height
        self._draw_centered("SLEEPER", height * 0.28, "header", self.header_color)
        self._draw_centered(self._countdown_text() or "NO MATCHUPS", height * 0.58, "team", self.team_color)
        if self.error_message:
            self._draw_centered(self.error_message, height * 0.86, "small", self.accent_color)

    def _matchups_are_relevant(self):
        season_type = str(self.nfl_state.get("season_type") or "regular").lower()
        return bool(self.matchups) and season_type in ("regular", "post", "postseason")

    def display(self, force_clear=False):
        try:
            now = time.monotonic()
            elapsed = max(0, now - self.rotation_started)
            self.frame_brightness = 1.0
            if self._matchups_are_relevant():
                index = int(elapsed / self.matchup_display_seconds) % len(self.matchups)
                frame_key = ("matchup", index, self.last_update)
            elif self.show_standings_when_idle and self.standings:
                pages = max(1, len(self.standing_pages))
                page = int(elapsed / self.matchup_display_seconds) % pages
                frame_key = ("standings", page, self.last_update)
            else:
                frame_key = ("idle", self.error_message, self.last_update)

            # LEDMatrix calls display() once per second. Clearing an unchanged
            # panel on every call produces a visible flash, so keep the existing
            # pixels until the card or data changes. A gap means another plugin
            # was active and this card must be restored.
            returning_to_mode = bool(self.last_display_at and now - self.last_display_at > 2.0)
            self.last_display_at = now
            if not force_clear and not returning_to_mode and frame_key == self.last_frame_key:
                return True

            self.last_frame_key = frame_key
            self.display_manager.clear()
            if frame_key[0] == "matchup":
                self._matchup_card(index)
            elif frame_key[0] == "standings":
                self._standings_card(page)
            else:
                self._idle_card()
            self.display_manager.update_display()
            return True
        except Exception as exc:
            self.logger.error("Sleeper display error: %s", exc, exc_info=True)
            return False

    def validate_config(self):
        if not super().validate_config():
            return False
        checks = (
            (self.league_id.isdigit(), "league_id must contain only digits"),
            (bool(self.league_ids) and all(value.isdigit() for value in self.league_ids), "league_ids must contain numeric Sleeper league IDs"),
            (self.configured_week in range(26), "week must be from 0 through 25"),
            (self.matchup_display_seconds >= 2, "matchup_display_seconds must be at least 2"),
            (self.update_interval >= 15, "update_interval must be at least 15 seconds"),
            (1 <= self.standings_rows <= 4, "standings_rows must be from 1 through 4"),
            (6 <= self.name_max_length <= 18, "name_max_length must be from 6 through 18"),
            (0 <= self.transition_seconds <= 1, "transition_seconds must be from 0 through 1"),
        )
        for valid, message in checks:
            if not valid:
                self.logger.error(message)
                return False
        return True

    def get_info(self):
        info = super().get_info()
        info.update({"league_id": self.league_id, "league_ids": self.league_ids, "week": self.current_week, "matchup_count": len(self.matchups),
                     "standings_count": len(self.standings), "last_update": self.last_update,
                     "last_attempt": self.last_attempt, "league_errors": self.league_errors, "error": self.error_message})
        return info

    def cleanup(self):
        self.logger.info("Cleaning up Sleeper Scoreboard V2")
        super().cleanup()
