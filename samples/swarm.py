"""CMU Swarm: a deliberately heavy cmu_graphics game for benchmarking the R36S.

~500 shapes a frame at the arcade box's 800x600: tile grid, starfield, rotating
asteroid polygons, rotated sprite images, particles with opacity, stars, an arc
and labels that change every frame, plus O(bullets x asteroids) collision logic.

Plays itself until you touch a control. Logs FPS to stdout once a second.
Keyboard: arrows turn/thrust, space fires, escape quits. Arcade joystick (joystick.py,
so it runs in joystick mode on the R36S): stick/D-pad turn+thrust, a (1) fires, P1 (5) quits.
"""
import math
import sys
import time

from cmu_graphics import *
from PIL import Image as PILImage, ImageDraw

W, H = 800, 600
N_ASTEROIDS = 30
N_STARS = 80
N_ENEMIES = 12
TILE = 50
STATS = {'frames': 0}  # redrawAll can't modify app


def makeEnemySprite():
    img = PILImage.new('RGBA', (48, 48), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(24, 2), (46, 40), (24, 30), (2, 40)], fill=(220, 60, 90, 255), outline=(255, 220, 120, 255))
    d.ellipse([18, 14, 30, 26], fill=(120, 230, 255, 255))
    return CMUImage(img)


def newAsteroid(app):
    return {
        'x': randrange(W), 'y': randrange(H),
        'dx': random() * 3 - 1.5, 'dy': random() * 3 - 1.5,
        'r': randrange(12, 34), 'sides': randrange(5, 9),
        'a': randrange(360), 'spin': random() * 6 - 3,
    }


def onAppStart(app):
    seed(112)
    app.stepsPerSecond = 1000
    app.background = 'black'
    app.sprite = makeEnemySprite()
    app.ship = {'x': W / 2, 'y': H / 2, 'a': 0, 'vx': 0, 'vy': 0}
    app.asteroids = [newAsteroid(app) for _ in range(N_ASTEROIDS)]
    app.stars = [(randrange(W), randrange(H), random() * 1.8 + 0.4) for _ in range(N_STARS)]
    app.enemies = [{'x': randrange(W), 'y': randrange(H), 'a': randrange(360)} for _ in range(N_ENEMIES)]
    app.bullets = []
    app.particles = []
    app.score = 0
    app.t = 0
    app.autopilot = True
    app.keys = set()
    app.fps = 0.0
    app.frameMs = 0.0
    app.t0 = time.perf_counter()
    app.steps = 0
    app.lastFrames = 0


def fire(app):
    s = app.ship
    if len(app.bullets) < 40:
        rad = math.radians(s['a'] - 90)
        app.bullets.append({'x': s['x'], 'y': s['y'], 'dx': math.cos(rad) * 9, 'dy': math.sin(rad) * 9, 'life': 60})


def explode(app, x, y, color):
    for _ in range(12):
        if len(app.particles) < 150:
            ang = random() * 2 * math.pi
            sp = random() * 4 + 1
            app.particles.append({'x': x, 'y': y, 'dx': math.cos(ang) * sp, 'dy': math.sin(ang) * sp,
                                  'life': 40, 'color': color})


def onStep(app):
    app.t += 1
    app.steps += 1
    s = app.ship
    if app.autopilot:
        s['a'] = (s['a'] + 3) % 360
        if app.t % 4 == 0:
            fire(app)
    else:
        if 'left' in app.keys: s['a'] -= 5
        if 'right' in app.keys: s['a'] += 5
        if 'up' in app.keys:
            rad = math.radians(s['a'] - 90)
            s['vx'] += math.cos(rad) * 0.3
            s['vy'] += math.sin(rad) * 0.3
        if 'space' in app.keys and app.t % 4 == 0:
            fire(app)
    s['vx'] *= 0.98
    s['vy'] *= 0.98
    s['x'] = (s['x'] + s['vx']) % W
    s['y'] = (s['y'] + s['vy']) % H

    for a in app.asteroids:
        a['x'] = (a['x'] + a['dx']) % W
        a['y'] = (a['y'] + a['dy']) % H
        a['a'] = (a['a'] + a['spin']) % 360
    for e in app.enemies:
        e['a'] = (e['a'] + 2) % 360
        rad = math.radians(e['a'])
        e['x'] = (e['x'] + math.cos(rad) * 1.5) % W
        e['y'] = (e['y'] + math.sin(rad) * 1.5) % H

    alive = []
    for b in app.bullets:
        b['x'] += b['dx']; b['y'] += b['dy']; b['life'] -= 1
        hit = False
        for a in app.asteroids:
            if (b['x'] - a['x']) ** 2 + (b['y'] - a['y']) ** 2 < a['r'] ** 2:
                hit = True
                app.score += 10
                explode(app, a['x'], a['y'], 'orange')
                a.update(newAsteroid(app))
                break
        if not hit and b['life'] > 0 and 0 <= b['x'] <= W and 0 <= b['y'] <= H:
            alive.append(b)
    app.bullets = alive

    parts = []
    for p in app.particles:
        p['x'] += p['dx']; p['y'] += p['dy']; p['life'] -= 1
        if p['life'] > 0:
            parts.append(p)
    app.particles = parts

    now = time.perf_counter()
    if now - app.t0 >= 1:
        frames = STATS['frames'] - app.lastFrames
        app.fps = frames / (now - app.t0)
        app.frameMs = 1000 * (now - app.t0) / max(frames, 1)
        print(f'fps={app.fps:.1f} frame={app.frameMs:.1f}ms steps/s={app.steps / (now - app.t0):.1f} '
              f'shapes~{shapeCount(app)}', flush=True)
        app.lastFrames = STATS['frames']
        app.steps = 0
        app.t0 = now


