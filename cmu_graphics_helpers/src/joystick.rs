//! Gamepad input for cmu_graphics, built on gilrs. Exposed as cmu_graphics_helpers.joystick.
//!
//! Every pad is reported in the Xbox controller layout (SDL's GameController layout):
//!   buttons  0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 Back, 7 Start, 8 Guide, 9 LS, 10 RS
//!   axes     0 LX, 1 LY, 3 RX, 4 RY: -1.0..1.0, down and right positive
//!            2 LT, 5 RT: 0.0 released .. 1.0 fully pressed (digital triggers jump 0 -> 1)
//!   D-pad    a hat, (x, y) in -1/0/1 with y positive up
//! gilrs works out where a pad's buttons are from SDL's controller database or from the
//! driver's button codes. Buttons with no place in that layout (C, Z, paddles, ...) are
//! dropped. A pad with no A button at all, which is how gilrs sees an arcade encoder that
//! isn't in the database, gets its buttons numbered in hardware order instead, so that
//! it is still usable; see `button_index`.
//!
//! `Joysticks.poll()` returns a list of tuples:
//!   ("added", id, name)      ("removed", id)
//!   ("down", id, button)     ("up", id, button)
//!   ("axis", id, axis, value)
//!   ("hat", id, (x, y))
//! ids count up from 0 and are never reused, like pygame's instance ids.
use gilrs::ff::{BaseEffect, BaseEffectType, Effect, EffectBuilder, Repeat, Replay, Ticks};
use gilrs::{Axis, Button, EventType, GamepadId, Gilrs};
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyList;
use std::collections::HashMap;

fn xbox_button(b: Button) -> Option<u32> {
    Some(match b {
        Button::South => 0,
        Button::East => 1,
        Button::West => 2,
        Button::North => 3,
        Button::LeftTrigger => 4,
        Button::RightTrigger => 5,
        Button::Select => 6,
        Button::Start => 7,
        Button::Mode => 8,
        Button::LeftThumb => 9,
        Button::RightThumb => 10,
        _ => return None,
    })
}

/// A button's position on a pad with no Xbox layout, from its platform-specific code.
#[cfg(target_os = "linux")]
fn button_index(code: u32) -> Option<u32> {
    // evdev: EV_KEY << 16 | key code. Joystick buttons start at BTN_JOYSTICK, so this is
    // SDL's raw joystick numbering for the usual encoder, whose buttons have no gaps.
    const EV_KEY: u32 = 1;
    const BTN_JOYSTICK: u32 = 0x120;
    let (kind, key) = (code >> 16, code & 0xffff);
    (kind == EV_KEY && key >= BTN_JOYSTICK).then(|| key - BTN_JOYSTICK)
}

#[cfg(target_os = "macos")]
fn button_index(code: u32) -> Option<u32> {
    // IOKit: HID usage page << 16 | usage. Usages on the Button page count up from 1.
    const PAGE_BUTTON: u32 = 0x09;
    let (page, usage) = (code >> 16, code & 0xffff);
    (page == PAGE_BUTTON && usage >= 1).then(|| usage - 1)
}

#[cfg(target_os = "windows")]
fn button_index(code: u32) -> Option<u32> {
    // Windows.Gaming.Input: kind << 16 | index, and kind 0 is a button
    (code >> 16 == 0).then_some(code & 0xffff)
}

#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
fn button_index(_code: u32) -> Option<u32> {
    None
}

/// gilrs scales a trigger on Z/RZ to -1..1. It centers odd ranges like 0..255, so a
/// released trigger comes out a hair above -1.
fn z_to_trigger(v: f32) -> f32 {
    let t = (v + 1.0) / 2.0;
    if t < 0.01 { 0.0 } else { t.min(1.0) }
}

struct Pad {
    /// The id Python sees
    num: usize,
    /// The pad has an A button, so gilrs knows its layout
    xbox: bool,
    /// LeftZ/RightZ are the triggers (the pad has a right stick elsewhere), not the right stick
    z_is_trigger: bool,
    /// D-pad left, right, up, down
    dpad: [bool; 4],
    hat: (i32, i32),
    /// Last values sent for axes 2 and 5
    triggers: [f32; 2],
    /// gilrs stops an effect when its last handle is dropped, so the current rumble lives here
    rumble: Option<Effect>,
}

impl Pad {
    /// Updates the D-pad and returns the new hat value if it changed
    fn set_dpad(&mut self, left: bool, right: bool, up: bool, down: bool) -> Option<(i32, i32)> {
        self.dpad = [left, right, up, down];
        let hat = (right as i32 - left as i32, up as i32 - down as i32);
        (hat != self.hat).then(|| {
            self.hat = hat;
            hat
        })
    }

