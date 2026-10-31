"""A nearest-centroid classifier for three-tap timing patterns."""

import json
import math
from pathlib import Path
from statistics import mean


LABELS = ("spark", "wave", "drum")
EXAMPLES_PER_LABEL = 5
MINIMUM_MARGIN = 0.20


def _vector(values):
    if (not isinstance(values, (list, tuple)) or len(values) != 5
            or any(type(x) not in (int, float) or not 0 < x <= 1 for x in values)
            or not math.isclose(sum(values), 1.0, abs_tol=1e-6)):
        raise ValueError("Expected five positive, normalized timing features")


def extract_features(taps):
    """Taps are (start_ms, end_ms), relative to the beginning of this rhythm."""
    if len(taps) != 3:
        raise ValueError("Use exactly three taps, then leave a one-second gap")
    if any(len(tap) != 2 or any(type(x) is not int for x in tap) for tap in taps):
        raise ValueError("Tap timestamps must be integer milliseconds")
    durations = [end - start for start, end in taps]
    gaps = [right[0] - left[1] for left, right in zip(taps, taps[1:])]
    if any(not 80 <= value <= 1200 for value in durations):
        raise ValueError("Hold each tap for 0.08–1.2 seconds")
    if any(not 80 <= value < 1000 for value in gaps):
        raise ValueError("Leave 0.08–1.0 seconds between taps")
    timings = durations + gaps
    return [value / sum(timings) for value in timings]


def _distance(left, right):
    return math.sqrt(mean((a - b) ** 2 for a, b in zip(left, right)))


def train(examples):
    centroids, radii = {}, {}
    for label in LABELS:
        rows = examples.get(label, [])
        if len(rows) < EXAMPLES_PER_LABEL:
            raise ValueError(f"Record {EXAMPLES_PER_LABEL} examples of {label}")
        for row in rows:
            _vector(row)
        center = [mean(column) for column in zip(*rows)]
        centroids[label] = center
        radii[label] = max(0.035, max(_distance(row, center) for row in rows))
    return {"version": 1, "centroids": centroids, "radii": radii}


def predict(model, features):
    _vector(features)
    distances = {label: _distance(features, model["centroids"][label]) for label in LABELS}
    ranked = sorted(distances, key=distances.get)
    label = ranked[0]
    best, second = distances[label], distances[ranked[1]]
    margin = (second - best) / max(second, 1e-9)
    return {
        "label": label, "margin": margin, "distances": distances,
        "accepted": margin >= MINIMUM_MARGIN and best <= 2 * model["radii"][label],
    }


def save(model, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(model, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def load(path):
    path = Path(path)
    if not path.exists():
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(model, dict) or model.get("version") != 1:
        raise ValueError("Unsupported rhythm model")
    for key in ("centroids", "radii"):
        if not isinstance(model.get(key), dict) or set(model[key]) != set(LABELS):
            raise ValueError("Saved model must contain all three rhythms")
    for label in LABELS:
        _vector(model["centroids"][label])
        radius = model["radii"][label]
        if type(radius) not in (int, float) or not 0 < radius <= 1:
            raise ValueError("Invalid rhythm radius")
    return model
