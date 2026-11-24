import os

from cmu_graphics import almostEqual, onStepEvent

# Set CMU_JOY_DEBUG=1 to keep a log of raw backend events in joystick.debugLog.
debugLog = []

try:
    from cmu_graphics_joystick import Joysticks

    _native = Joysticks(debug=bool(os.environ.get('CMU_JOY_DEBUG')))
except ImportError:
    _native = None
    print(
        'joystick.py: cmu_graphics_joystick is not installed, so joystick support is '
        "disabled. (Your program will still run; joystick callbacks just won't be called.)"
    )
except Exception as e:  # e.g. gilrs couldn't start
    _native = None
    print(
        f"joystick.py: couldn't start the joystick module ({e}), so joystick support is "
        'disabled. (Your program will still run.)'
    )

_allJoyButtonsDown = dict()
_allDigitalJoyAxisDown = dict()
_lastJoyAxis = dict()
devices = dict()  # instance id -> name, for the joysticks that are currently connected

# If this user releases all joystick presses, trigger
# onDigitalJoyAxis one more time with an empty list
# so that we can tell it was released.
_digitalJoyAxisSendEmpty = dict()


class JoyEvent:
    """type is 'added', 'removed', 'down', 'up', 'hat' or 'axis'."""

    def __init__(self, type, instance_id, button=None, axis=None, value=None, name=''):
        self.type, self.instance_id, self.button = type, instance_id, button
        self.axis, self.value, self.name = axis, value, name


def _rumble(instanceId, strong, weak, ms):
    _native.rumble(instanceId, strong, weak, ms)  # Does nothing if it can't rumble


def handleJoyEvent(event, callUserFn, app):
    id = event.instance_id
    if event.type == 'added':
        devices[id] = event.name
        _allJoyButtonsDown[id] = set()
        _allDigitalJoyAxisDown[id] = set()
        _digitalJoyAxisSendEmpty[id] = False
        _rumble(id, 0, 0.7, 500)  # Rumble if it can and is connected
    elif event.type == 'removed':
        devices.pop(id, None)
        _lastJoyAxis.pop(f'J{id}H', None)
        _allJoyButtonsDown.pop(id, None)
        _allDigitalJoyAxisDown.pop(id, None)
        _digitalJoyAxisSendEmpty.pop(id, None)
    elif id not in _allJoyButtonsDown:
        return  # An event from a joystick we never saw connect
    elif event.type == 'down':
        handleJoyPress(str(event.button), id, callUserFn)
    elif event.type == 'up':
        handleJoyRelease(str(event.button), id, callUserFn)
    elif event.type == 'hat':
        handleJoyHat(event.value, id, callUserFn)
    elif event.type == 'axis':
        handleDigitalJoyAxis(event.value, event.axis, id)
        callUserFn('onJoyAxis', (event.value, event.axis, id))


def fromNativeEvent(raw):
    kind, id, a, b = raw
    if kind == 'added':
        return JoyEvent('added', id, name=a)
    if kind == 'removed':
        return JoyEvent('removed', id)
    if kind in ('down', 'up'):
        return JoyEvent(kind, id, button=a)
    if kind == 'hat':
        return JoyEvent('hat', id, value=b)
    if kind == 'axis':
        return JoyEvent('axis', id, axis=a, value=b)
    if kind == 'raw':
        debugLog.append(f'J{id} {a}')
        del debugLog[:-50]
    return None


# The R36S launcher sets CMU_R36S_JOY=1 to renumber the R36S gamepad like the CMU arcade
# box (see STUDENT_GUIDE.md). a/b/x/y, L1/R1 and L2/R2 already match; Select/Start move
# to 8/9 like the arcade box; L3/R3 take 10/11. The D-pad becomes axes 0/1, like the
# left stick. Pressing Select and Start together quits.
R36S = _native is not None and os.environ.get('CMU_R36S_JOY') == '1'
R36S_BUTTONS = {
    0: 0,
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6,
    7: 7,
    12: 8,
    13: 9,
    14: 10,
    15: 11,
}
R36S_DPAD = {
    8: (1, -1),
    9: (1, 1),
    10: (0, -1),
    11: (0, 1),
}  # raw button -> (axis, direction)
R36S_SELECT, R36S_START = 12, 13
_r36sHeld = set()


