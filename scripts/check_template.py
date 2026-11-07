#!/usr/bin/env python3
"""Offline sanity check of switch/deal-desk.template.yaml before importing it.

Mirrors the checks Switch's own linter makes (docs/TEMPLATES.md, "Validation"):
the document parses, every {placeholder} is declared or a builtin, every param is
used, every agent says its provider, location and directory, and the room only
names agents the document creates. Switch Console runs the authoritative check on
import; this catches typos first. Needs PyYAML (pip install pyyaml).
"""

import re
import sys
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parent.parent / "switch" / "deal-desk.template.yaml"
BUILTINS = {"$creator", "$creator_email", "$date", "$timestamp", "$agents_dir", "agent"}
PARAM_TYPES = {"string", "number", "boolean", "enum", "agent", "bridge", "room", "user",
               "provider", "location", "machine", "directory"}
TOP_LEVEL = {"version", "params", "agent", "agents", "room", "group", "rooms", "links",
             "kickoff", "form"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PH_RE = re.compile(r"\{(\$?[A-Za-z_][A-Za-z0-9_]*)\}")


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def check(path: Path = PATH) -> list[str]:
    doc = yaml.safe_load(path.read_text())
    errors = []
    if not isinstance(doc, dict):
        return ["document is not a mapping"]
    errors += [f"unknown top-level key: {k}" for k in doc if k not in TOP_LEVEL]
    if doc.get("version") != 1:
        errors.append("expected version: 1")

    params = doc.get("params") or {}
    for name, spec in params.items():
        if spec.get("type", "string") not in PARAM_TYPES:
            errors.append(f"param {name}: unknown type {spec.get('type')}")
        if spec.get("input") in {"advanced", "fixed"} and "default" not in spec:
            errors.append(f"param {name}: input {spec['input']} needs a default")

    body = {k: v for k, v in doc.items() if k not in {"params", "form"}}
    used = {m for s in strings(body) for m in PH_RE.findall(s)}
    errors += [f"undeclared placeholder {{{p}}}" for p in sorted(used - set(params) - BUILTINS)]
    errors += [f"param {p} is never used" for p in sorted(set(params) - used)]

    agents = doc.get("agents") or []
    names = []
    for a in agents:
        n = a.get("name", "?")
        names.append(n)
        if not NAME_RE.match(n):
            errors.append(f"agent {n}: name must be lowercase letters, digits, . - _")
        for field in ("provider", "location", "directory", "instructions"):
            if not a.get(field):
                errors.append(f"agent {n}: missing {field}")
        if a.get("addressing") not in {"owner", "owner-agents", "anyone"}:
            errors.append(f"agent {n}: addressing must be owner, owner-agents or anyone")
    if len(names) != len(set(names)):
        errors.append("duplicate agent names")

    room = doc.get("room") or {}
    errors += [f"room lists unknown agent {a}" for a in room.get("agents", []) if a not in names]
    if "kickoff" in doc and not room:
        errors.append("kickoff needs a room")
    for n in names:
        if f"@{n}" not in doc.get("kickoff", ""):
            errors.append(f"kickoff does not mention @{n}, so it will sit silent")
    return errors


if __name__ == "__main__":
    errs = check()
    for e in errs:
        print("ERROR:", e)
    if not errs:
        print(f"OK: {PATH.name} parses; placeholders, params, agents and room line up.")
    sys.exit(1 if errs else 0)
