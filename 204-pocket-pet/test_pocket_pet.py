"""Run from the repository root: python3 -B 204-pocket-pet/test_pocket_pet.py"""

import contextlib
import io
import json
from pathlib import Path
import random
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / "workshop-app/python"))
from pet_model import choose, load, save, train, update, values


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid input was accepted")


def check():
    model = train()
    for expected in range(3):
        action, reason = choose(model)
        assert action == expected and reason == "first example"
        update(model, action, int(action == 1))
    assert values(model) == [0, 1, 0]
    rng = random.Random(42)
    choices = [choose(model, rng)[0] for _ in range(1000)]
    assert choices.count(1) > 800 and set(choices) == {0, 1, 2}
    update(model, 1, 0)
    assert values(model)[1] == 0.5
    for action, reward in ((-1, 1), (3, 0), (1, 2), (True, 1)):
        rejects(lambda: update(model, action, reward))

    with TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()):
        path = Path(directory) / "data/pet_model.json"
        assert load(path) is None
        save(model, path)
        assert load(path) == model and not path.with_suffix(".tmp").exists()
        for invalid in ([], {}, {**model, "counts": [-1, 1, 1]},
                        {**model, "rewards": [10, 0, 0]}, {**model, "counts": [1, 2]}):
            path.write_text(json.dumps(invalid))
            rejects(lambda: load(path))

        now, pressed, edges, overflow = 100, 0, [], 0
        calls = []

        def call(name, *args):
            if name == "poll_input":
                return json.dumps([now, pressed, overflow, edges])
            calls.append((name, *args))
            if name == "show":
                return now

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

        def finish_expression():
            for _ in range(75):
                if app.mode != "expressing":
                    break
                tick()
            assert app.mode == "rating"

        tick()  # Invalid save starts a new pet.
        assert app.mode == "ready" and app.model == train()
        tap()
        assert app.mode == "expressing" and app.action == 0
        tap()  # Early input is ignored, not counted as a reward.
        assert sum(app.model["counts"]) == 0
        finish_expression()
        assert app.mode == "rating"
        ready_at = app.button.accepted_after
        tick(200, [[1, ready_at - 100], [0, ready_at + 100]])
        assert app.mode == "rating" and sum(app.model["counts"]) == 0
        tap(800)  # Ambiguous duration asks for another rating.
        assert app.mode == "rating" and sum(app.model["counts"]) == 0
        tap()
        assert app.mode == "ready" and app.model["rewards"] == [1, 0, 0]
        assert load(path) == app.model
        tap()
        # A stalled Linux loop must not collapse bounce's three pulses into one.
        pulse_count = sum(entry[0] == "pulse" for entry in calls)
        tick(1500)
        assert sum(entry[0] == "pulse" for entry in calls) == pulse_count + 1
        assert app.mode == "expressing"
        tick()
        assert sum(entry[0] == "pulse" for entry in calls) == pulse_count + 1
        finish_expression()
        tap(1500)
        assert app.model["counts"] == [1, 1, 0] and app.model["rewards"] == [1, 0, 0]
        tap()
        finish_expression()
        tick(20, lost=1)
        assert app.mode == "ready" and app.model["counts"][2] == 0
        tap()
        finish_expression()
        tap(3200)  # Reset is never recorded as a negative reward.
        assert app.model == train() and not path.exists()
        tap()
        finish_expression()

        def cannot_save(*args):
            raise OSError("Simulated full disk")

        original_save = app.save
        app.save = cannot_save
        tap()
        assert app.model["counts"] == [1, 0, 0] and not path.exists()
        app.save = original_save
        save(app.model, path)
        app.initialized = False
        tick()
        assert app.model == load(path)
        # A short tap and reset may arrive together after a blocked Bridge call.
        base = now
        tick(4020, [[1, base + 100], [0, base + 300], [1, base + 500], [0, base + 3800]])
        assert app.model == train() and not path.exists() and app.mode == "ready"
        old_model = app.model
        app.MODEL_PATH = Path(directory)
        app.reset()
        assert app.model is old_model and app.MODEL_PATH.is_dir()

    print("PASS: reward learning, exploration, persistence, and simulated expression/rating/reset flow")


if __name__ == "__main__":
    check()
    from test_sketch import check as check_sketch
    check_sketch()
