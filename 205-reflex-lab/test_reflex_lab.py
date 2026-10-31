"""Run from the repository root: python3 -B 205-reflex-lab/test_reflex_lab.py"""

import contextlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / "workshop-app/python"))
from reflex_model import load, predict, save, train


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid input was accepted")


def check():
    examples = {"light": [400] * 5, "vibration": [600] * 5}
    model = train(examples)
    assert model["baselines"]["light"]["scale"] == 40
    assert predict(model, "light", 400)["status"] == "typical"
    assert predict(model, "light", 480)["status"] == "typical"
    assert predict(model, "light", 481)["status"] == "slower"
    assert predict(model, "light", 300)["status"] == "faster"
    assert predict(model, "vibration", 400)["status"] == "faster"
    for invalid in (99, 2001, 10**400, float("nan"), float("inf"), True):
        rejects(lambda: predict(model, "light", invalid))
    rejects(lambda: train({"light": [400], "vibration": [400] * 5}))

    with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        path = Path(directory) / "data/reflex_model.json"
        assert load(path) is None
        save(model, path)
        assert load(path) == model and not path.with_suffix(".tmp").exists()
        for invalid in ([], {}, {**model, "baselines": {}},
                        {"version": 1, "baselines": {"light": {"mean": 10**400, "scale": 40}, "vibration": {}}},
                        {"version": 1, "baselines": {"light": {"mean": 400, "scale": 10**400}, "vibration": {}}},
                        {"version": 1, "baselines": {"light": {"mean": 400, "scale": 0}, "vibration": {}}}):
            path.write_text(json.dumps(invalid))
            rejects(lambda: load(path))

        now, pressed, edges, overflow, result = 100, 0, [], 0, -2
        show_delay = 0
        calls = []

        def call(name, *args):
            nonlocal result, now
            if name == "poll_input":
                return json.dumps([now, pressed, overflow, edges])
            calls.append((name, *args))
            if name == "show":
                now += show_delay
                return now
            if name == "arm_trial":
                assert args[0] in (0, 1) and 1500 <= args[1] <= 3500
                result = -2
                return 1
            if name == "read_trial":
                return result
            if name == "cancel_trial":
                result = -2

        utilities = ModuleType("arduino.app_utils")
        utilities.App, utilities.Bridge = SimpleNamespace(), SimpleNamespace(call=call)
        sys.modules["arduino"] = ModuleType("arduino")
        sys.modules["arduino.app_utils"] = utilities
        import main as app
        app.MODEL_PATH = path
        app.time = SimpleNamespace(monotonic=lambda: now / 1000, sleep=lambda _: None)

        def tick(delta=20, new_edges=(), down=0, lost=0):
            nonlocal now, pressed, edges, overflow
            now += delta
            pressed, edges, overflow = down, list(new_edges), lost
            app.loop()

        def tap(duration=200):
            tick(duration + 40, [[1, now + 20], [0, now + 20 + duration]])

        def trial(reaction):
            nonlocal result
            tap()
            assert app.mode == "trial"
            result = reaction
            tick(2500)
            assert app.mode == "feedback"
            tick(1020)

        tick()
        assert app.model is None and app.mode == "ready"
        for invalid in (-3, -4, 50, 2001):
            trial(invalid)
            assert not any(app.examples.values())
        for _ in range(5):
            trial(400)
        assert app.examples["light"] == [400] * 5
        for _ in range(5):
            trial(600)
        assert app.model == model and load(path) == model
        app.initialized = False
        tick()
        assert app.model == model
        ready_at = app.button.accepted_after
        tick(200, [[1, ready_at - 100], [0, ready_at + 100]])
        assert app.mode == "ready"  # A tap begun before READY cannot arm a trial.
        app.random = SimpleNamespace(choice=lambda _: "light", randint=lambda a, b: 2000)
        calls.clear()
        trial(600)
        assert any(entry[:2] == ("show", 5) for entry in calls)
        assert load(path) == model  # Live challenges do not silently retrain.
        show_delay = 1500
        app.finish_trial(-3)
        assert app.feedback_until >= now / 1000 + 1
        show_delay = 0
        tick(1020)
        # An earlier short tap in the packet must not hide a later reset hold.
        base = now
        tick(4020, [[1, base + 100], [0, base + 300], [1, base + 500], [0, base + 3800]])
        assert app.model is None and not path.exists()
        tick(1020)
        app.model = model
        save(model, path)
        tap()
        tick(20, lost=1)
        assert app.mode == "ready" and result == -2
        tap(3200)
        tick(1020)
        assert app.model is None and not path.exists()
        app.model = model
        app.MODEL_PATH = Path(directory)
        app.reset()
        assert app.model is model and app.MODEL_PATH.is_dir()
        app.MODEL_PATH = path
        app.model = None
        app.examples = {"light": [400] * 5, "vibration": [600] * 4}
        app.cue = "vibration"

        def cannot_save(*args):
            raise OSError("Simulated full disk")

        app.save = cannot_save
        app.finish_trial(600)
        assert app.model == model and not path.exists()

    print("PASS: cue baselines, scoring, persistence, and simulated training/challenge/reset flow")


if __name__ == "__main__":
    check()
    from test_sketch import check as check_sketch
    check_sketch()
