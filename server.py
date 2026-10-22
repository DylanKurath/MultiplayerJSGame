import os
import re
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import database

server = Flask(__name__)

server.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
socket = SocketIO(server)

WORLD_W, WORLD_H = 1000, 600
PLAYER_SIZE = 24
BASE_SPEED = 200  # pixels per second
TICK_RATE = 20
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,16}$")

players = {}

@server.route('/')
def get_client():
    return render_template('clientPage.html', world_w=WORLD_W, world_h=WORLD_H)

def clamp(value, low, high):
    return max(low, min(high, value))

def get_credentials(data):
    data = data if isinstance(data, dict) else {}
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not USERNAME_PATTERN.fullmatch(username):
        emit("account_result", {
            "ok": False,
            "message": "Username must be 3-16 letters, numbers, or underscores.",
        })
        return None
    if not isinstance(password, str) or not 6 <= len(password) <= 128:
        emit("account_result", {
            "ok": False,
            "message": "Password must be between 6 and 128 characters.",
        })
        return None
    return username, password


def start_player(account, message):
    if any(player["id"] == account["id"] for player in players.values()):
        emit("account_result", {
            "ok": False,
            "message": "This account is already playing.",
        })
        return

    x = clamp(account["x"], PLAYER_SIZE / 2, WORLD_W - PLAYER_SIZE / 2)
    y = clamp(account["y"], PLAYER_SIZE / 2, WORLD_H - PLAYER_SIZE / 2)
    players[request.sid] = {
        "id": account["id"],
        "world_id": account["world_id"],
        "name": account["name"],
        "hue": random.randint(0, 359),
        "x": x,
        "y": y,
        "dx": 0,
        "dy": 0,
    }
    database.save_player_states([players[request.sid]])
    emit("account_result", {"ok": True, "message": message})
    emit("welcome", {
        "id": request.sid,
        "name": account["name"],
        "x": x,
        "y": y,
        "hue": players[request.sid]["hue"],
    })
    socket.emit("chat", {
        "username": "system",
        "text": f'{account["name"]} joined.',
    })


@socket.on("register")
def on_register(data):
    credentials = get_credentials(data)
    if not credentials:
        return
    username, password = credentials
    account = database.create_account(username, password)
    if not account:
        emit("account_result", {
            "ok": False,
            "message": "That username is already taken.",
        })
        return
    start_player(account, "Account created.")


@socket.on("login")
def on_login(data):
    credentials = get_credentials(data)
    if not credentials:
        return
    username, password = credentials
    account = database.authenticate(username, password)
    if not account:
        emit("account_result", {
            "ok": False,
            "message": "Invalid username or password.",
        })
        return
    start_player(account, "Logged in.")

@socket.on('disconnect')
def on_disconnect(*args):
    player = players.get(request.sid)
    if player:
        database.save_player_states([player])
        players.pop(request.sid, None)
        socket.emit('chat', {'username': 'system', 'text': f"{player['name']} left."})
 
@socket.on('input')
def on_input(data):
    player = players.get(request.sid)
    if not player:
        return
    player['dx'] = clamp(int((data or {}).get('dx', 0)), -1, 1)
    player['dy'] = clamp(int((data or {}).get('dy', 0)), -1, 1)

@socket.on('chat')
def on_chat(data):
    player = players.get(request.sid)
    text = str((data or {}).get('text', '')).strip()[:200]
    if not player or not text:
        return
    socket.emit('chat', {'username': player['name'], 'text': text})

def game_loop():
    dt = 1 / TICK_RATE
    half = PLAYER_SIZE / 2
    save_elapsed = 0
    while True:
        socket.sleep(dt)
        save_elapsed += dt
        for p in list(players.values()):
            dx, dy = p['dx'], p['dy']
            if dx and dy:
                dx *= 0.7
                dy *= 0.7
            p['x'] = clamp(p['x'] + dx * BASE_SPEED * dt, half, WORLD_W - half)
            p['y'] = clamp(p['y'] + dy * BASE_SPEED * dt, half, WORLD_H - half)
        if players:
            socket.emit('state', {
                sid: {'x': round(p['x'], 1), 'y': round(p['y'], 1), 'name': p['name'], 'hue': p['hue']}
                for sid, p in list(players.items())
            })
        if save_elapsed >= 5:
            database.save_player_states(players.values())
            save_elapsed = 0

if __name__ == '__main__':
    database.init_db()
    # Start the game loop only in the reloader's serving process.
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        socket.start_background_task(game_loop)
    socket.run(
        server,
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=True,
        allow_unsafe_werkzeug=True,
    )