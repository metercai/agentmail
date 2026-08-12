#!/usr/bin/env python3
"""Detect installed agent systems (Hermes / OpenClaw) and list profiles."""
import json, os, subprocess, sys
from pathlib import Path

HOME = Path.home()

def detect_hermes():
    """Return {name, version, profiles} or None."""
    profiles_dir = HOME / ".hermes" / "profiles"
    if not profiles_dir.is_dir():
        return None
    # Get version
    version = "unknown"
    try:
        r = subprocess.run(["hermes", "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.strip() or r.stderr.strip() or "unknown"
    except Exception:
        pass
    # List profiles and their email addresses
    profiles = []
    for p in sorted(profiles_dir.iterdir()):
        if p.is_dir():
            cfg = p / "config.yaml"
            email = ""
            if cfg.exists():
                import yaml
                try:
                    c = yaml.safe_load(cfg.read_text()) or {}
                    email = c.get("agent", {}).get("email", "") or ""
                except Exception:
                    pass
            profiles.append({"name": p.name, "email": email})
    return {"product": "Hermes Agent", "version": version, "profiles": profiles}

def detect_openclaw():
    """Return {name, version, profiles} or None.

    OpenClaw stores agents under ~/.openclaw/agents/<id>/agent
    (legacy ~/.openclaw/profiles is no longer used).
    """
    agents_dir = HOME / ".openclaw" / "agents"
    if not agents_dir.is_dir():
        return None
    version = "unknown"
    try:
        r = subprocess.run(["openclaw", "--version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.strip() or r.stderr.strip() or "unknown"
    except Exception:
        pass
    profiles = []
    for p in sorted(agents_dir.iterdir()):
        if p.is_dir() and (p / "agent").is_dir():
            profiles.append({"name": p.name, "email": ""})
    return {"product": "OpenClaw", "version": version, "profiles": profiles}

if __name__ == "__main__":
    agents = []
    for d in [detect_hermes(), detect_openclaw()]:
        if d:
            agents.append(d)
    print(json.dumps(agents, indent=2, ensure_ascii=False))
