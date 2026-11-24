"""Prints gamepad events for 30 seconds. Usage: python test_poll.py (module on sys.path)."""

import time
from cmu_graphics_joystick import Joysticks

j = Joysticks()
end = time.time() + 30
print('Polling for 30s; plug in / press things on a gamepad...')
while time.time() < end:
    for ev in j.poll():
        print(ev)
        if ev[0] == 'added':
            print('  rumble:', j.rumble(ev[1], 0.0, 0.7, 500))
    time.sleep(1 / 60)
