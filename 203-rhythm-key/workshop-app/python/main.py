from arduino.app_utils import App, Bridge

import time
from pathlib import Path

from button import Button, elapsed
from rhythm_model import LABELS, EXAMPLES_PER_LABEL, extract_features, load, predict, save, train


MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "rhythm_model.json"
button = Button()
model = None
initialized = False
examples = {label: [] for label in LABELS}
taps = []
started_at = None
tap_started_at = None
last_release = None
feedback_until = 0.0


def clear_capture():
    global taps, started_at, tap_started_at, last_release
    taps, started_at, tap_started_at, last_release = [], None, None, None


def prompt():
    if model is None:
        label = next(label for label in LABELS if len(examples[label]) < EXAMPLES_PER_LABEL)
        button.accept_after(Bridge.call("show", LABELS.index(label) + 1, max(1, round(len(examples[label]) * 8 / EXAMPLES_PER_LABEL))))
        print(f"TRAIN {label}: example {len(examples[label]) + 1}/{EXAMPLES_PER_LABEL}. Tap three times, then wait one second.")
    else:
        button.accept_after(Bridge.call("show", 0, 8))
        print("LIVE: tap any trained rhythm. Hold three seconds to erase and retrain.")


def reset():
    global model, examples, feedback_until
    clear_capture()
    try:
        MODEL_PATH.unlink(missing_ok=True)
    except OSError as error:
        print(f"Could not erase saved model: {error}. Release and hold again to retry.")
        Bridge.call("show", 6, 8)
        feedback_until = time.monotonic() + 1
        return
    model = None
    examples = {label: [] for label in LABELS}
    feedback_until = 0
    print("Record five examples each of spark, wave, and drum. Rotation is unused.")
    prompt()


def finish_capture():
    global model, feedback_until
    try:
        features = extract_features(taps)
    except ValueError as error:
        print(f"RETRY: {error}")
        Bridge.call("show", 5, 3)
    else:
        if model is None:
            label = next(label for label in LABELS if len(examples[label]) < EXAMPLES_PER_LABEL)
            examples[label].append(features)
            print(f"Accepted {label}: {len(examples[label])}/{EXAMPLES_PER_LABEL}.")
            Bridge.call("pulse", 120)
            if all(len(rows) == EXAMPLES_PER_LABEL for rows in examples.values()):
                model = train(examples)
                try:
                    save(model, MODEL_PATH)
                    print(f"Model saved to {MODEL_PATH}")
                except OSError as error:
                    print(f"Model is active but could not be saved: {error}. Restarting will retrain.")
                Bridge.call("show", 3, 8)
            else:
                Bridge.call("show", LABELS.index(label) + 1, max(1, round(len(examples[label]) * 8 / EXAMPLES_PER_LABEL)))
        else:
            result = predict(model, features)
            status = result["label"] if result["accepted"] else "UNCERTAIN"
            print(f"{status}: separation={result['margin']:.2f}; distances={result['distances']}")
            Bridge.call("show", LABELS.index(result["label"]) + 1 if result["accepted"] else 5,
                        max(1, round(result["margin"] * 8)))
            Bridge.call("pulse", 220 if result["accepted"] else 80)
    clear_capture()
    feedback_until = time.monotonic() + 1


def loop():
    global initialized, model, started_at, tap_started_at, last_release, feedback_until
    if not initialized:
        try:
            model = load(MODEL_PATH)
        except (OSError, ValueError) as error:
            print(f"Ignoring saved model: {error}")
            model = None
        prompt()
        initialized = True
    try:
        events = button.poll()
    except ValueError as error:
        clear_capture()
        print(f"RETRY: {error}")
        Bridge.call("show", 5, 3)
        feedback_until = time.monotonic() + 1
        time.sleep(0.02)
        return
    for kind, at, duration in events:
        if kind == "reset":
            reset()
            break
        if feedback_until:
            continue
        # Split rhythms using MCU timestamps even when several edges arrive together.
        if kind == "press" and taps and last_release is not None and elapsed(at, last_release) >= 1000:
            finish_capture()
            break
        if kind == "press":
            if started_at is None:
                started_at = at
                Bridge.call("show", 4, 8)
            tap_started_at = elapsed(at, started_at)
        elif kind == "release" and tap_started_at is not None:
            taps.append((tap_started_at, elapsed(at, started_at)))
            tap_started_at = None
            last_release = at
    if not feedback_until and started_at is not None:
        if not button.pressed and last_release is not None and elapsed(button.now, last_release) >= 1000:
            finish_capture()
        elif elapsed(button.now, started_at) >= 8000:
            clear_capture()
            print("RETRY: rhythm exceeded eight seconds. Release and start again.")
            Bridge.call("show", 5, 3)
            feedback_until = time.monotonic() + 1
    if feedback_until and time.monotonic() >= feedback_until and not button.pressed:
        feedback_until = 0
        prompt()
    time.sleep(0.02)


if __name__ == "__main__":
    print("UNO Q Rhythm Key starting...")
    App.run(user_loop=loop)
