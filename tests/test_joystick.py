"""Tests joystick.py's event handling against a fake backend, so no gamepad is needed."""

import os
import sys

# joystick.py lives at the top of the repo. Appended, so the installed cmu_graphics wins.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import joystick  # noqa: E402


class FakeNative:
    def __init__(self):
        self.events = []
        self.rumbles = []

    def poll(self):
        events, self.events = self.events, []
        return events

    def debug_log(self):
        return []

    def rumble(self, id, strong, weak, ms):
        self.rumbles.append(id)
        return False


class FakeApp:
    class _app:
        stopped = False

    quits = 0

    def quit(self):
        FakeApp.quits += 1


calls = []


def callUserFn(name, args):
    calls.append((name, args))


def run(*events, step=False):
    """Feeds events through one main loop pass (and one step), returning the callbacks."""
    calls.clear()
    joystick._native.events = list(events)
    joystick._readEvents(0, callUserFn, FakeApp())
    if step:
        joystick._sendHolds(callUserFn, FakeApp())
    return list(calls)


joystick._native = FakeNative()

# Connecting rumbles, and pads get their own state
assert run(('added', 0, 'Pad A'), ('added', 1, 'Pad B')) == []
assert joystick.devices == {0: 'Pad A', 1: 'Pad B'}
assert joystick._native.rumbles == [0, 1]

# Buttons are strings, and holds are reported each step
assert run(('down', 0, 3), step=True) == [
    ('onJoyPress', ('3', 0)),
    ('onJoyButtonHold', (['3'], 0)),
]
assert run(('up', 0, 3), step=True) == [('onJoyRelease', ('3', 0))]

# Events from a pad that never connected are ignored
assert run(('down', 7, 0)) == []

# Hat: pressing up, then sliding straight to down releases up
assert run(('hat', 0, (0, 1))) == [('onJoyPress', ('H0', 0))]
assert run(('hat', 0, (1, -1))) == [
    ('onJoyRelease', ('H0', 0)),
    ('onJoyPress', ('H1', 0)),
    ('onJoyPress', ('H2', 0)),
]
assert run(('hat', 0, (0, 0))) == [
    ('onJoyRelease', ('H1', 0)),
    ('onJoyRelease', ('H2', 0)),
]

# Digital axes: a stick flicked from one side straight to the other
run(('axis', 0, 0, -1.0))
assert joystick._digitalAxesDown[0] == {(0, -1)}
assert run(('axis', 0, 0, 1.0), step=True) == [
    ('onJoyAxis', (1.0, 0, 0)),
    ('onDigitalJoyAxis', ([(0, 1)], 0)),
]
assert run(('axis', 0, 0, 0.1), step=True) == [
    ('onJoyAxis', (0.1, 0, 0)),
    ('onDigitalJoyAxis', ([], 0)),  # one last empty list after release
]
assert run(step=True) == []

# Triggers rest at 0, so an untouched trigger isn't held
run(('axis', 0, 2, 0.0))
assert joystick._digitalAxesDown[0] == set()
run(('axis', 0, 2, 1.0))
assert joystick._digitalAxesDown[0] == {(2, 1)}
run(('axis', 0, 2, 0.0))

# Unplugging releases whatever was held and forgets the pad
run(('down', 1, 0), ('hat', 1, (-1, 0)), ('axis', 1, 1, 1.0))
assert run(('removed', 1)) == [
    ('onJoyRelease', ('0', 1)),
    ('onJoyRelease', ('H3', 1)),
    ('onDigitalJoyAxis', ([], 1)),
]
assert 1 not in joystick.devices and 1 not in joystick._digitalAxes
assert run(('down', 1, 0)) == []

# Nothing reaches the app once it has stopped
FakeApp._app.stopped = True
assert run(('down', 0, 0)) == []
FakeApp._app.stopped = False

# R36S: hardware order to Xbox layout
joystick.R36S = True
assert run(('down', 0, 12), ('up', 0, 12)) == [
    ('onJoyPress', ('6', 0)),
    ('onJoyRelease', ('6', 0)),
]
assert run(('down', 0, 6)) == [('onJoyAxis', (1.0, 2, 0))]  # L2
run(('up', 0, 6))
assert run(('down', 0, 8), ('down', 0, 11)) == [
    ('onJoyPress', ('H0', 0)),
    ('onJoyPress', ('H1', 0)),
]
run(('up', 0, 8), ('up', 0, 11))
assert run(('down', 0, 12), ('down', 0, 13)) == [('onJoyPress', ('6', 0))]
assert FakeApp.quits == 1
joystick.R36S = False

print('joystick tests passed')
