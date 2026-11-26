"""Gamepad support for cmu_graphics. Import it, then define any of these:

    onJoyPress(app, button, joystick)       onJoyRelease(app, button, joystick)
    onJoyButtonHold(app, buttons, joystick) called every step while buttons are held
    onJoyAxis(app, value, axis, joystick)
    onDigitalJoyAxis(app, directions, joystick)  every step, a list of (axis, -1 or 1)

Every pad uses the Xbox controller layout. Buttons are strings:
    '0' A, '1' B, '2' X, '3' Y, '4' LB, '5' RB, '6' Back, '7' Start, '8' Guide,
    '9' left stick click, '10' right stick click,
    'H0' D-pad up, 'H1' right, 'H2' down, 'H3' left
Axes: 0/1 left stick x/y, 3/4 right stick x/y, from -1 to 1 with down and right positive;
2/5 left/right trigger, from 0 to 1.
"""

import os

from cmu_graphics import onMainLoopEvent, onStepEvent

# Set CMU_JOY_DEBUG=1 to keep the last 50 raw backend events in joystick.debugLog.
debugLog = []

try:
    from cmu_graphics.deps import cmu_graphics_helpers

    _native = cmu_graphics_helpers.joystick.Joysticks(
        debug=bool(os.environ.get('CMU_JOY_DEBUG'))
    )
except (ImportError, AttributeError):
    _native = None
    print(
        "joystick.py: this version of cmu_graphics doesn't include joystick support, so it "
        "is disabled. (Your program will still run; joystick callbacks just won't be called.)"
    )
except Exception as e:  # e.g. gilrs couldn't start
    _native = None
    print(
        f"joystick.py: couldn't start the joystick module ({e}), so joystick support is "
        'disabled. (Your program will still run.)'
    )

devices = dict()  # instance id -> name, for the joysticks that are currently connected

# All keyed by instance id
_buttonsDown = dict()  # set of buttons held
_hats = dict()  # the D-pad's latest (x, y)
_digitalAxes = dict()  # axis -> -1, 0 or 1
_digitalAxesDown = dict()  # set of (axis, direction) for the axes that aren't 0
# After all digital axes are released, onDigitalJoyAxis gets called one more time with an
# empty list, so that the app can tell they were released.
_digitalAxesSendEmpty = dict()

# H0 up, H1 right, H2 down, H3 left: (hat index, direction)
_HAT_BUTTONS = {'H0': (1, 1), 'H1': (0, 1), 'H2': (1, -1), 'H3': (0, -1)}


def _added(id, name):
    devices[id] = name
    _buttonsDown[id] = set()
    _hats[id] = (0, 0)
    _digitalAxes[id] = dict()
    _digitalAxesDown[id] = set()
    _digitalAxesSendEmpty[id] = False
    _native.rumble(id, 0, 0.7, 500)  # Does nothing if the pad can't rumble


def _removed(id, callUserFn):
    # Release whatever was held, so the app doesn't think it still is
    for button in sorted(_buttonsDown[id]):
        _release(button, id, callUserFn)
    if _digitalAxesDown[id]:
        callUserFn('onDigitalJoyAxis', ([], id))
    for state in (
        devices,
        _buttonsDown,
        _hats,
        _digitalAxes,
        _digitalAxesDown,
        _digitalAxesSendEmpty,
    ):
        del state[id]


def _press(button, id, callUserFn):
    _buttonsDown[id].add(button)
    callUserFn('onJoyPress', (button, id))


def _release(button, id, callUserFn):
    _buttonsDown[id].discard(button)
    callUserFn('onJoyRelease', (button, id))


# The D-pad is reported as a hat, and turned into the buttons H0-H3
def _hat(value, id, callUserFn):
    prev, _hats[id] = _hats[id], value
    for button, (i, direction) in _HAT_BUTTONS.items():
        if prev[i] == direction and value[i] != direction:
            _release(button, id, callUserFn)
    for button, (i, direction) in _HAT_BUTTONS.items():
        if value[i] == direction and prev[i] != direction:
            _press(button, id, callUserFn)


