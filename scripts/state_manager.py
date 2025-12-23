#!/usr/bin/env python3
"""
Manage the state of the framework analysis process.
Tracks which frameworks are pending, in-progress, or completed.
"""

import json
import sys
import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from enum import Enum

class Status(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

STATE_DIR = Path("forensics-output/.state")
MANIFEST_FILE = STATE_DIR / "manifest.json"
REPOS_DIR = Path("repos")

def get_manifest() -> Dict:
    if not MANIFEST_FILE.exists():
        return {"frameworks": {}}
    try:
        return json.loads(MANIFEST_FILE.read_text())
    except json.JSONDecodeError:
        return {"frameworks": {}}

def save_manifest(manifest: Dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))

def init_state():
    """Scan repos and initialize/update manifest."""
    manifest = get_manifest()
    
    # Ensure repos dir exists
    if not REPOS_DIR.exists():
        print(f"Error: {REPOS_DIR} does not exist.")
        sys.exit(1)

    # Scan for frameworks
    found_frameworks = set()
    for item in REPOS_DIR.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            found_frameworks.add(item.name)
            if item.name not in manifest["frameworks"]:
                manifest["frameworks"][item.name] = {
                    "status": Status.PENDING,
                    "path": str(item)
                }
    
    # Warn about missing frameworks that were in manifest
    existing = set(manifest["frameworks"].keys())
    missing = existing - found_frameworks
    if missing:
        print(f"Warning: The following frameworks are in state but not found in repos: {', '.join(missing)}")
    
    save_manifest(manifest)
    print(f"State initialized. Tracking {len(manifest['frameworks'])} frameworks.")

def get_next_batch(limit: int) -> List[str]:
    """Get the next batch of pending frameworks."""
    manifest = get_manifest()
    pending = []
    
    # First, prioritize IN_PROGRESS (maybe they crashed?) 
    # Actually, if we are resuming, IN_PROGRESS might mean interrupted. 
    # Let's treat IN_PROGRESS as PENDING for the purpose of 'next batch' if we assume single-threaded orchestrator.
    # But to be safe, maybe we should just look for PENDING. 
    # If the user wants to resume crashed ones, they might need to be reset.
    # For now, let's just look for PENDING.
    
    for name, data in manifest["frameworks"].items():
        if data["status"] == Status.PENDING:
            pending.append(name)
    
    return pending[:limit]

def mark_status(framework: str, status: str):
    """Update status of a framework."""
    manifest = get_manifest()
    if framework not in manifest["frameworks"]:
        print(f"Error: Framework '{framework}' not found in state.")
        sys.exit(1)
        
    if status not in [s.value for s in Status]:
        print(f"Error: Invalid status '{status}'. Must be one of {[s.value for s in Status]}")
        sys.exit(1)
        
    manifest["frameworks"][framework]["status"] = status
    save_manifest(manifest)
    print(f"Updated '{framework}' to {status}.")

def show_status():
    """Print status table."""
    manifest = get_manifest()
    frameworks = manifest["frameworks"]
    
    if not frameworks:
        print("No frameworks tracked. Run 'init' first.")
        return

    print(f"{'FRAMEWORK':<25} {'STATUS':<15}")
    print("-" * 40)
    for name, data in sorted(frameworks.items()):
        print(f"{name:<25} {data['status']:<15}")

def reset_in_progress():
    """Reset IN_PROGRESS to PENDING and clean up output directories (Clean Slate)."""
    manifest = get_manifest()
    count = 0
    frameworks_output_dir = STATE_DIR.parent / "frameworks"

    for name, data in manifest["frameworks"].items():
        if data["status"] == Status.IN_PROGRESS:
            data["status"] = Status.PENDING
            
            # Clean slate: remove output directory
            fw_dir = frameworks_output_dir / name
            if fw_dir.exists():
                shutil.rmtree(fw_dir)
                print(f"  Cleaned up partial output for '{name}'")
            
            count += 1
            
    save_manifest(manifest)
    print(f"Reset {count} in-progress frameworks to pending.")

def main():
    parser = argparse.ArgumentParser(description="Manage analysis state")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("init", help="Initialize or update state from repos/")
    
    next_parser = subparsers.add_parser("next", help="Get next batch of pending frameworks")
    next_parser.add_argument("--limit", type=int, default=1, help="Batch size")
    
    mark_parser = subparsers.add_parser("mark", help="Mark framework status")
    mark_parser.add_argument("framework", help="Framework name")
    mark_parser.add_argument("status", choices=[s.value for s in Status], help="New status")
    
    subparsers.add_parser("status", help="Show status table")
    
    subparsers.add_parser("reset-running", help="Reset IN_PROGRESS to PENDING")

    args = parser.parse_args()
    
    if args.command == "init":
        init_state()
    elif args.command == "next":
        batch = get_next_batch(args.limit)
        # Output as space-separated string for easy shell usage
        print(" ".join(batch))
    elif args.command == "mark":
        mark_status(args.framework, args.status)
    elif args.command == "status":
        show_status()
    elif args.command == "reset-running":
        reset_in_progress()

if __name__ == "__main__":
    main()
