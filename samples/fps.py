from cmu_graphics import *
import time, platform

# FPS benchmark: draws a moderate scene and logs real frame rate once a second.
N_BALLS = 40
# redrawAll may not modify app, so frame counters live here
STATS = {"frames": 0, "drawTime": 0.0}

def onAppStart(app):
    app.stepsPerSecond = 2000  # ask for 60 so we see the real ceiling
    app.x, app.y = 320, 240
    app.lastButton = 'none'
    app.balls = [[randrange(640), randrange(480), choice([-3, 3]), choice([-3, 3])]
                 for _ in range(N_BALLS)]
    app.steps = 0
    app.t0 = time.perf_counter()
    app.fps = app.sps = 0.0
    app.drawMs = 0.0
    app.infoPrinted = False

def onStep(app):
    app.steps += 1
    for b in app.balls:
        b[0] += b[2]; b[1] += b[3]
        if not 0 <= b[0] <= 640: b[2] *= -1
        if not 0 <= b[1] <= 480: b[3] *= -1
    now = time.perf_counter()
    dt = now - app.t0
    if dt >= 1:
        app.fps = STATS["frames"] / dt
        app.sps = app.steps / dt
        app.drawMs = 1000 * STATS["drawTime"] / max(STATS["frames"], 1)
        print(f'fps={app.fps:.1f} steps/s={app.sps:.1f} redrawAll={app.drawMs:.1f}ms '
              f'shapes={N_BALLS + 6}', flush=True)
        STATS["frames"] = app.steps = 0
        STATS["drawTime"] = 0.0
        app.t0 = now

def onDigitalJoyAxis(app, directions, joystick):
    if (0, -1) in directions: app.x -= 5
    if (0, 1) in directions: app.x += 5
    if (1, -1) in directions: app.y -= 5
    if (1, 1) in directions: app.y += 5

def onJoyPress(app, button, joystick):
    app.lastButton = button

def redrawAll(app):
    t = time.perf_counter()
    STATS["frames"] += 1
    drawRect(0, 0, 640, 480, fill='midnightBlue')
    for b in app.balls:
        drawCircle(b[0], b[1], 10, fill='steelBlue')
    drawLabel('cmu_graphics works on R36S!', 320, 60, size=28, fill='white', bold=True)
    drawLabel(f'last button: {app.lastButton}', 320, 100, size=18, fill='lightGray')
    drawLabel('D-pad moves the dot. Select+Start quits.', 320, 440, size=16, fill='lightGray')
    drawCircle(app.x, app.y, 20, fill='crimson')
    drawLabel(f'FPS {app.fps:.1f}  steps/s {app.sps:.1f}  draw {app.drawMs:.1f} ms',
              10, 20, size=16, fill='yellow', align='left', bold=True)
    STATS["drawTime"] += time.perf_counter() - t

runApp(width=640, height=480)
