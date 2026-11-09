import os
import json
import re
import sqlite3
import discord
from datetime import timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

# bot_token = os.getenv("TEST_TOKEN")
# chat_id = int(os.getenv("TEST_TARGET_CHAT_ID"))

bot_token = os.getenv("TOKEN")
chat_id = int(os.getenv("TARGET_CHAT_ID"))

DB_PATH = "wagdb.db"
PASTA_PATH = "pasta.json"
DAILY_TIMEZONE = ZoneInfo("America/Chicago")

# ---------- Configuration ----------


with open(PASTA_PATH, "r", encoding="utf-8") as f:
    PASTA_DATA = json.load(f)


# ---------- Database ----------


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                message_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                game TEXT NOT NULL,
                raw_score INTEGER NOT NULL,
                max_score INTEGER NOT NULL,
                normalized_score REAL NOT NULL,
                created_at TEXT NOT NULL,
                day_key TEXT NOT NULL
            );
        """)

        # Ensure that a user can only have one score per game per day
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_unique_user_game_day
            ON scores (user_id, game, day_key)
        """)


def save_score(
    message_id: int,
    user_id: int,
    username: str,
    game: str,
    raw_score: int,
    max_score: int,
    normalized_score: float,
    created_at: str,
    day_key: str,
) -> bool:
    """Save a submission. Return False if already recorded."""

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO scores (
                message_id, user_id, username, game,
                raw_score, max_score, normalized_score, created_at, day_key
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                str(message_id),
                str(user_id),
                username,
                game,
                raw_score,
                max_score,
                normalized_score,
                created_at,
                day_key,
            ),
        )

        return cursor.rowcount == 1


# ---------- Game detection ----------


def get_trigger_from_message(message_content: str) -> str | None:
    content = message_content.casefold()

    for key, settings in PASTA_DATA.items():
        trigger = settings.get("trigger", "")

        if trigger and trigger.casefold() in content:
            return key

    return None


# ---------- Score parsing ----------


def parse_score(settings: dict, message: str) -> int | None:
    """Parse a raw score using either a regex or index configuration."""

    regex = settings.get("score_regex")

    if regex:
        match = re.search(regex, message)

        if not match:
            return None

        # Supports scores such as 410 and 41,407.
        score_text = match.group(1)
        digits = re.sub(r"\D", "", score_text)

        return int(digits) if digits else None

    # Alternative: parse the score using a configured text index.
    score_index = settings.get("score_index")

    if score_index is None:
        return None

    parts = message.split(score_index)

    if len(parts) < 2:
        return None

    width = settings["score_max_width"]
    location = settings["score_index_location"]

    if location == "after":
        score_text = parts[0][-width:]
    elif location == "before":
        score_text = parts[1][:width]
    else:
        raise ValueError(f"Invalid score_index_location: {location}")

    digits = re.sub(r"\D", "", score_text.strip())

    return int(digits) if digits else None


def get_normalized_score(
    game: str,
    message: str,
) -> tuple[int, int, float] | None:
    settings = PASTA_DATA[game]

    raw_score = parse_score(settings, message)
    max_score = settings["score_max"]

    if raw_score is None or max_score <= 0:
        return None

    # Reject malformed or out-of-range scores.
    if not 0 <= raw_score <= max_score:
        return None

    normalized = raw_score / max_score * 100

    return raw_score, max_score, normalized


# ---------- Player statistics ----------


