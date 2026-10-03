#!/usr/bin/env python3
"""Run evidence/DVR retention purge (schedule via cron)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_yaml, expand_env


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = expand_env(load_yaml(os.path.join(base, "config", "config.yaml")))
    retention = cfg.get("retention", {})
    if not retention.get("enabled", False):
        print("Retention disabled in config.yaml")
        return
    try:
        from utils.data.retention import purge_old_evidence
        purge_old_evidence(base, days=retention.get("evidence_days", 90))
        print("Retention purge complete")
    except Exception as e:
        print(f"Retention purge failed: {e}")


if __name__ == "__main__":
    main()
