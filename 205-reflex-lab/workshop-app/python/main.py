from arduino.app_utils import App, Bridge

import random
import time
from pathlib import Path

from button import Button
from reflex_model import CUES, EXAMPLES_PER_CUE, load, predict, save, train


MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "reflex_model.json"
button = Button()
model = None
initialized = False
examples = {cue: [] for cue in CUES}
mode = "ready"
cue = None
feedback_until = 0.0


def prompt():
    if model is None:
        next_cue = next(cue for cue in CUES if len(examples[cue]) < EXAMPLES_PER_CUE)
        button.accept_after(Bridge.call("show", 1 if next_cue == "light" else 3, max(1, round(len(examples[next_cue]) * 8 / EXAMPLES_PER_CUE))))
        print(f"TRAIN {next_cue}: example {len(examples[next_cue]) + 1}/{EXAMPLES_PER_CUE}. Tap and release to arm, then wait for the cue.")
    else:
        button.accept_after(Bridge.call("show", 0, 8))
        print("LIVE: tap and release to arm a random light or vibration trial.")
    print("Press only after the cue. Hold three seconds to erase the baseline and retrain.")


def show_feedback(color, count):
    global mode, feedback_until
    Bridge.call("show", color, count)
    mode = "feedback"
    feedback_until = time.monotonic() + 1


def reset():
    global model, examples
    Bridge.call("cancel_trial")
    try:
        MODEL_PATH.unlink(missing_ok=True)
    except OSError as error:
        print(f"Could not erase saved model: {error}. Release and hold again to retry.")
        show_feedback(6, 8)
        return
    model = None
    examples = {name: [] for name in CUES}
    show_feedback(7, 0)
    print("Baseline cleared. Release the button to begin training again.")


def finish_trial(reaction):
    global model
    if reaction == -3:
        print("FALSE START: press only after the cue. This trial was not saved.")
        show_feedback(5, 3)
        return
    if reaction == -4:
        print("TIMEOUT: no response within two seconds. This trial was not saved.")
        show_feedback(5, 3)
        return
    if not 100 <= reaction <= 2000:
        print("RETRY: response under 100ms or invalid timing. This trial was not saved.")
        show_feedback(5, 3)
        return
    if model is None:
        examples[cue].append(reaction)
        print(f"Accepted {cue} reaction: {reaction}ms ({len(examples[cue])}/{EXAMPLES_PER_CUE}).")
        show_feedback(2, 8)
        if all(len(rows) == EXAMPLES_PER_CUE for rows in examples.values()):
            model = train(examples)
            try:
                save(model, MODEL_PATH)
                print(f"Baseline saved to {MODEL_PATH}")
            except OSError as error:
                print(f"Baseline is active but could not be saved: {error}. Restarting will retrain.")
            print(f"Learned baselines: {model['baselines']}")
    else:
        result = predict(model, cue, reaction)
        print(f"{cue.upper()} {reaction}ms: {result['status']}; signed deviation={result['z']:.2f} (not a probability).")
        code = {"faster": 3, "typical": 2, "slower": 5}[result["status"]]
        show_feedback(code, max(1, min(8, round(abs(result["z"]) * 2))))


def loop():
    global initialized, model, mode, cue
    if not initialized:
        Bridge.call("cancel_trial")
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
        Bridge.call("cancel_trial")
        mode = "ready"
        print(f"RETRY: {error}")
        prompt()
        time.sleep(0.02)
        return
    for kind, at, duration in events:
        if kind == "reset":
            reset()
            break
        if mode == "ready" and kind == "release" and 80 <= duration <= 600:
            cue = (next(name for name in CUES if len(examples[name]) < EXAMPLES_PER_CUE)
                   if model is None else random.choice(CUES))
            print(f"WAIT for {cue}. Do not press yet.")
            accepted = int(Bridge.call("arm_trial", CUES.index(cue), random.randint(1500, 3500)))
            if accepted:
                mode = "trial"
            else:
                print("Release the button, then tap again to arm.")
            break
    if mode == "trial":
        result = int(Bridge.call("read_trial"))
        if result != -2:
            finish_trial(result)
    if mode == "feedback" and time.monotonic() >= feedback_until and not button.pressed:
        mode = "ready"
        prompt()
    time.sleep(0.02)


if __name__ == "__main__":
    print("UNO Q Reflex Lab starting...")
    App.run(user_loop=loop)
