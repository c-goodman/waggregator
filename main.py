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


# ---------- Start ----------

init_db()

intents = discord.Intents.default()
intents.message_content = True

client = Client(intents=intents)
client.run(bot_token)
