# waggregator - Discord Web App Game Score Tracker

A Discord bot that automatically detects game score submissions, records player statistics, and tracks daily and all-time performance. Players can post their scores in a designated Discord text channel and receive an instant statistical summary.

<img width="531" height="1303" alt="image" src="https://github.com/user-attachments/assets/fefc75e2-801b-43e5-9d61-9753d77a8a14" />


## Features

- **Automatic score detection:** Detects supported games from messages using configurable trigger phrases.
- **Flexible score parsing:** Extracts scores using regular expressions or configurable text positions.
- **Normalized scoring:** Converts raw scores into percentages, allowing performance comparisons across different games.
- **Daily score tracking:** Tracks games played, normalized totals, and averages for each calendar day.
- **All-time statistics:** Maintains cumulative player statistics across all recorded submissions.
- **Per-game breakdowns:** Tracks daily game counts, total normalized scores, average scores, and best normalized scores in the database.
- **Recent submissions:** Stores the information needed to retrieve a player's five most recent scores.
- **Historical statistics:** Maintains daily records for long-term performance tracking.
- **Duplicate submission prevention:** Limits each player to one recorded score per game per day.
- **SQLite database:** Persists score data locally without requiring a separate database server.
- **Configurable game support:** Add or modify supported games through `pasta.json` without changing the core score-parsing logic.
- **Timezone-aware tracking:** Uses the `America/Chicago` timezone to determine each submission's calendar day.

## Tech Stack