def shapeCount(app):
    return ((W // TILE) * (H // TILE) + N_STARS + N_ASTEROIDS + N_ENEMIES + len(app.bullets)
            + len(app.particles) + 1 + 4 + 12)


def takeControl(app):
    app.autopilot = False


def onKeyPress(app, key):
    takeControl(app)
    app.keys.add(key)
    if key == 'escape':
        sys.exit(0)


def onKeyRelease(app, key):
    app.keys.discard(key)


# Arcade box style joystick events (when the game imports joystick.py)
def onJoyPress(app, button, joystick):
    takeControl(app)
    if button == '5':
        sys.exit(0)
    if button == '1':
        app.keys.add('space')


def onJoyRelease(app, button, joystick):
    if button == '1':
        app.keys.discard('space')


def onDigitalJoyAxis(app, results, joystick):
    if results:
        takeControl(app)
    app.keys -= {'left', 'right', 'up'}
    if (0, -1) in results: app.keys.add('left')
    if (0, 1) in results: app.keys.add('right')
    if (1, -1) in results: app.keys.add('up')


def redrawAll(app):
    STATS['frames'] += 1
    t = app.t
    # tile grid (192 rects)
    for row in range(H // TILE):
        for col in range(W // TILE):
            shade = 18 + ((row + col + t // 20) % 4) * 6
            drawRect(col * TILE, row * TILE, TILE - 2, TILE - 2, fill=rgb(shade, shade, shade + 14))
    for (x, y, r) in app.stars:
        drawCircle(x, y, r, fill='white', opacity=60)
    for a in app.asteroids:
        drawRegularPolygon(a['x'], a['y'], a['r'], a['sides'], fill='sienna', border='peru',
                           borderWidth=2, rotateAngle=a['a'])
    for e in app.enemies:
        drawImage(app.sprite, e['x'], e['y'], align='center', rotateAngle=e['a'] + 90)
    for b in app.bullets:
        drawLine(b['x'], b['y'], b['x'] - b['dx'], b['y'] - b['dy'], fill='yellow', lineWidth=3)
    for p in app.particles:
        drawRect(p['x'], p['y'], 4, 4, fill=p['color'], opacity=max(5, p['life'] * 2), align='center')
    s = app.ship
    drawPolygon(s['x'], s['y'] - 16, s['x'] + 11, s['y'] + 12, s['x'], s['y'] + 6, s['x'] - 11, s['y'] + 12,
                fill='cyan', border='white', rotateAngle=s['a'])
    for i in range(4):
        drawStar(60 + i * 40, H - 40, 14, 5, fill='gold', rotateAngle=(t * 3 + i * 20) % 360)
    drawArc(W - 60, H - 60, 70, 70, 0, 10 + (t * 4) % 350, fill='lime', opacity=70)
    drawRect(20, 20, 200, 14, fill=None, border='white', borderWidth=1)
    drawRect(20, 20, 2 + 2 * (t % 99), 14, fill='lime')
    drawLabel(f'SCORE {app.score}', W - 20, 30, size=24, bold=True, fill='white', align='right')
    drawLabel(f'FPS {app.fps:.1f}  {app.frameMs:.1f} ms', 20, 55, size=16, fill='yellow', align='left')
    drawLabel(f'bullets {len(app.bullets)}  particles {len(app.particles)}', 20, 78, size=14,
              fill='lightGray', align='left')
    drawLabel('AUTOPILOT - touch a control to play' if app.autopilot else 'arrows/stick + A',
              W / 2, H - 20, size=16, fill='white', italic=True)
    drawLabel(f't={t}', W / 2, 30, size=14, fill='gray')


runApp(width=W, height=H)
