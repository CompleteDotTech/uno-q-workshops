from arduino.app_utils import App, Bridge

import time
from pathlib import Path

from button import Button
from pet_model import BEHAVIORS, choose, load, save, train, update, values


MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "pet_model.json"
# Each step is (seconds from start, lit Pixels, vibration milliseconds).
EXPRESSIONS = (
    ((0.0, 3, 80), (0.25, 6, 0), (0.5, 8, 0)),
    ((0.0, 2, 90), (0.25, 5, 90), (0.5, 8, 90)),
    ((0.0, 8, 500),),
)
button = Button()
model = None
initialized = False
mode = "ready"
action = None
animation = []
animation_started = 0.0
rating_pressed = False


def prompt():
    button.accept_after(Bridge.call("show", 0, 8))
    print("READY: tap to meet your pet. After its expression, tap to reward or hold 1–2.5s to reject.")
    print("Hold three seconds at any time to erase its learning. Rotation is unused.")


def reset():
    global model, mode, animation, rating_pressed
    animation, rating_pressed, mode = [], False, "ready"
    try:
        MODEL_PATH.unlink(missing_ok=True)
    except OSError as error:
        print(f"Could not erase saved model: {error}. Release and hold again to retry.")
        Bridge.call("show", 6, 8)
        return
    model = train()
    print("New pet: all behavior ratings cleared.")
    prompt()


def start_expression():
    global action, mode, animation, animation_started, rating_pressed
    action, reason = choose(model)
    print(f"PET {BEHAVIORS[action]} ({reason}). Wait for two white Pixels before rating.")
    animation = list(EXPRESSIONS[action])
    animation_started = time.monotonic()
    rating_pressed = False
    mode = "expressing"


def rate(duration):
    global mode
    if 80 <= duration <= 600:
        reward = 1
    elif 1000 <= duration <= 2500:
        reward = 0
    else:
        print("RETRY rating: tap for 0.08–0.6s to reward, or hold 1–2.5s to reject.")
        return
    update(model, action, reward)
    try:
        save(model, MODEL_PATH)
    except OSError as error:
        print(f"Learning is active but could not be saved: {error}. This rating may be lost on restart.")
    scores = ", ".join(f"{name}={score:.2f} ({count} ratings)" for name, score, count in zip(BEHAVIORS, values(model), model["counts"]))
    print(f"{'REWARDED' if reward else 'REJECTED'} {BEHAVIORS[action]}; {scores}")
    mode = "ready"
    prompt()


def loop():
    global initialized, model, mode, animation, animation_started, rating_pressed
    if not initialized:
        try:
            model = load(MODEL_PATH)
        except (OSError, ValueError) as error:
            print(f"Ignoring saved model: {error}")
            model = None
        if model is None:
            model = train()
        prompt()
        initialized = True
    try:
        events = button.poll()
    except ValueError as error:
        print(f"RETRY: {error}. This expression was not rated; tap to start another.")
        mode, animation, rating_pressed = "ready", [], False
        Bridge.call("show", 5, 3)
        time.sleep(0.02)
        return
    for kind, at, duration in events:
        if kind == "reset":
            reset()
            break
        if mode == "rating" and kind == "press":
            rating_pressed = True
        elif mode == "rating" and kind == "release" and rating_pressed:
            rating_pressed = False
            rate(duration)
            break
        elif mode == "ready" and kind == "release" and 80 <= duration <= 600:
            start_expression()
            break
    if mode == "expressing":
        age = time.monotonic() - animation_started
        if animation and age >= animation[0][0]:
            offset, count, pulse = animation.pop(0)
            Bridge.call("show", action + 1, count)
            if pulse:
                Bridge.call("pulse", pulse)
            # Stretch playback after a delayed call instead of collapsing its pulses.
            animation_started = time.monotonic() - offset
        if not animation and time.monotonic() - animation_started >= 0.9 and not button.pressed:
            mode = "rating"
            button.accept_after(Bridge.call("show", 4, 2))
            print("RATE NOW: short tap = reward; 1–2.5s hold = reject; 3s hold = reset.")
    time.sleep(0.02)


if __name__ == "__main__":
    print("UNO Q Pocket Pet starting...")
    App.run(user_loop=loop)