def get_player_stats(user_id: int, day_key: str) -> dict:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Today's totals
        daily = conn.execute(
            """
            SELECT
                COUNT(*) AS games_played,
                COALESCE(SUM(normalized_score), 0) AS total_score,
                COALESCE(AVG(normalized_score), 0) AS average_score
            FROM scores
            WHERE user_id = ? AND day_key = ?
        """,
            (str(user_id), day_key),
        ).fetchone()

        # All-time totals
        overall = conn.execute(
            """
            SELECT
                COUNT(*) AS games_played,
                COALESCE(SUM(normalized_score), 0) AS total_score,
                COALESCE(AVG(normalized_score), 0) AS average_score
            FROM scores
            WHERE user_id = ?
        """,
            (str(user_id),),
        ).fetchone()

        # Today's scores grouped by game
        by_game = conn.execute(
            """
            SELECT
                game,
                COUNT(*) AS games_played,
                SUM(normalized_score) AS total_score,
                AVG(normalized_score) AS average_score,
                MAX(normalized_score) AS best_score
            FROM scores
            WHERE user_id = ? AND day_key = ?
            GROUP BY game
            ORDER BY average_score DESC
        """,
            (str(user_id), day_key),
        ).fetchall()

        # Five most recent submissions, across all dates
        recent = conn.execute(
            """
            SELECT game, raw_score, max_score,
                   normalized_score, created_at, day_key
            FROM scores
            WHERE user_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 5
        """,
            (str(user_id),),
        ).fetchall()

        # One historical record per calendar day
        history = conn.execute(
            """
            SELECT
                day_key,
                COUNT(*) AS games_played,
                SUM(normalized_score) AS total_score,
                AVG(normalized_score) AS average_score
            FROM scores
            WHERE user_id = ?
            GROUP BY day_key
            ORDER BY day_key DESC
        """,
            (str(user_id),),
        ).fetchall()

    return {
        "day_key": day_key,
        "daily": dict(daily),
        "overall": dict(overall),
        "by_game": [dict(row) for row in by_game],
        "recent": [dict(row) for row in recent],
        "history": [dict(row) for row in history],
    }


# ---------- History statistics ----------


def get_history_stats(days: int | None, all_time: bool = True):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Handle None or non-integer days values
        if not isinstance(days, int):
            days = 0

        # Use SQLite string concatenation operator (||) to insert the number of days
        history = conn.execute(
            """
            WITH daily_rankings AS (
                SELECT
                    user_id,
                    username,
                    game,
                    day_key,
                    raw_score,
                    RANK() OVER (
                        PARTITION BY game, day_key
                        ORDER BY raw_score DESC
                    ) AS daily_rank
                FROM scores
                WHERE (? = 1 OR created_at >= datetime('now', '-' || ? || ' days'))
            ),
            player_stats AS (
                SELECT
                    user_id,
                    username,
                    game,
                    COUNT(DISTINCT day_key) AS games_played,
                    AVG(raw_score) AS avg_raw_score,
                    MAX(raw_score) AS max_raw_score,
                    MIN(raw_score) AS min_raw_score
                FROM scores
                WHERE (? = 1 OR created_at >= datetime('now', '-' || ? || ' days'))
                GROUP BY user_id, game
            ),
            player_wins AS (
                SELECT
                    user_id,
                    game,
                    COUNT(DISTINCT day_key) AS wins
                FROM daily_rankings
                WHERE daily_rank = 1
                GROUP BY user_id, game
            )
            SELECT
                ps.username,
                ps.game,
                ps.games_played,
                COALESCE(pw.wins, 0) AS wins,
                ps.avg_raw_score,
                ps.max_raw_score,
                ps.min_raw_score
            FROM player_stats ps
            LEFT JOIN player_wins pw
                ON ps.user_id = pw.user_id
                AND ps.game = pw.game
            ORDER BY ps.game, ps.avg_raw_score DESC;
            """,
            (int(all_time), days, int(all_time), days),
        ).fetchall()

        return {
            "history": [dict(row) for row in history],
        }


def build_history_message(stats, days: int | None):
    history = stats.get("history", [])

    if not history:
        return "Historical Score Statistics\n\nNo historical scores found."

    lines = [
        f"**Historical Score Statistics**",
        f"Last {days} days" if days else "All time",
        "",
    ]

    games = {}

    for row in history:
        games.setdefault(row["game"], []).append(row)

    for game, players in games.items():
        players.sort(key=lambda p: p["avg_raw_score"], reverse=True)

        lines.append(f"**{game.upper()}**")
        lines.append(
            "```"
            "\n"
            f"{'Player':<15} {'Games':>5} {'Wins':>5} {'Average':>10} "
            f"{'Best':>7} {'Lowest':>7}"
        )

        for player in players:
            lines.append(
                f"{player['username']:<15} "
                f"{player['games_played']:>5} "
                f"{player['wins']:>5} "
                f"{player['avg_raw_score']:>10,.2f} "
                f"{player['max_raw_score']:>7,} "
                f"{player['min_raw_score']:>7,}"
            )

        lines.append("```")
        lines.append("")

    return "\n".join(lines)


# ---------- Message handling ----------


