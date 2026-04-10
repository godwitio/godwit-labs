#!/usr/bin/env python3
# Copyright (c) 2026 Godwit.io
#
# Licensed under the MIT License. You may obtain a copy of the License at
#
#     https://opensource.org/licenses/MIT
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""migrate-many.py -- Fan out godwit sync across config files in a folder.

Enumerates every .yml file in the migrations/ directory and runs
godwit sync -f <file> for each, in parallel.

Usage:
    python3 scripts/migrate-many.py plan    Plan all pairs (--plan-only)
    python3 scripts/migrate-many.py run     Execute all pairs in parallel
    python3 scripts/migrate-many.py retry   Re-run only failed pairs
    python3 scripts/migrate-many.py verify  Verify checksums for all pairs
    python3 scripts/migrate-many.py status  Print summary table

Prerequisites:
    - godwit binary on PATH, in CWD, or in the parent of the migrations/ dir
    - PyYAML: pip install pyyaml
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = SCRIPT_ROOT / "migrations"
STATE_DIR = SCRIPT_ROOT / "state"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_godwit() -> str:
    """Resolve the godwit binary: ./godwit in CWD, SCRIPT_ROOT/godwit, or godwit on PATH."""
    for candidate in [Path("./godwit"), SCRIPT_ROOT / "godwit"]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    found = shutil.which("godwit")
    if found:
        return found
    print("Error: godwit binary not found. Place it in the current directory "
          "(./godwit), in the lab root, or install it on PATH.", file=sys.stderr)
    sys.exit(1)


GODWIT = find_godwit()


def get_configs():
    """Return sorted list of .yml config files in the migrations folder."""
    configs = sorted(MIGRATIONS_DIR.glob("*.yml"))
    if not configs:
        print(f"No .yml files found in {MIGRATIONS_DIR}", file=sys.stderr)
        sys.exit(1)
    return configs


def read_config(path):
    """Read a Godwit config file to extract run_id and state_path."""
    with open(path) as f:
        return yaml.safe_load(f)


def resolve_state_path(cfg):
    """Get the absolute state_path from a parsed config."""
    sp = cfg.get("run", {}).get("state_path", "")
    if sp.startswith("./"):
        return str(SCRIPT_ROOT / sp[2:])
    return sp


def status_port_from_cfg(cfg) -> str:
    """Extract the status port from a config dict. Returns empty string if unset."""
    return cfg.get("status", {}).get("addr", "").lstrip(":")


def is_pair_running(cfg) -> bool:
    """Check if a godwit process is running for this pair by probing its status endpoint."""
    return _check_status_port(status_port_from_cfg(cfg))


