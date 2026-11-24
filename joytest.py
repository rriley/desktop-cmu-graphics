"""
Joystick tester: shows every gamepad/joystick that joystick.py sees, which buttons and
axes are active, and a log of recent events.  800x600.

Run:  python3 joytest.py        (joystick.py must be in the same folder)
      CMU_JOY_DEBUG=1 python3 joytest.py            to also show raw backend events
Quit: press Esc on the keyboard, or hold Select+Start (button 8 and 9) on the pad.
"""

# ruff: noqa: F403, F405
from cmu_graphics import *
import joystick

BUTTONS = [str(i) for i in range(12)]
HATS = ['H0', 'H1', 'H2', 'H3']  # up, right, down, left
HAT_LABELS = {'H0': 'up', 'H1': 'right', 'H2': 'down', 'H3': 'left'}
AXES = range(6)


def onAppStart(app):
    app.width, app.height = 800, 600
    app.stepsPerSecond = 30
    app.held = set()  # (joystick, button) pairs currently held
    app.axes = {}  # (joystick, axis) -> latest value
    app.log = []  # recent event descriptions
    app.dot = [400, 520]  # dot you can drive with the first stick or the D-pad
    app.dotMove = [0, 0]
    app.quitCombo = set()


def note(app, text):
    app.log.append(text)
    del app.log[:-9]


def onJoyPress(app, button, joystick):
    app.held.add((joystick, button))
    note(app, f'J{joystick} press {button}')
    app.quitCombo.add(button)
    if {'8', '9'} <= app.quitCombo:
        app.quit()


def onJoyRelease(app, button, joystick):
    app.held.discard((joystick, button))
    app.quitCombo.discard(button)
    note(app, f'J{joystick} release {button}')


def onJoyAxis(app, value, axis, joystick):
    old = app.axes.get((joystick, axis), 0)
    app.axes[(joystick, axis)] = value
    if abs(value - old) > 0.5:  # don't flood the log with small wiggles
        note(app, f'J{joystick} axis {axis} = {value:.2f}')


def onDigitalJoyAxis(app, directions, joystick):
    app.dotMove = [0, 0]
    for axis, d in directions:
        if axis == 0:
            app.dotMove[0] = d
        if axis == 1:
            app.dotMove[1] = d


def onJoyButtonHold(app, buttons, joystick):
    for b, (dx, dy) in {
        'H0': (0, -1),
        'H1': (1, 0),
        'H2': (0, 1),
        'H3': (-1, 0),
    }.items():
        if b in buttons:
            app.dot[0] += dx * 6
            app.dot[1] += dy * 6


def onKeyPress(app, key):
    if key == 'escape':
        app.quit()


def onStep(app):
    app.dot[0] = max(10, min(790, app.dot[0] + app.dotMove[0] * 6))
    app.dot[1] = max(430, min(590, app.dot[1] + app.dotMove[1] * 6))


def anyHeld(app, button):
    return any(b == button for (_, b) in app.held)


def redrawAll(app):
    drawRect(0, 0, 800, 600, fill='midnightBlue')
    drawLabel('Joystick Tester', 400, 24, size=26, fill='white', bold=True)

    # Connected devices
    if joystick.devices:
        for i, (id, name) in enumerate(sorted(joystick.devices.items())):
            drawLabel(
                f'J{id}: {name}',
                20,
                80 + 18 * i,
                size=14,
                fill='lightGreen',
                align='left',
            )
    else:
        drawLabel(
            'No joystick connected. Plug one in (or press a button on it).',
            20,
            80,
            size=14,
            fill='orange',
            align='left',
        )

    # Buttons 0..11
    drawLabel('Buttons', 20, 150, size=14, fill='white', align='left', bold=True)
    for i, b in enumerate(BUTTONS):
        x, y = 50 + 58 * i, 185
        drawCircle(
            x, y, 22, fill='gold' if anyHeld(app, b) else 'slateGray', border='white'
        )
        drawLabel(b, x, y, size=16, fill='black' if anyHeld(app, b) else 'white')

    # D-pad / hat
    drawLabel('D-pad (hat)', 20, 240, size=14, fill='white', align='left', bold=True)
    for h, (dx, dy) in zip(HATS, [(0, -1), (1, 0), (0, 1), (-1, 0)]):
        x, y = 90 + dx * 34, 295 + dy * 34
        drawRect(
            x - 15,
            y - 15,
            30,
            30,
            fill='gold' if anyHeld(app, h) else 'slateGray',
            border='white',
        )
        drawLabel(
            HAT_LABELS[h][0].upper(), x, y, fill='black' if anyHeld(app, h) else 'white'
        )

    # Axes 0..5 as bars
    drawLabel('Axes', 220, 240, size=14, fill='white', align='left', bold=True)
    for a in AXES:
        v = max([app.axes.get((j, a), 0) for j in joystick.devices] or [0], key=abs)
        y = 262 + 22 * a
        drawLabel(f'{a}', 225, y, size=13, fill='white')
        drawRect(250, y - 7, 200, 14, fill=None, border='white')
        drawLine(350, y - 7, 350, y + 7, fill='white')
        drawRect(350 + min(0, v) * 100, y - 6, abs(v) * 100, 12, fill='deepSkyBlue')
        drawLabel(f'{v:+.2f}', 490, y, size=13, fill='white', align='left')

    # Event log
    drawLabel('Recent events', 560, 150, size=14, fill='white', align='left', bold=True)
    for i, line in enumerate(reversed(app.log)):
        drawLabel(line, 560, 175 + 17 * i, size=13, fill='white', align='left')

    # Raw debug lines, if CMU_JOY_DEBUG=1
    for i, line in enumerate(joystick.debugLog[-4:]):
        drawLabel(line[:110], 20, 395 + 14 * i, size=11, fill='gray', align='left')

    # A dot to drive around
    drawRect(5, 425, 790, 170, fill=None, border='slateGray')
    drawLabel(
        'Drive the dot with a stick or the D-pad', 400, 440, size=12, fill='slateGray'
    )
    drawCircle(app.dot[0], app.dot[1], 10, fill='tomato')


runApp()