- [Python](<https://www.python.org/>)
- [discord.py](<https://discordpy.readthedocs.io/>)
- [SQLite](<https://www.sqlite.org/>)
- [python-dotenv](<https://pypi.org/project/python-dotenv/>)
- Python's `zoneinfo` module for timezone handling

## Project Structure

```txt
.
├── main.py          # Bot entry point and score-tracking logic
├── pasta.json       # Game triggers and score parsing configuration
├── .env             # Discord token and target channel ID
├── .gitignore       # Files excluded from version control
└── wagdb.db         # SQLite database
```

I recommend using [DBeaver](https://dbeaver.io/download/) to download SQLite drivers and create a local database of your choosing. DBeaver will also allow you to manage any recorded data manually if needed.

## Getting Started

### 1. Prerequisites

Before running the bot, you will need:

- Python 3.10 or newer.
- A Discord account and a server where you can add a bot.
- A Discord application and bot token from the [Discord Developer Portal](<https://discord.com/developers/applications>).
- Installed package deps `discord.py` and `python-dotenv`.
- A local SQLite Database for the bot to read/write to.

See this youtube guide for the basic steps on how to set up a discord bot using the developer portal.

- [Creating a Discord Bot in Python (2025) | Episode 1: Setup & Basics](https://www.youtube.com/watch?v=CHbN_gB30Tw)

### 2. Clone the Repository

```cmd
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY.git
cd YOUR_REPOSITORY
```

Replace the repository URL with your own GitHub repository.

### 3. Create a Python Virtual Environment

Seek other resources. I used conda for this project.

### 4. Install Dependencies

Use whatever package manager you would like, `discord.py` and `python-dotenv` are the only two major deps.

```cmd
pip install discord.py python-dotenv
```

The `sqlite3`, `json`, `re`, `datetime`, and `zoneinfo` modules are included in Python's standard library.

### 5\. Configure Environment Variables

Create a `.env` file in the project root:

```env
TOKEN=your_discord_bot_token
TARGET_CHAT_ID=123456789012345678
```

- `TOKEN`: Your Discord bot token. Obtained from discord developer portal.
- `TARGET_CHAT_ID`: The ID of the channel where the bot should monitor score submissions.

To obtain a channel ID, enable Developer Mode in Discord, right-click the target channel, and select **Copy Channel ID**.

**Important:** Never commit your `.env` file or expose your bot token publicly.

### 6. Enable Discord Intents

See youtube guide above. You will need to give the discord bot permissions via the discord developer portal.

### 7. Configure Supported Games

Score Parsing Configuration

The bot supports two methods for extracting scores from Discord messages: delimiter-based parsing and regular expression parsing. Each game is configured independently in pasta.json, allowing new games to be added without modifying main.py.

Create a `pasta.json` (copy pasta) file in the project root. Each game needs a trigger, a maximum score, and a score-parsing configuration.

#### 7.1. Regex Parsing

```json
{
  "Example Game": {
    "trigger": "example game",
    "score_regex": "Score:\\s*([0-9,]+)",
    "score_max": 50000
  }
}
```

With this configuration, a message containing:

```txt
I played Example Game today! Score: 41,407
```

will match the game trigger and extract `41407` as the raw score.

The score will be normalized against the configured maximum of `50000`.

#### 7.2. Delimiter Parsing

Delimiter-based parsing extracts a score relative to a specific text marker in the message. It uses three settings:

Setting Description
score_index - The text marker used to locate the score.
score_index_location - Determines where the score is in relation to the index string: before or after.
score_max_width - The maximum number of characters to inspect when extracting the score.

After extracting the relevant text, the bot removes non-digit characters and converts the remaining digits into an integer.

Example configuration:

```json
{
  "timeguesser": {
    "trigger": "TimeGuessr",
    "score_index": "/",
    "score_index_location": "after",
    "score_max_width": 6,
    "score_max": 50000
  }
}
```

Example message:

TimeGuessr result: 42,150 / 50,000

The bot finds "/" then extracts the six characters immediately before it, and removes non-digit characters to obtain the raw score.

This method is useful when the score appears immediately before a consistent marker.

Score Before the Delimiter

When score_index_location is set to before, the bot extracts up to score_max_width characters immediately after the delimiter.

Example configuration:

```json
{
  "maptap": {
    "trigger": "www.maptap.gg",
    "score_index": "Final score: ",
    "score_index_location": "before",
    "score_max_width": 4,
    "score_max": 1000
  }
}
```

Example message:

```txt
www.maptap.gg
Final score: 875
```

The bot finds "Final score: " then extracts the next four characters, and converts the digits into the raw score.

This method works well when a game reports its score after a predictable label.

#### 7.3. Configuration Fields

| Field | Description |
| --- | --- |
| `trigger` | Text used to detect the game in a message. |
| `score_regex` | Optional regex whose first capture group contains the score. |
| `score_index` | Optional text delimiter used instead of a regex. |
| `score_max_width` | Number of characters to inspect when using delimiter-based parsing. |
| `score_index_location` | Set to `after` or `before` to choose which side of the delimiter contains the score. |
| `score_max` | Maximum valid raw score for the game. |

Use either `score_regex` or the delimiter-based configuration. Regular expression parsing is generally the simplest option.

Game names are matched case-insensitively. Make sure each game has an appropriate trigger to reduce ambiguous matches.

### 8. Run the Bot

Run main.py

When connected successfully, the terminal displays a message similar to:

```cmd
2026-10-22 15:40:21 INFO     discord.client logging in using static token
2026-10-22 15:40:22 INFO     discord.gateway Shard ID None has connected to Gateway (Session ID: 238429347abcd2342024352345someothertextetc).
Logged in as waggregator#4112
```

The bot is now ready to monitor the configured channel.

## How Scoring Works

When a user posts a message in the target channel, the bot:

1. Ignores messages sent by bots.
2. Checks whether the message contains a configured game trigger.
3. Extracts the raw score using the game's parsing configuration.
4. Validates the score against the game's maximum.
5. Converts the raw score to a normalized percentage.
6. Determines the submission date using the `America/Chicago` timezone.
7. Saves the submission to SQLite, provided the user has not already submitted a score for that game on that day.
8. Replies with updated daily and all-time statistics.

### Normalized Score Formula

The bot calculates a normalized score using the following formula:

```txt
Normalized Score = (Raw Score / Maximum Score) * 100
```

For example, a score of `41,407` out of `50,000` becomes:

```txt
Raw Score:        41,407 / 50,000
Normalized Score: 82.81%
```

Normalization makes scores from games with different scoring scales easier to compare.

### Example Discord Response

```txt
Score update for PlayerName
Date: 2026-10-22

Latest game: Example Game
Score: 41,407/50,000 (82.81%)

Today's statistics
Games played: 1
Normalized total: 82.81
Normalized average: 82.81%

All-time statistics
Games played: 12
Normalized total: 934.25
Normalized average: 77.85%

Today's games
- Example Game: 1 games, total 82.81, avg 82.81%
```

The values above are illustrative and do not represent actual database records.

## Database

The bot automatically creates `wagdb.db` and initializes a `scores` table when it starts.

Each recorded submission stores:

- Discord message ID
- User ID and display name
- Game name
- Raw score and maximum score
- Normalized score
- Original message creation timestamp in UTC
- Calendar-day key in the configured daily timezone

A unique database index on `user_id`, `game`, and `day_key` prevents a user from recording more than one score for the same game per day.

The database file persists between restarts, so existing score records remain available as long as the file is retained.

The current implementation collects daily history, recent submissions, and per-game best scores in its statistics function. However, the Discord reply currently displays only the daily and all-time totals and the daily per-game breakdown.

## Possible Future Improvements

- Leaderboards for daily, weekly, and all-time performance.
- Slash commands for player statistics and historical records.
- Commands to display recent submissions and per-game personal bests.
- Scheduled daily summaries.
- Configurable timezones and target channels.
- Administrative commands to correct or remove submissions.
- Unit tests for score parsing, normalization, and duplicate prevention.
- Docker support for easier deployment.
- Cloud database support for persistent hosting across multiple instances.