async def handle_stats_command(message):
    parts = message.content.strip().split()

    # Validate argument count
    if not parts or (len(parts) > 2) or parts[0].lower() not in ["!stats", "!help"]:
        await message.reply(
            "Unknown command. Use `!help` for usage information.",
            mention_author=False,
        )
        return

    # Return help message
    if parts[0].lower().startswith("!help"):
        await message.reply(
            "Usage: `!stats` for all time or `!stats X` for past X number of days (e.g. `!stats 30`).",
            mention_author=False,
        )
        return

    # Parse optional days argument
    try:
        days = int(parts[1]) if len(parts) == 2 else 0
    except ValueError:
        await message.reply(
            "Invalid number of days. Try `!stats` for all time or `!stats 30` for past 30 days.",
            mention_author=False,
        )
        return

    if days <= 0:
        await message.reply(
            "Please provide a positive number of days.",
            mention_author=False,
        )
        return

    all_time = len(parts) == 1

    # Retrieve historical statistics
    stats = get_history_stats(
        days=days,
        all_time=all_time,
    )

    # Construct response
    reply = build_history_message(
        stats,
        days=None if all_time else days,
    )

    # Discord's message limit is 2000 characters
    if len(reply) > 2000:
        await message.reply(
            "Your statistics are too large for one message.",
            mention_author=False,
        )
        return

    await message.reply(reply, mention_author=False)


async def handle_game_entry(message):
    game = get_trigger_from_message(message.content)

    if game is None:
        return

    parsed = get_normalized_score(game, message.content)

    if parsed is None:
        await message.reply(
            f"I detected **{game}**, but couldn't parse "
            "a valid score from your message.",
            mention_author=False,
        )
        return

    raw_score, max_score, normalized = parsed

    # Parse created at to get the day key
    created_at = message.created_at
    day_key = created_at.astimezone(DAILY_TIMEZONE).date().isoformat()

    saved = save_score(
        message_id=message.id,
        user_id=message.author.id,
        username=message.author.display_name,
        game=game,
        raw_score=raw_score,
        max_score=max_score,
        normalized_score=normalized,
        created_at=created_at.astimezone(timezone.utc).isoformat(),
        day_key=day_key,
    )

    if not saved:
        # Avoid counting the same message twice.
        await message.reply(
            f"⚠️ {message.author.mention}, you've already "
            f"submitted a score for **{game}** on "
            f"**{day_key}**. Your new score wasn't recorded.",
            mention_author=False,
        )
        return

    stats = get_player_stats(message.author.id, day_key=day_key)

    daily = stats["daily"]
    overall = stats["overall"]

    game_lines = [
        f"- **{row['game']}**: "
        f"{row['games_played']} games, "
        f"total {row['total_score']:.2f}, "
        f"avg {row['average_score']:.2f}%"
        for row in stats["by_game"]
    ]

    reply = (
        f"📊 **Score update for {message.author.display_name}**\n"
        f"Date: **{day_key}**\n\n"
        f"**Latest game: {game}**\n"
        f"Score: {raw_score:,}/{max_score:,} "
        f"({normalized:.2f}%)\n\n"
        f"**Today's statistics**\n"
        f"Games played: **{daily['games_played']}**\n"
        f"Normalized total: **{daily['total_score']:.2f}**\n"
        f"Normalized average: **{daily['average_score']:.2f}%**\n\n"
        f"**All-time statistics**\n"
        f"Games played: **{overall['games_played']}**\n"
        f"Normalized total: **{overall['total_score']:.2f}**\n"
        f"Normalized average: **{overall['average_score']:.2f}%**\n\n"
        f"**Today's games**\n" + ("\n".join(game_lines) or "No games yet.")
    )

    await message.reply(reply, mention_author=False)


# ---------- Discord bot ----------


class Client(discord.Client):

    async def on_ready(self):
        print(f"Logged in as {self.user}")

    async def on_message(self, message):
        # Ignore bots, including this bot.
        if message.author.bot:
            return

        # Only track submissions in the target channel.
        if message.channel.id != chat_id:
            return

        # Handle stats command
        if message.content.strip().lower().startswith("!stats"):
            await handle_stats_command(message)
            return

        await handle_game_entry(message)


# ---------- Start ----------

init_db()

intents = discord.Intents.default()
intents.message_content = True

client = Client(intents=intents)
client.run(bot_token)
