//! Gamepad input for cmu_graphics, built on gilrs.
//!
//! `Joysticks.poll()` returns a list of tuples shaped like the pygame joystick events that
//! joystick.py already handles:
//!   ("added",   id, name,  0)
//!   ("removed", id, "",    0)
//!   ("down",    id, button, 0)    ("up", id, button, 0)
//!   ("axis",    id, axis,  value)  value is -1.0..1.0
//!   ("hat",     id, 0,     (x, y)) x/y in -1/0/1, y positive is up, like pygame
//! Button and axis numbers follow the pygame/SDL2 Xbox 360 layout.
use gilrs::ff::{BaseEffect, BaseEffectType, EffectBuilder, Replay, Ticks};
use gilrs::{Axis, Button, EventType, GamepadId, Gilrs};
use pyo3::prelude::*;
use pyo3::types::PyList;
use std::collections::HashMap;

fn button_number(b: Button) -> Option<u32> {
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

fn axis_number(a: Axis) -> Option<u32> {
    Some(match a {
        Axis::LeftStickX => 0,
        Axis::LeftStickY => 1,
        Axis::RightStickX => 3,
        Axis::RightStickY => 4,
        _ => return None,
    })
}

// Pads with no SDL mapping (many arcade encoders) report Button::Unknown / Axis::Unknown plus
// the raw evdev code, kind << 16 | code, with kind 1 = EV_KEY and 3 = EV_ABS. Numbering them
// like SDL's joystick API does is approximate: BTN_JOYSTICK (0x120) is button 0, and absolute
// axes use their evdev code. Use `debug=True` to see what the pad actually sends.
const EV_KEY: u32 = 1;
const EV_ABS: u32 = 3;
const BTN_JOYSTICK: u32 = 0x120;
const ABS_HAT0X: u32 = 16;
const ABS_HAT0Y: u32 = 17;

fn raw_button(code: u32) -> Option<u32> {
    let (kind, c) = (code >> 16, code & 0xffff);
    if kind != EV_KEY {
        return None;
    }
    Some(if c >= BTN_JOYSTICK { c - BTN_JOYSTICK } else { 64 + c })
}

#[derive(Default)]
struct Hat {
    left: bool,
    right: bool,
    up: bool,
    down: bool,
}

impl Hat {
    fn value(&self) -> (i32, i32) {
        (
            self.right as i32 - self.left as i32,
            self.up as i32 - self.down as i32,
        )
    }
}

#[pyclass(unsendable)]
struct Joysticks {
    gilrs: Gilrs,
    ids: HashMap<GamepadId, usize>,
    hats: HashMap<GamepadId, Hat>,
    initial_sent: bool,
    debug: bool,
}

#[pymethods]
impl Joysticks {
    #[new]
    #[pyo3(signature = (debug=false))]
    fn new(debug: bool) -> PyResult<Self> {
        let gilrs = Gilrs::new().map_err(|e| {
            pyo3::exceptions::PyRuntimeError::new_err(format!("couldn't start gilrs: {e}"))
        })?;
        Ok(Joysticks { gilrs, ids: HashMap::new(), hats: HashMap::new(), initial_sent: false, debug })
    }

    fn poll<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let out = PyList::empty(py);
        if !self.initial_sent {
            // gilrs doesn't send Connected for pads that were already plugged in
            self.initial_sent = true;
            let present: Vec<(GamepadId, String)> =
                self.gilrs.gamepads().map(|(id, g)| (id, g.name().to_string())).collect();
            for (id, name) in present {
                let n = self.ids.len();
                self.ids.insert(id, n);
                out.append(("added", n, name, 0).into_pyobject(py)?)?;
            }
        }
        while let Some(ev) = self.gilrs.next_event() {
            let next = self.ids.len();
            let known = self.ids.contains_key(&ev.id);
            match ev.event {
                EventType::Connected => {
                    if !known {
                        self.ids.insert(ev.id, next);
                        let name = self.gilrs.gamepad(ev.id).name().to_string();
                        out.append(("added", next, name, 0).into_pyobject(py)?)?;
                    }
                    continue;
                }
                EventType::Disconnected => {
                    if let Some(id) = self.ids.remove(&ev.id) {
                        self.hats.remove(&ev.id);
                        out.append(("removed", id, "", 0).into_pyobject(py)?)?;
                    }
                    continue;
                }
                _ => {}
            }
            let Some(&id) = self.ids.get(&ev.id) else { continue };
            if self.debug {
                out.append(("raw", id, format!("{:?}", ev.event), 0).into_pyobject(py)?)?;
            }
            match ev.event {
                EventType::ButtonPressed(b, c) | EventType::ButtonReleased(b, c) => {
                    let pressed = matches!(ev.event, EventType::ButtonPressed(..));
                    let hat = self.hats.entry(ev.id).or_default();
                    let is_dpad = match b {
                        Button::DPadLeft => { hat.left = pressed; true }
                        Button::DPadRight => { hat.right = pressed; true }
                        Button::DPadUp => { hat.up = pressed; true }
                        Button::DPadDown => { hat.down = pressed; true }
                        _ => false,
                    };
                    if is_dpad {
                        out.append(("hat", id, 0, hat.value()).into_pyobject(py)?)?;
                    } else if let Some(n) = button_number(b).or_else(|| raw_button(c.into_u32())) {
                        let kind = if pressed { "down" } else { "up" };
                        out.append((kind, id, n, 0).into_pyobject(py)?)?;
                    }
                }
                EventType::AxisChanged(Axis::Unknown, v, c) => {
                    let (kind, code) = (c.into_u32() >> 16, c.into_u32() & 0xffff);
                    if kind == EV_ABS && (code == ABS_HAT0X || code == ABS_HAT0Y) {
                        let hat = self.hats.entry(ev.id).or_default();
                        let dir = (v.round() as i32).clamp(-1, 1);
                        if code == ABS_HAT0X {
                            hat.left = dir < 0;
                            hat.right = dir > 0;
                        } else {
                            hat.up = dir < 0; // evdev hat Y is down positive
                            hat.down = dir > 0;
                        }
                        out.append(("hat", id, 0, hat.value()).into_pyobject(py)?)?;
                    } else if kind == EV_ABS {
                        out.append(("axis", id, code, v as f64).into_pyobject(py)?)?;
                    }
                }
                EventType::AxisChanged(a, v, _) => {
                    if let Some(n) = axis_number(a) {
                        // gilrs has up positive; pygame has down positive
                        let v = if matches!(a, Axis::LeftStickY | Axis::RightStickY) { -v } else { v };
                        out.append(("axis", id, n, v as f64).into_pyobject(py)?)?;
                    }
                }
                EventType::ButtonChanged(b, v, _) => {
                    // Analog triggers: SDL2 reports them as axes 2 and 5, rest 0.0 -> -1.0
                    let axis = match b {
                        Button::LeftTrigger2 => Some(2),
                        Button::RightTrigger2 => Some(5),
                        _ => None,
                    };
                    if let Some(n) = axis {
                        out.append(("axis", id, n, (v * 2.0 - 1.0) as f64).into_pyobject(py)?)?;
                    }
                }
                _ => {}
            }
        }
        Ok(out)
    }

    /// Rumbles for `ms` milliseconds. Returns False if the pad can't.
    fn rumble(&mut self, id: usize, strong: f32, weak: f32, ms: u32) -> bool {
        let Some((&gid, _)) = self.ids.iter().find(|&(_, &i)| i == id) else { return false };
        if !self.gilrs.gamepad(gid).is_ff_supported() {
            return false;
        }
        let scale = |x: f32| (x.clamp(0.0, 1.0) * 65535.0) as u16;
        let play_for = Replay { play_for: Ticks::from_ms(ms), ..Default::default() };
        let effect = EffectBuilder::new()
            .add_effect(BaseEffect { kind: BaseEffectType::Strong { magnitude: scale(strong) }, scheduling: play_for, ..Default::default() })
            .add_effect(BaseEffect { kind: BaseEffectType::Weak { magnitude: scale(weak) }, scheduling: play_for, ..Default::default() })
            .gamepads(&[gid])
            .finish(&mut self.gilrs);
        match effect {
            Ok(e) => e.play().is_ok(),
            Err(_) => false,
        }
    }
}

#[pymodule]
fn cmu_graphics_joystick(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Joysticks>()?;
    Ok(())
}
