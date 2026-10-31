"""Run from the repository root: python3 -B 203-rhythm-key/test_rhythm_key.py"""

import contextlib
import io
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent / "workshop-app/python"))
from rhythm_model import LABELS, extract_features, load, predict, save, train


PATTERNS = (
    [(0, 160), (360, 520), (720, 1360)],
    [(0, 640), (840, 1000), (1200, 1360)],
    [(0, 160), (360, 1000), (1200, 1360)],
)


def rejects(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Invalid input was accepted")


def check():
    rows = [extract_features(pattern) for pattern in PATTERNS]
    model = train({label: [row] * 5 for label, row in zip(LABELS, rows)})
    for label, pattern in zip(LABELS, PATTERNS):
        for factor in (0.75, 1, 1.5):
            result = predict(model, extract_features([(int(a * factor), int(b * factor)) for a, b in pattern]))
            assert result["accepted"] and result["label"] == label
    assert not predict(model, [0.2] * 5)["accepted"]
    overlapping = train({label: [rows[0]] * 5 for label in LABELS})
    assert not predict(overlapping, rows[0])["accepted"]
    for invalid in ([], PATTERNS[0][:2], [(0, 20), (200, 400), (600, 800)],
                    [(0, 200), (100, 300), (400, 600)], [(0, 200), (1200, 1400), (1500, 1700)]):
        rejects(lambda: extract_features(invalid))

    output = io.StringIO()
    with TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
        path = Path(directory) / "data/rhythm_model.json"
        assert load(path) is None
        save(model, path)
        assert load(path) == model and not path.with_suffix(".tmp").exists()
        for invalid in ([], {}, {**model, "centroids": {}},
                        {**model, "centroids": dict.fromkeys(LABELS, [10**400, 1, 1, 1, 1])},
                        {**model, "radii": dict.fromkeys(LABELS, 10**400)},
                        {**model, "radii": dict.fromkeys(LABELS, float("nan"))}):
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
        from button import Button, elapsed

        app.MODEL_PATH = path
        app.time = SimpleNamespace(monotonic=lambda: now / 1000, sleep=lambda _: None)

        def tick(delta=20, new_edges=(), down=0, lost=0):
            nonlocal now, pressed, edges, overflow
            now += delta
            pressed, edges, overflow = down, list(new_edges), lost
            app.loop()

        def rhythm(pattern):
            base = now + 100
            packet = [[state, base + at] for start, end in pattern for state, at in ((1, start), (0, end))]
            tick(pattern[-1][1] + 120, packet)
            tick(1020)
            tick(1020)

        tick()  # Malformed model falls back to training.
        assert app.model is None
        rhythm(PATTERNS[0][:2])
        assert not any(app.examples.values())
        # Do not invite the next example while button input is still ignored.
        before = output.getvalue().count("TRAIN spark:")
        app.taps = PATTERNS[0]
        app.finish_capture()
        assert output.getvalue().count("TRAIN spark:") == before
        tick(1020)
        assert output.getvalue().count("TRAIN spark:") == before + 1
        app.examples[LABELS[0]].clear()
        for label, pattern in zip(LABELS, PATTERNS):
            for _ in range(5):
                rhythm(pattern)
            assert len(app.examples[label]) == 5
        assert app.model == load(path)
        calls.clear()
        rhythm(PATTERNS[1])
        assert ("show", 2, 8) in calls
        calls.clear()
        rhythm([(0, 200), (400, 600), (800, 1000)])
        assert any(entry[:2] == ("show", 5) for entry in calls)
        app.initialized = False
        tick()
        assert app.model == load(path)

        # A reset behind a completed rhythm's gap must supersede the whole batch.
        base = now
        tick(5020, [[1, base + 100], [0, base + 300], [1, base + 1500], [0, base + 4800]])
        assert app.model is None and not path.exists()
        app.model = model
        save(model, path)

        tick(20, [[1, now + 20]], down=1)
        tick(3020, down=1)
        assert app.model is None and not path.exists()
        tick(20, [[0, now + 20]])
        assert not app.taps and app.started_at is None
        tick(20, lost=1)
        tick(1020)
        assert not any(app.examples.values())

        # A reset failure keeps the active model and saved data.
        app.model = model
        app.MODEL_PATH = Path(directory)  # Cannot unlink a directory as a model file.
        app.reset()
        assert app.model is model and app.MODEL_PATH.is_dir()
        app.MODEL_PATH = path
        app.model = None
        app.examples = {label: [row] * 5 for label, row in zip(LABELS, rows)}
        app.examples[LABELS[-1]].pop()
        app.taps = PATTERNS[-1]

        def cannot_save(*args):
            raise OSError("Simulated full disk")

        app.save = cannot_save
        app.finish_capture()
        assert app.model is not None and not path.exists()

        # The shared button reader handles batched reset, overflow and clock rollover.
        reader = Button()
        now, pressed, overflow, edges = 100, 0, 0, [[1, 0xFFFFFF80], [0, 80]]
        assert reader.poll()[-1] == ("release", 80, 208)
        assert elapsed(80, 0xFFFFFF80) == 208
        now, edges = 4000, [[1, 500], [0, 3800]]
        assert reader.poll() == [("reset", 3800, 3300)]
        # A late-delivered press that began before a prompt cannot be reused.
        reader.accept_after(4500)
        now, edges = 4800, [[1, 4400], [0, 4600]]
        assert reader.poll() == []
        now, edges = 5200, [[1, 4900], [0, 5100]]
        assert reader.poll()[-1] == ("release", 5100, 200)
        reader.accept_after(0xFFFFFFF0)
        now, edges = 100, [[1, 0xFFFFFFE0], [0, 60]]
        assert reader.poll() == []
        now, edges = 400, [[1, 150], [0, 350]]
        assert reader.poll()[-1] == ("release", 350, 200)
        # Reset holds still work when they started before the prompt.
        reader.accept_after(1000)
        now, edges = 4200, [[1, 800], [0, 4100]]
        assert reader.poll() == [("reset", 4100, 3300)]
        overflow, edges = 1, []
        rejects(reader.poll)
        overflow, edges = 0, [[1, "bad timestamp"]]
        rejects(reader.poll)

    print("PASS: rhythm features, rejection, persistence, button timing, and simulated train/live/reset flow")


if __name__ == "__main__":
    check()
    from test_sketch import check as check_sketch
    check_sketch()