    /// Returns the axis event for a trigger's new value, if it changed
    fn set_trigger(&mut self, right: bool, v: f32) -> Option<Out> {
        let (slot, axis) = if right { (&mut self.triggers[1], 5) } else { (&mut self.triggers[0], 2) };
        (*slot != v).then(|| {
            *slot = v;
            Out::Axis(axis, v)
        })
    }
}

enum Out {
    Button(u32, bool),
    Axis(u32, f32),
    Hat((i32, i32)),
}

#[pyclass(unsendable)]
pub struct Joysticks {
    gilrs: Gilrs,
    pads: HashMap<GamepadId, Pad>,
    next_num: usize,
    initial_sent: bool,
    debug: Option<Vec<String>>,
}

impl Joysticks {
    fn add_pad(&mut self, gid: GamepadId) -> Option<(usize, String)> {
        if self.pads.contains_key(&gid) {
            return None;
        }
        let gp = self.gilrs.connected_gamepad(gid)?;
        let name = gp.name().to_string();
        let pad = Pad {
            num: self.next_num,
            xbox: gp.button_code(Button::South).is_some(),
            z_is_trigger: gp.axis_code(Axis::RightStickX).is_some(),
            dpad: [false; 4],
            hat: (0, 0),
            triggers: [0.0; 2],
            rumble: None,
        };
        if let Some(log) = &mut self.debug {
            log.push(format!(
                "J{} {:?} {:?} {:?} layout={}",
                pad.num,
                name,
                gp.uuid(),
                gp.mapping_source(),
                if pad.xbox { "xbox" } else { "hardware order" },
            ));
        }
        self.next_num += 1;
        let num = pad.num;
        self.pads.insert(gid, pad);
        Some((num, name))
    }

    fn translate(gilrs: &Gilrs, gid: GamepadId, pad: &mut Pad, event: EventType) -> Option<Out> {
        use Button::{LeftTrigger2, RightTrigger2};
        let [left, right, up, down] = pad.dpad;
        match event {
            // Triggers, analog or digital, are axes. gilrs sends the value in ButtonChanged,
            // except on a trigger's first press, where it starts its state at 1.0 and so drops
            // the ButtonChanged(1.0) that follows. Its state is right either way.
            EventType::ButtonPressed(b @ (LeftTrigger2 | RightTrigger2), code)
            | EventType::ButtonReleased(b @ (LeftTrigger2 | RightTrigger2), code)
            | EventType::ButtonChanged(b @ (LeftTrigger2 | RightTrigger2), _, code) => {
                let v = gilrs.gamepad(gid).state().value(code);
                pad.set_trigger(b == RightTrigger2, v)
            }
            EventType::ButtonPressed(b, code) | EventType::ButtonReleased(b, code) => {
                let pressed = matches!(event, EventType::ButtonPressed(..));
                match b {
                    Button::DPadLeft => pad.set_dpad(pressed, right, up, down).map(Out::Hat),
                    Button::DPadRight => pad.set_dpad(left, pressed, up, down).map(Out::Hat),
                    Button::DPadUp => pad.set_dpad(left, right, pressed, down).map(Out::Hat),
                    Button::DPadDown => pad.set_dpad(left, right, up, pressed).map(Out::Hat),
                    _ if pad.xbox => xbox_button(b).map(|n| Out::Button(n, pressed)),
                    _ => button_index(code.into_u32()).map(|n| Out::Button(n, pressed)),
                }
            }
            // gilrs has up positive on the stick Y axes, and the Xbox layout has down positive
            EventType::AxisChanged(Axis::LeftStickX, v, _) => Some(Out::Axis(0, v)),
            EventType::AxisChanged(Axis::LeftStickY, v, _) => Some(Out::Axis(1, -v)),
            EventType::AxisChanged(Axis::RightStickX, v, _) => Some(Out::Axis(3, v)),
            EventType::AxisChanged(Axis::RightStickY, v, _) => Some(Out::Axis(4, -v)),
            // Pads gilrs has no mapping for put either the triggers or the right stick on Z/RZ.
            // Like SDL, call them triggers if the pad has a right stick on RX/RY. gilrs scales
            // them to -1..1 and leaves them unflipped.
            EventType::AxisChanged(Axis::LeftZ, v, _) if pad.z_is_trigger => {
                pad.set_trigger(false, z_to_trigger(v))
            }
            EventType::AxisChanged(Axis::RightZ, v, _) if pad.z_is_trigger => {
                pad.set_trigger(true, z_to_trigger(v))
            }
            EventType::AxisChanged(Axis::LeftZ, v, _) => Some(Out::Axis(3, v)),
            EventType::AxisChanged(Axis::RightZ, v, _) => Some(Out::Axis(4, v)),
            // gilrs usually turns these into D-pad buttons, but not if the pad has both
            EventType::AxisChanged(Axis::DPadX, v, _) => {
                pad.set_dpad(v < -0.5, v > 0.5, up, down).map(Out::Hat)
            }
            EventType::AxisChanged(Axis::DPadY, v, _) => {
                pad.set_dpad(left, right, v > 0.5, v < -0.5).map(Out::Hat)
            }
            _ => None,
        }
    }
}

