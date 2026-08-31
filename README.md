# Sleeper Fantasy Scoreboard V2 for ChuckBuilds LEDMatrix

Displays **every weekly matchup** in a Sleeper fantasy football league and
cycles through the live fantasy scores.

## Included configuration

The default league IDs are:

- `1386603818250158080`
- `1393309596713517056`

You can change the `league_ids` list later from the LEDMatrix web interface.
The original `league_id` setting remains supported for V1 compatibility.

## Features

- Large fixed-pixel team and score fonts for 96x48 matrices
- Retrieves all league users, rosters, team names, avatars, and matchups
- Cycles through both leagues and labels each league in the header
- Automatically uses Sleeper's current NFL week
- Supports manually selecting a week
- Rotates through every matchup
- Refreshes scores every 60 seconds by default
- Retains the last good scores during temporary network failures
- Shows paged league standings when the current week has no matchups
- Cycles each league's overall standings after the matchup cards
- Detects starter scoring jumps and shows fantasy big-play alerts
- Refreshes big-play data every 15 seconds by default
- Optionally shows projected points when supplied in matchup data
- Shows a preseason countdown when Sleeper supplies a season start date
- Handles long team names
- Shows byes
- Uses only Sleeper's public read-only API
- Requires no Sleeper login or API key
- Uses conservative text-only drawing calls compatible with the proven LEDMatrix API

Avatar IDs are retained in the data model, but V2 does not render remote images
because the currently proven ChuckBuilds plugin API exposes text drawing only.

## Install from GitHub

1. Open the LEDMatrix web interface at `http://YOUR-PI-IP:5000`.
2. Open **Plugin Manager** and choose **Install from GitHub**.
3. Paste `https://github.com/Halonoonan/ledmatrix-sleeper-scoreboard`.
4. Install or update the plugin, enable it, confirm the league ID, and save.
5. Restart the display service if the update does not appear immediately.

## Manual installation

Copy the entire folder into the configured LEDMatrix plugin directory, usually:

```bash
/path/to/LEDMatrix/plugin-repos/sleeper-scoreboard
```

The final structure should be:

```text
plugin-repos/
└── sleeper-scoreboard/
    ├── manifest.json
    ├── manager.py
    ├── config_schema.json
    ├── requirements.txt
    ├── icon.svg
    └── README.md
```

Restart the LEDMatrix display service afterward.

## Sleeper endpoints used

- `/v1/state/nfl`
- `/v1/league/{league_id}/users`
- `/v1/league/{league_id}/rosters`
- `/v1/league/{league_id}/matchups/{week}`
- Standings are calculated from `/v1/league/{league_id}/rosters`.

## Troubleshooting

**NO MATCHUPS** usually means the selected week has no generated matchups yet.
Set `week` to a week that has a schedule, or leave it at `0` for automatic.

**Sleeper offline** means the Raspberry Pi could not reach Sleeper. Confirm the Pi
has internet access.

**Plugin does not appear** means the repository files may be inside an extra
folder. `manifest.json` must be at the repository's top level for a standalone
plugin repository.
