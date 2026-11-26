"""Prints gamepad events for 30 seconds, and rumbles each pad as it connects.

Usage: python test_joystick.py [--debug]   (with cmu_graphics_helpers installed)
--debug also prints the raw gilrs events, including the ones that don't map to anything.
"""

import sys
import time
from cmu_graphics_helpers.joystick import Joysticks

debug = '--debug' in sys.argv
j = Joysticks(debug=debug)
end = time.time() + 30
print('Polling for 30s; plug in / press things on a gamepad...')
while time.time() < end:
    events = j.poll()
    for line in j.debug_log():
        print('  raw', line)
    for ev in events:
        print(ev)
        if ev[0] == 'added':
            print('  rumble:', j.rumble(ev[1], 0.0, 0.7, 500))
    time.sleep(1 / 60)