def _digitalAxis(value, axis, id):
    # Treat the axis as digital, which many are
    direction = 1 if value > 0.5 else -1 if value < -0.5 else 0
    prev = _digitalAxes[id].get(axis, 0)
    if direction != prev:
        _digitalAxes[id][axis] = direction
        _digitalAxesDown[id].discard((axis, prev))
        if direction != 0:
            _digitalAxesDown[id].add((axis, direction))


def _handle(event, callUserFn):
    kind, id = event[0], event[1]
    if kind == 'added':
        _added(id, event[2])
    elif id not in devices:
        return
    elif kind == 'removed':
        _removed(id, callUserFn)
    elif kind == 'down':
        _press(str(event[2]), id, callUserFn)
    elif kind == 'up':
        _release(str(event[2]), id, callUserFn)
    elif kind == 'hat':
        _hat(event[2], id, callUserFn)
    elif kind == 'axis':
        axis, value = event[2], event[3]
        _digitalAxis(value, axis, id)
        callUserFn('onJoyAxis', (value, axis, id))


# The R36S launcher sets CMU_R36S_JOY=1 (see STUDENT_GUIDE.md). The R36S gamepad isn't in
# SDL's controller database, so its buttons arrive in hardware order. This puts them in
# the Xbox layout like every other pad. Pressing Select and Start together quits.
R36S = _native is not None and os.environ.get('CMU_R36S_JOY') == '1'
R36S_BUTTONS = {
    0: 0,  # a
    1: 1,  # b
    2: 2,  # x
    3: 3,  # y
    4: 4,  # L1
    5: 5,  # R1
    12: 6,  # Select
    13: 7,  # Start
    14: 9,  # L3
    15: 10,  # R3
}
R36S_TRIGGERS = {6: 2, 7: 5}  # L2/R2 -> trigger axes
R36S_UP, R36S_DOWN, R36S_LEFT, R36S_RIGHT = 8, 9, 10, 11
R36S_SELECT, R36S_START = 12, 13
_r36sHeld = set()


def _translateR36S(event, app):
    """Returns the Xbox layout version of an R36S gamepad event, as a list of events."""
    kind = event[0]
    if kind == 'removed':
        _r36sHeld.clear()
    if kind not in ('down', 'up'):
        return [event]
    id, b = event[1], event[2]
    if kind == 'down':
        _r36sHeld.add(b)
    else:
        _r36sHeld.discard(b)
    if R36S_SELECT in _r36sHeld and R36S_START in _r36sHeld:
        app.quit()
        return []
    if b in R36S_BUTTONS:
        return [(kind, id, R36S_BUTTONS[b])]
    if b in R36S_TRIGGERS:
        return [('axis', id, R36S_TRIGGERS[b], 1.0 if kind == 'down' else 0.0)]
    if b in (R36S_UP, R36S_DOWN, R36S_LEFT, R36S_RIGHT):
        held = _r36sHeld.__contains__
        x = held(R36S_RIGHT) - held(R36S_LEFT)
        y = held(R36S_UP) - held(R36S_DOWN)
        return [('hat', id, (x, y))]
    return [event]


# Runs every time through the main loop, even while the app is paused, like key presses
def _readEvents(msPassed, callUserFn, app):
    events = _native.poll()
    debugLog.extend(_native.debug_log())
    del debugLog[:-50]
    for event in events:
        for e in _translateR36S(event, app) if R36S else [event]:
            if app._app.stopped:  # e.g. a callback raised an error
                return
            _handle(e, callUserFn)


def _sendHolds(callUserFn, app):
    for id, buttons in _buttonsDown.items():
        if buttons:
            callUserFn('onJoyButtonHold', (list(buttons), id))
    for id, directions in _digitalAxesDown.items():
        if directions:
            callUserFn('onDigitalJoyAxis', (list(directions), id))
            _digitalAxesSendEmpty[id] = True
        elif _digitalAxesSendEmpty[id]:
            callUserFn('onDigitalJoyAxis', ([], id))
            _digitalAxesSendEmpty[id] = False


if _native is not None:
    onMainLoopEvent.connect(_readEvents)
    onStepEvent.connect(_sendHolds)