def inspect_run(cfg) -> dict | None:
    """Run godwit plan inspect --json and return the parsed result, or None on failure."""
    run_id = cfg.get("run", {}).get("run_id", "")
    state_path = resolve_state_path(cfg)
    if not run_id or not Path(state_path).is_file():
        return None
    result = subprocess.run(
        [GODWIT, "plan", "inspect", "--run-id", run_id,
         "--state-path", state_path, "--json"],
        capture_output=True, text=True, cwd=SCRIPT_ROOT,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Run a single pair
# ---------------------------------------------------------------------------

def _check_status_port(port: str) -> bool:
    """Return True if the status endpoint on the given port responds."""
    if not port:
        return False
    try:
        urllib.request.urlopen(f"http://localhost:{port}/status", timeout=2)
        return True
    except Exception:
        return False


def run_pair(godwit, config_path, action, status_port=""):
    """Run godwit sync for one config file. Returns (name, exit_code, skipped)."""
    name = config_path.stem

    # Skip if a godwit process is already running on this pair's status port
    if status_port and _check_status_port(status_port):
        return name, -1, True

    cmd = [godwit, "sync", "-f", str(config_path)]
    if action == "plan":
        cmd.append("--plan-only")
    elif action == "retry":
        cmd.append("--resume")

    log_path = STATE_DIR / f"{name}.log"
    exitcode_path = STATE_DIR / f"{name}.exitcode"

    # Remove stale exitcode before starting so a concurrent retry sees it as running
    exitcode_path.unlink(missing_ok=True)

    with open(log_path, "w") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=SCRIPT_ROOT)

    exitcode_path.write_text(str(result.returncode))
    return name, result.returncode, False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_plan():
    configs = get_configs()
    STATE_DIR.mkdir(exist_ok=True)

    print()
    print("===========================================")
    print(f"  Plan -- Planning all {len(configs)} pairs in parallel")
    print("===========================================")

    for cfg_path in configs:
        print(f"  Planning: {cfg_path.stem}")

    futures = {}
    with ThreadPoolExecutor(max_workers=40) as pool:
        for cfg_path in configs:
            cfg = read_config(cfg_path)
            port = status_port_from_cfg(cfg)
            future = pool.submit(run_pair, GODWIT, cfg_path, "plan", port)
            futures[future] = cfg_path.stem

        print(f"\n  All {len(configs)} pairs launched. Waiting for completion ...\n")

        results = {}
        for future in as_completed(futures):
            name, rc, skipped = future.result()
            results[name] = (rc, skipped)

    # Report in file-order
    print()
    print("===========================================")
    print("  Plan Results")
    print("===========================================")
    print(f"  {'PAIR':<20} {'STATUS':<12} {'OBJECTS':>8} {'DATA':>12}")
    print(f"  {'----':<20} {'------':<12} {'-------':>8} {'----':>12}")

    failed = 0
    total_objects = 0
    total_bytes = 0
    for cfg_path in configs:
        name = cfg_path.stem
        rc, skipped = results[name]
        cfg = read_config(cfg_path)
        inspection = inspect_run(cfg)

        if skipped:
            status = "SKIPPED"
            obj_str = ""
            data_str = ""
        elif rc == 0 and inspection:
            status = "OK"
            objects = inspection.get("objects", {})
            data = inspection.get("data", {})
            obj_count = objects.get("total", 0)
            byte_count = data.get("total", 0)
            total_objects += obj_count
            total_bytes += byte_count
            obj_str = str(obj_count)
            data_str = f"{byte_count / 1_048_576:.1f} MB"
        elif rc == 0:
            status = "OK"
            obj_str = "?"
            data_str = "?"
        else:
            status = f"FAILED ({rc})"
            obj_str = ""
            data_str = ""
            failed += 1

        print(f"  {name:<20} {status:<12} {obj_str:>8} {data_str:>12}")

    print(f"  {'':─<20} {'':─<12} {'':─>8} {'':─>12}")
    print(f"  {'TOTAL':<20} {'':<12} {total_objects:>8} {total_bytes / 1_048_576:>11.1f} MB")

    print()
    if failed > 0:
        print(f"  {failed} pair(s) failed. Check logs in {STATE_DIR}/")
        sys.exit(1)
    else:
        print("  All pairs planned successfully.")


def cmd_run():
    configs = get_configs()
    STATE_DIR.mkdir(exist_ok=True)

    print()
    print("===========================================")
    print(f"  Run -- Executing all {len(configs)} pairs in parallel")
    print("===========================================")

    futures = {}
    with ThreadPoolExecutor(max_workers=len(configs)) as pool:
        for cfg_path in configs:
            name = cfg_path.stem
            cfg = read_config(cfg_path)
            port = status_port_from_cfg(cfg)
            print(f"  Starting: {name} (log: state/{name}.log)")
            future = pool.submit(run_pair, GODWIT, cfg_path, "run", port)
            futures[future] = name

        print(f"\n  All {len(configs)} pairs launched. Waiting for completion ...\n")

        results = {}
        for future in as_completed(futures):
            name, rc, skipped = future.result()
            results[name] = (rc, skipped)

    # Report in file-order
    print()
    print("===========================================")
    print("  Results")
    print("===========================================")
    print(f"  {'PAIR':<20} STATUS")
    print(f"  {'----':<20} ------")

    failed = 0
    for cfg_path in configs:
        name = cfg_path.stem
        rc, skipped = results[name]
        if skipped:
            status = "SKIPPED (already running)"
        elif rc == 0:
            status = "OK"
        else:
            status = f"FAILED (exit {rc})"
            failed += 1
        print(f"  {name:<20} {status}")

    print()
    if failed > 0:
        print(f"  {failed} pair(s) failed. Check logs in {STATE_DIR}/")
        sys.exit(1)
    else:
        print("  All pairs completed successfully.")


