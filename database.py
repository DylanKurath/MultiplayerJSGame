import sqlite3
import uuid
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

DB_PATH = Path(__file__).resolve().parent / "instance" / "game.db"
DEFAULT_WORLD_ID = "default"
DEFAULT_SPAWN_X = 500
DEFAULT_SPAWN_Y = 300


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    connection = connect()
    try:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS worlds (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                width_tiles INTEGER NOT NULL CHECK (width_tiles > 0),
                height_tiles INTEGER NOT NULL CHECK (height_tiles > 0),
                tile_size INTEGER NOT NULL CHECK (tile_size > 0),
                default_tile_id INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS players (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                username TEXT,
                password_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS player_world_state (
                player_id TEXT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                x REAL NOT NULL,
                y REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%f', 'now')),
                PRIMARY KEY (player_id, world_id)
            );

            CREATE TABLE IF NOT EXISTS world_tiles (
                world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
                tile_x INTEGER NOT NULL,
                tile_y INTEGER NOT NULL,
                tile_id INTEGER NOT NULL,
                PRIMARY KEY (world_id, tile_x, tile_y)
            );
        """)
        player_columns = {
            column["name"]
            for column in connection.execute("PRAGMA table_info(players)")
        }
        if "username" not in player_columns:
            connection.execute("ALTER TABLE players ADD COLUMN username TEXT")
        if "password_hash" not in player_columns:
            connection.execute("ALTER TABLE players ADD COLUMN password_hash TEXT")
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_players_username
            ON players(username COLLATE NOCASE)
        """)
        connection.execute("""
            INSERT OR IGNORE INTO worlds
                (id, name, width_tiles, height_tiles, tile_size, default_tile_id)
            VALUES (?, 'World', 1000, 600, 1, 0)
        """, (DEFAULT_WORLD_ID,))
        connection.commit()
    finally:
        connection.close()


def create_account(username, password):
    player_id = uuid.uuid4().hex
    password_hash = generate_password_hash(password)
    connection = connect()
    try:
        player_columns = {
            column["name"]
            for column in connection.execute("PRAGMA table_info(players)")
        }
        values = {
            "id": player_id,
            "display_name": username,
            "username": username,
            "password_hash": password_hash,
        }
        if "world_id" in player_columns:
            values["world_id"] = DEFAULT_WORLD_ID
        if "x" in player_columns:
            values["x"] = DEFAULT_SPAWN_X
        if "y" in player_columns:
            values["y"] = DEFAULT_SPAWN_Y

        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        try:
            connection.execute(
                f"INSERT INTO players ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
        except sqlite3.IntegrityError:
            return None
        connection.execute("""
            INSERT INTO player_world_state (player_id, world_id, x, y)
            VALUES (?, ?, ?, ?)
        """, (player_id, DEFAULT_WORLD_ID, DEFAULT_SPAWN_X, DEFAULT_SPAWN_Y))
        connection.commit()
        return {
            "id": player_id,
            "name": username,
            "world_id": DEFAULT_WORLD_ID,
            "x": DEFAULT_SPAWN_X,
            "y": DEFAULT_SPAWN_Y,
        }
    finally:
        connection.close()


def authenticate(username, password):
    connection = connect()
    try:
        account = connection.execute("""
            SELECT id, display_name, password_hash
            FROM players
            WHERE username = ? COLLATE NOCASE
        """, (username,)).fetchone()
        if not account or not account["password_hash"]:
            return None
        if not check_password_hash(account["password_hash"], password):
            return None

        state = connection.execute("""
            SELECT world_id, x, y
            FROM player_world_state
            WHERE player_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """, (account["id"],)).fetchone()
        if state:
            world_id, x, y = state["world_id"], state["x"], state["y"]
        else:
            world_id, x, y = DEFAULT_WORLD_ID, DEFAULT_SPAWN_X, DEFAULT_SPAWN_Y

        return {
            "id": account["id"],
            "name": account["display_name"],
            "world_id": world_id,
            "x": x,
            "y": y,
        }
    finally:
        connection.close()


def save_player_states(active_players):
    states = [
        (player["id"], player["world_id"], player["x"], player["y"])
        for player in active_players
    ]
    if not states:
        return

    connection = connect()
    try:
        connection.executemany("""
            INSERT INTO player_world_state (player_id, world_id, x, y)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id, world_id) DO UPDATE SET
                x = excluded.x,
                y = excluded.y,
                updated_at = strftime('%Y-%m-%d %H:%M:%f', 'now')
        """, states)
        connection.commit()
    finally:
        connection.close()