#[pymethods]
impl Joysticks {
    #[new]
    #[pyo3(signature = (debug=false))]
    fn new(debug: bool) -> PyResult<Self> {
        let gilrs = Gilrs::new()
            .map_err(|e| PyRuntimeError::new_err(format!("couldn't start gilrs: {e}")))?;
        Ok(Joysticks {
            gilrs,
            pads: HashMap::new(),
            next_num: 0,
            initial_sent: false,
            debug: debug.then(Vec::new),
        })
    }

    fn poll<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let out = PyList::empty(py);
        if !self.initial_sent {
            // gilrs doesn't send Connected for pads that were already plugged in
            self.initial_sent = true;
            let present: Vec<GamepadId> = self.gilrs.gamepads().map(|(id, _)| id).collect();
            for gid in present {
                if let Some((num, name)) = self.add_pad(gid) {
                    out.append(("added", num, name))?;
                }
            }
        }
        while let Some(ev) = self.gilrs.next_event() {
            match ev.event {
                EventType::Connected => {
                    if let Some((num, name)) = self.add_pad(ev.id) {
                        out.append(("added", num, name))?;
                    }
                    continue;
                }
                EventType::Disconnected => {
                    if let Some(pad) = self.pads.remove(&ev.id) {
                        out.append(("removed", pad.num))?;
                    }
                    continue;
                }
                _ => {}
            }
            let Some(pad) = self.pads.get_mut(&ev.id) else { continue };
            if let Some(log) = &mut self.debug {
                log.push(format!("J{} {:?}", pad.num, ev.event));
            }
            match Self::translate(&self.gilrs, ev.id, pad, ev.event) {
                Some(Out::Button(n, true)) => out.append(("down", pad.num, n))?,
                Some(Out::Button(n, false)) => out.append(("up", pad.num, n))?,
                Some(Out::Axis(n, v)) => out.append(("axis", pad.num, n, v as f64))?,
                Some(Out::Hat(hat)) => out.append(("hat", pad.num, hat))?,
                None => {}
            }
        }
        Ok(out)
    }

    /// The raw gilrs events since the last call, if this was made with debug=True
    fn debug_log(&mut self) -> Vec<String> {
        self.debug.as_mut().map(std::mem::take).unwrap_or_default()
    }

    /// Rumbles for `ms` milliseconds, replacing any rumble already playing; ms=0 stops it.
    /// Returns False if the pad can't rumble.
    fn rumble(&mut self, id: usize, strong: f32, weak: f32, ms: u32) -> bool {
        let Some((&gid, pad)) = self.pads.iter_mut().find(|(_, p)| p.num == id) else {
            return false;
        };
        if !self.gilrs.connected_gamepad(gid).is_some_and(|g| g.is_ff_supported()) {
            return false;
        }
        pad.rumble = None; // stops the old one
        if ms == 0 {
            return true;
        }
        let scale = |x: f32| (x.clamp(0.0, 1.0) * 65535.0) as u16;
        let duration = Ticks::from_ms(ms);
        let scheduling = Replay { play_for: duration, ..Default::default() };
        let effect = EffectBuilder::new()
            .add_effect(BaseEffect {
                kind: BaseEffectType::Strong { magnitude: scale(strong) },
                scheduling,
                ..Default::default()
            })
            .add_effect(BaseEffect {
                kind: BaseEffectType::Weak { magnitude: scale(weak) },
                scheduling,
                ..Default::default()
            })
            // The default repeats forever
            .repeat(Repeat::For(duration))
            .gamepads(&[gid])
            .finish(&mut self.gilrs);
        let Ok(effect) = effect else { return false };
        let played = effect.play().is_ok();
        pad.rumble = Some(effect);
        played
    }
}