def cmd_retry():
    configs = get_configs()

    print()
    print("===========================================")
    print("  Retry -- Re-running failed pairs")
    print("===========================================")

    failed_configs = []
    skipped_running = []
    skipped_completed = []
    for cfg_path in configs:
        name = cfg_path.stem
        cfg = read_config(cfg_path)

        # Skip pairs that are still running (status endpoint responds)
        if is_pair_running(cfg):
            skipped_running.append(name)
            continue

        # Check the state database via godwit plan inspect --json
        inspection = inspect_run(cfg)
        if inspection:
            run_status = inspection.get("status", "")
            if run_status == "completed":
                skipped_completed.append(name)
                continue
            if run_status == "running":
                skipped_running.append(name)
                continue
            # "failed", "planned", "pending" -- eligible for retry
            if run_status in ("failed",):
                failed_configs.append(cfg_path)
                continue

        # Fall back to exitcode file for pairs without a state database
        exitcode_path = STATE_DIR / f"{name}.exitcode"
        if not exitcode_path.exists():
            continue
        rc = int(exitcode_path.read_text().strip())
        if rc != 0:
            failed_configs.append(cfg_path)

    if skipped_running:
        print(f"  Skipping (still running): {', '.join(skipped_running)}")
    if skipped_completed:
        print(f"  Skipping (already completed): {', '.join(skipped_completed)}")

    if not failed_configs:
        print("  No failed pairs found. Nothing to retry.")
        return

    names = [c.stem for c in failed_configs]
    print(f"  Retrying {len(failed_configs)} pair(s): {', '.join(names)}")

    futures = {}
    with ThreadPoolExecutor(max_workers=len(failed_configs)) as pool:
        for cfg_path in failed_configs:
            name = cfg_path.stem
            cfg = read_config(cfg_path)
            port = status_port_from_cfg(cfg)
            print(f"  Starting: {name} (log: state/{name}.log)")
            future = pool.submit(run_pair, GODWIT, cfg_path, "run", port)
            futures[future] = name

        print("\n  Waiting for completion ...")

        results = {}
        for future in as_completed(futures):
            name, rc, skipped = future.result()
            results[name] = (rc, skipped)

    print()
    print(f"  {'PAIR':<20} STATUS")
    print(f"  {'----':<20} ------")

    still_failed = 0
    for cfg_path in failed_configs:
        name = cfg_path.stem
        rc, skipped = results[name]
        if skipped:
            status = "SKIPPED (already running)"
        elif rc == 0:
            status = "OK"
        else:
            status = f"FAILED (exit {rc})"
            still_failed += 1
        print(f"  {name:<20} {status}")

    print()
    if still_failed > 0:
        print(f"  {still_failed} pair(s) still failing. Check logs in {STATE_DIR}/")
        sys.exit(1)
    else:
        print("  All retried pairs completed successfully.")


def verify_pair(godwit, config_path):
    """Run godwit plan verify for one config file. Returns (name, exit_code)."""
    name = config_path.stem
    cmd = [godwit, "plan", "verify", "-f", str(config_path)]
    log_path = STATE_DIR / f"{name}.log"

    with open(log_path, "a") as log:
        result = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=SCRIPT_ROOT)

    return name, result.returncode