def translateR36S(event, app):
    """Returns the arcade box version of an R36S gamepad event, or None to drop it."""
    if event.type not in ('down', 'up'):
        return event
    b = event.button
    if event.type == 'down':
        _r36sHeld.add(b)
    else:
        _r36sHeld.discard(b)
    if R36S_SELECT in _r36sHeld and R36S_START in _r36sHeld:
        app.quit()
        return None
    if b in R36S_DPAD:
        axis = R36S_DPAD[b][0]
        neg, pos = (10, 11) if axis == 0 else (8, 9)
        value = float((pos in _r36sHeld) - (neg in _r36sHeld))
        return JoyEvent('axis', event.instance_id, axis=axis, value=value)
    if b in R36S_BUTTONS:
        return JoyEvent(event.type, event.instance_id, button=R36S_BUTTONS[b])
    return event


def readJoyEvents(callUserFn, app):
    for raw in _native.poll():
        event = fromNativeEvent(raw)
        if event is not None and R36S:
            event = translateR36S(event, app)
        if event is not None:
            handleJoyEvent(event, callUserFn, app)


def handleOnStepEvent(callUserFn, app):
    readJoyEvents(callUserFn, app)
    for joystick in _allJoyButtonsDown:
        if len(_allJoyButtonsDown[joystick]) > 0:
            callUserFn(
                'onJoyButtonHold', (list(_allJoyButtonsDown[joystick]), joystick)
            )
    for joystick in _allDigitalJoyAxisDown:
        if len(_allDigitalJoyAxisDown[joystick]) > 0:
            callUserFn(
                'onDigitalJoyAxis', (list(_allDigitalJoyAxisDown[joystick]), joystick)
            )
            _digitalJoyAxisSendEmpty[joystick] = True
        elif _digitalJoyAxisSendEmpty[joystick]:
            callUserFn(
                'onDigitalJoyAxis', (list(_allDigitalJoyAxisDown[joystick]), joystick)
            )
            _digitalJoyAxisSendEmpty[joystick] = False


if _native is not None:
    onStepEvent.connect(handleOnStepEvent)


def handleJoyPress(button, joystick, callUserFn):
    _allJoyButtonsDown[joystick].add(button)
    callUserFn('onJoyPress', (button, joystick))


def handleJoyRelease(button, joystick, callUserFn):
    if button in _allJoyButtonsDown[joystick]:
        _allJoyButtonsDown[joystick].remove(button)
    callUserFn('onJoyRelease', (button, joystick))


def handleDigitalJoyAxisPress(value, axis, joystick):
    _allDigitalJoyAxisDown[joystick].add((axis, value))


def handleDigitalJoyAxisRelease(value, axis, joystick):
    if (axis, value) in _allDigitalJoyAxisDown[joystick]:
        _allDigitalJoyAxisDown[joystick].remove((axis, value))


# Hats are just DPADs, so we'll handle them like buttons
def handleJoyHat(values, joystick, callUserFn):
    # We will index the _lastJoyAxis dict using the joystick and H for hat
    key = f'J{joystick}H'
    prev = _lastJoyAxis.get(key, (0, 0))

    # Only signal a button press if it is newly pressed.
    # You can get (0,1) followed by (1,1), meaning one of the buttons stayed pressed.
    if values[1] == 1 and prev[1] != 1:
        handleJoyPress('H0', joystick, callUserFn)
    elif values[1] == -1 and prev[1] != -1:
        handleJoyPress('H2', joystick, callUserFn)

    if values[1] == 0 and prev[1] == 1:
        handleJoyRelease('H0', joystick, callUserFn)
    elif values[1] == 0 and prev[1] == -1:
        handleJoyRelease('H2', joystick, callUserFn)

    if values[0] == 1 and prev[0] != 1:
        handleJoyPress('H1', joystick, callUserFn)
    elif values[0] == -1 and prev[0] != -1:
        handleJoyPress('H3', joystick, callUserFn)

    if values[0] == 0 and prev[0] == 1:
        handleJoyRelease('H1', joystick, callUserFn)
    elif values[0] == 0 and prev[0] == -1:
        handleJoyRelease('H3', joystick, callUserFn)

    _lastJoyAxis[key] = values


def handleDigitalJoyAxis(value, axis, joystick):
    # We are going to treat this as a digital, which many are.
    if almostEqual(value, 0, 0.5):
        value = 0
    elif almostEqual(value, 1, 0.5):
        value = 1
    elif almostEqual(value, -1, 0.5):
        value = -1
    else:
        return

    # We will index the _lastJoyAxis dict using the joystick and axis
    key = f'J{joystick}A{axis}'
    prev = _lastJoyAxis.get(key, 0)

    # Control stick was pushed in a direction
    if value != 0 and prev == 0:
        handleDigitalJoyAxisPress(value, axis, joystick)

    # Control stick was released in that direction
    if value == 0 and prev != 0:
        handleDigitalJoyAxisRelease(prev, axis, joystick)

    _lastJoyAxis[key] = value
