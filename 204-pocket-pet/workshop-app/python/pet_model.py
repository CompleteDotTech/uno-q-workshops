"""An epsilon-greedy bandit that learns which expressions get rewarded."""

import json
from pathlib import Path
import random


BEHAVIORS = ("glow", "bounce", "purr")
EXPLORATION = 0.20


def train():
    return {"version": 1, "counts": [0, 0, 0], "rewards": [0, 0, 0]}


def values(model):
    return [reward / count if count else 0.0 for reward, count in zip(model["rewards"], model["counts"])]


def choose(model, rng=random):
    for action, count in enumerate(model["counts"]):
        if count == 0:
            return action, "first example"
    if rng.random() < EXPLORATION:
        return rng.randrange(len(BEHAVIORS)), "explore"
    scores = values(model)
    return rng.choice([i for i, score in enumerate(scores) if score == max(scores)]), "exploit"


def update(model, action, reward):
    if type(action) is not int or not 0 <= action < len(BEHAVIORS) or type(reward) is not int or reward not in (0, 1):
        raise ValueError("Choose a valid behavior and reward of zero or one")
    model["counts"][action] += 1
    model["rewards"][action] += reward


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
        raise ValueError("Unsupported pet model")
    for key in ("counts", "rewards"):
        entries = model.get(key)
        if not isinstance(entries, list) or len(entries) != 3 or any(type(x) is not int or x < 0 for x in entries):
            raise ValueError("Saved pet counts must be three nonnegative integers")
    if any(reward > count for reward, count in zip(model["rewards"], model["counts"])):
        raise ValueError("Saved pet rewards exceed the number of ratings")
    return model