def cmd_verify():
    configs = get_configs()

    print()
    print("===========================================")
    print(f"  Verify -- Checking all {len(configs)} pairs in parallel")
    print("===========================================")

    futures = {}
    with ThreadPoolExecutor(max_workers=len(configs)) as pool:
        for cfg_path in configs:
            name = cfg_path.stem
            print(f"  Starting: {name}")
            future = pool.submit(verify_pair, GODWIT, cfg_path)
            futures[future] = name

        print(f"\n  All {len(configs)} pairs launched. Waiting for completion ...\n")

        results = {}
        for future in as_completed(futures):
            name, rc = future.result()
            results[name] = rc

    # Report in file-order
    print("===========================================")
    print("  Results")
    print("===========================================")
    print(f"  {'PAIR':<20} STATUS")
    print(f"  {'----':<20} ------")

    failed = 0
    for cfg_path in configs:
        name = cfg_path.stem
        rc = results[name]
        if rc == 0:
            status = "OK"
        else:
            status = f"FAILED (exit {rc})"
            failed += 1
        print(f"  {name:<20} {status}")

    print()
    if failed > 0:
        print(f"  {failed} pair(s) failed verification.")
        sys.exit(1)
    else:
        print("  All pairs verified successfully.")


def cmd_status():
    configs = get_configs()

    print()
    print("===========================================")
    print("  Status -- Migration Summary")
    print("===========================================")
    print()
    print(f"  {'PAIR':<20} {'STATE DB':<15} STATUS")
    print(f"  {'----':<20} {'--------':<15} ------")

    inspections = {}
    for cfg_path in configs:
        cfg = read_config(cfg_path)
        name = cfg_path.stem
        state_path = Path(resolve_state_path(cfg))

        db_status = "exists" if state_path.is_file() else "missing"

        # Determine run status: live endpoint > inspect > exitcode > not started
        inspection = inspect_run(cfg)
        inspections[name] = inspection

        if is_pair_running(cfg):
            run_status = "running"
        elif inspection:
            run_status = inspection.get("status", "unknown")
        else:
            exitcode_path = STATE_DIR / f"{name}.exitcode"
            if not exitcode_path.exists():
                run_status = "not started"
            else:
                rc = int(exitcode_path.read_text().strip())
                run_status = "OK" if rc == 0 else f"FAILED (exit {rc})"

        print(f"  {name:<20} {db_status:<15} {run_status}")

    # Print detailed inspect output for pairs that have a state database
    print()
    for cfg_path in configs:
        cfg = read_config(cfg_path)
        name = cfg_path.stem
        inspection = inspections.get(name)
        if not inspection:
            continue
        objects = inspection.get("objects", {})
        data = inspection.get("data", {})
        print(f"--- {name} ({inspection.get('status', 'unknown')}) ---")
        print(f"  Objects: {objects.get('succeeded', 0)}/{objects.get('total', 0)} succeeded"
              f", {objects.get('failed', 0)} failed"
              f", {objects.get('skipped', 0)} skipped")
        total_mb = data.get("total", 0) / 1_048_576
        done_mb = data.get("transferred", 0) / 1_048_576
        print(f"  Data:    {done_mb:.1f} / {total_mb:.1f} MB transferred")
        print()


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

COMMANDS = {
    "plan": cmd_plan,
    "run": cmd_run,
    "retry": cmd_retry,
    "verify": cmd_verify,
    "status": cmd_status,
}


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command in ("help", "--help", "-h"):
        print("Usage: python3 scripts/migrate-many.py {plan|run|retry|verify|status}")
        print()
        print("Commands:")
        print("  plan    Plan all pairs (--plan-only)")
        print("  run     Execute all pairs in parallel")
        print("  retry   Re-run only failed pairs")
        print("  verify  Verify checksums for all pairs")
        print("  status  Print summary table")
        return

    if command not in COMMANDS:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    STATE_DIR.mkdir(exist_ok=True)
    COMMANDS[command]()


if __name__ == "__main__":
    main()
