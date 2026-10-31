"""Read debounced MCU button events without timing Bridge round trips."""

import json

from arduino.app_utils import Bridge


def elapsed(now, start):
    return (now - start) & 0xFFFFFFFF


class Button:
    def __init__(self):
        self.now = 0
        self.pressed = False
        self.pressed_at = None
        self.blocked = False
        self.accepted_after = None

    def accept_after(self, at):
        """Ignore ordinary presses that began before an MCU prompt was displayed."""
        if type(at) is not int or not 0 <= at <= 0xFFFFFFFF:
            raise ValueError("Invalid prompt timestamp; import the matching Python and sketch files")
        self.accepted_after = at

    def poll(self):
        packet = json.loads(Bridge.call("poll_input"))
        if not isinstance(packet, list) or len(packet) != 4:
            raise ValueError("Invalid button packet; restart the app")
        now, pressed, overflow, edges = packet
        if (type(now) is not int or not 0 <= now <= 0xFFFFFFFF
                or type(pressed) is not int or pressed not in (0, 1)
                or type(overflow) is not int or overflow not in (0, 1)
                or not isinstance(edges, list) or len(edges) > 32):
            raise ValueError("Invalid button state; restart the app")
        for edge in edges:
            if (not isinstance(edge, list) or len(edge) != 2
                    or type(edge[0]) is not int or edge[0] not in (0, 1)
                    or type(edge[1]) is not int or not 0 <= edge[1] <= 0xFFFFFFFF):
                raise ValueError("Invalid button event; restart the app")
        self.now, self.pressed = now, bool(pressed)
        if overflow:
            self.pressed_at = None
            self.blocked = self.pressed
            raise ValueError("Button buffer overflow; release and retry this round")
        events = []
        for down, at in edges:
            if self.blocked:
                if not down:
                    self.blocked = False
                continue
            if down:
                self.pressed_at = at
                events.append(("press", at, 0))
            elif self.pressed_at is not None:
                duration = elapsed(at, self.pressed_at)
                events.append(("reset" if duration >= 3000 else "release", at, duration))
                self.pressed_at = None
        if self.pressed and self.pressed_at is not None and elapsed(now, self.pressed_at) >= 3000:
            events.append(("reset", now, 0))
            self.pressed_at = None
            self.blocked = True
        for event in events:
            if event[0] == "reset":
                # A reset supersedes the entire batch, including earlier start taps.
                self.pressed_at = None
                self.blocked = self.pressed
                return [event]
        return [event for event in events if self.accepted_after is None
                or elapsed((event[1] - event[2]) & 0xFFFFFFFF, self.accepted_after) < 0x80000000]
