import os
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random

server = Flask(__name__)

server.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-me')
socket = SocketIO(server)

WORLD_W, WORLD_H = 1000, 600
PLAYER_SIZE = 24
BASE_SPEED = 200  # pixels per second
TICK_RATE = 20

players = {}

@server.route('/')
def get_client():
    return render_template('clientPage.html', world_w=WORLD_W, world_h=WORLD_H)

def get_unique_name(requested):
    name = (requested or '').strip()[:16] or 'User'
    taken = {p['name'].lower() for p in players.values()}
    taken.add('system')
    candidate, count = name, 1
    while candidate.lower() in taken:
        count += 1
        candidate = f'{name}{count}'
    return candidate

def clamp(value, low, high):
    return max(low, min(high, value))

@socket.on('join')
def on_join(data):
    if request.sid in players:
        return
    name = get_unique_name((data or {}).get('name'))
    players[request.sid] = {
        'name': name,
        'hue': random.randint(0, 359),
        'x': WORLD_W / 2,
        'y': WORLD_H / 2,
        'dx': 0,
        'dy': 0,
    }
    emit('welcome', {'id': request.sid, 'name': name})
    socket.emit('chat', {'username': 'system', 'text': f'{name} joined.'})

@socket.on('disconnect')
def on_disconnect(*args):
    player = players.pop(request.sid, None)
    if player:
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
    while True:
        socket.sleep(dt)
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

if __name__ == '__main__':
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