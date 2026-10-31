"""Separate personal reaction-time baselines for light and vibration cues."""

import json
from pathlib import Path
from statistics import mean, pstdev


CUES = ("light", "vibration")
EXAMPLES_PER_CUE = 5
MINIMUM_MS = 100
MAXIMUM_MS = 2000
MINIMUM_SCALE_MS = 40


def _reaction(value):
    if type(value) not in (int, float) or not MINIMUM_MS <= value <= MAXIMUM_MS:
        raise ValueError("Use a reaction between 100 and 2000 milliseconds")


def train(examples):
    baselines = {}
    for cue in CUES:
        rows = examples.get(cue, [])
        if len(rows) < EXAMPLES_PER_CUE:
            raise ValueError(f"Record {EXAMPLES_PER_CUE} valid {cue} reactions")
        for row in rows:
            _reaction(row)
        baselines[cue] = {"mean": mean(rows), "scale": max(MINIMUM_SCALE_MS, pstdev(rows))}
    return {"version": 1, "baselines": baselines}


def predict(model, cue, reaction_ms):
    _reaction(reaction_ms)
    if cue not in CUES:
        raise ValueError("Unknown cue")
    baseline = model["baselines"][cue]
    z = (reaction_ms - baseline["mean"]) / baseline["scale"]
    return {"z": z, "status": "faster" if z < -2 else "slower" if z > 2 else "typical"}


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
        raise ValueError("Unsupported reflex model")
    if not isinstance(model.get("baselines"), dict) or set(model["baselines"]) != set(CUES):
        raise ValueError("Saved model must contain light and vibration baselines")
    for baseline in model["baselines"].values():
        if not isinstance(baseline, dict):
            raise ValueError("Invalid reflex baseline")
        _reaction(baseline.get("mean"))
        scale = baseline.get("scale")
        if type(scale) not in (int, float) or not MINIMUM_SCALE_MS <= scale <= MAXIMUM_MS:
            raise ValueError("Invalid reflex variation")
    return model
