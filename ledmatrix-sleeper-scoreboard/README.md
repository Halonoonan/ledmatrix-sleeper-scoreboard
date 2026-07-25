# Sleeper Fantasy Scoreboard for ChuckBuilds LEDMatrix

Displays **every weekly matchup** in a Sleeper fantasy football league and
cycles through the live fantasy scores.

## Included configuration

The default league ID is:

`1386603818250158080`

You can change it later from the LEDMatrix web interface.

## Features

- Retrieves all league users, rosters, team names, and matchups
- Automatically uses Sleeper's current NFL week
- Supports manually selecting a week
- Rotates through every matchup
- Refreshes scores every 60 seconds by default
- Handles long team names
- Shows byes
- Uses only Sleeper's public read-only API
- Requires no Sleeper login or API key
- Optimized for a 96x48 display

## Install from GitHub

1. Create a new public GitHub repository, such as `ledmatrix-sleeper-scoreboard`.
2. Upload every file from this folder to the **top level** of that repository.
3. Open the LEDMatrix web interface at `http://YOUR-PI-IP:5000`.
4. Open **Plugin Manager**.
5. Find **Install from GitHub**.
6. Paste your repository URL.
7. Click **Install**.
8. Enable **Sleeper Fantasy Scoreboard**.
9. Confirm the league ID and save.
10. Restart the display service if the plugin does not appear immediately.

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

## Troubleshooting

**NO MATCHUPS** usually means the selected week has no generated matchups yet.
Set `week` to a week that has a schedule, or leave it at `0` for automatic.

**Sleeper offline** means the Raspberry Pi could not reach Sleeper. Confirm the Pi
has internet access.

**Plugin does not appear** means the repository files may be inside an extra
folder. `manifest.json` must be at the repository's top level for a standalone
plugin repository.
