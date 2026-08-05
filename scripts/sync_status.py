"""
sync_status.py — auto-called by the PostFileSave hook.

On every .py or .html save, updates:
  1. "Last updated" timestamp in PROJECT_STATUS.md
  2. "Last updated" timestamp in .kiro/steering/onboarding.md
  3. Appends a line to .kiro/CHANGELOG.md (newest-first, capped at 100 entries)

Usage:
    python scripts/sync_status.py <saved_file_path>
"""

import sys
import os
import re
from datetime import datetime

# Resolve project root as the directory containing this script's parent
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)

STATUS_FILE    = os.path.join(ROOT, "PROJECT_STATUS.md")
ONBOARD_FILE   = os.path.join(ROOT, ".kiro", "steering", "onboarding.md")
CHANGELOG_FILE = os.path.join(ROOT, ".kiro", "CHANGELOG.md")

SKIP_FILES = {
    os.path.normcase(STATUS_FILE),
    os.path.normcase(ONBOARD_FILE),
    os.path.normcase(CHANGELOG_FILE),
}


def make_summary(filepath):
    """Build a short human-readable summary from the file path."""
    try:
        rel = os.path.relpath(filepath, ROOT).replace("\\", "/")
    except ValueError:
        rel = os.path.basename(filepath)
    return f"saved {rel}"


def update_last_updated(doc_path, summary):
    """Replace the **Last updated:** line in a markdown file."""
    if not os.path.exists(doc_path):
        return
    try:
        with open(doc_path, "r", encoding="utf-8") as f:
            content = f.read()
        now = datetime.now().strftime("%Y-%m-%d %H:%M ET")
        new_line = f"**Last updated:** {now} — {summary}"
        updated = re.sub(r"\*\*Last updated:\*\*[^\n]*", new_line, content, count=1)
        if updated != content:
            with open(doc_path, "w", encoding="utf-8") as f:
                f.write(updated)
    except Exception as e:
        print(f"[sync_status] WARNING: could not update {doc_path}: {e}", file=sys.stderr)


def append_changelog(summary):
    """Prepend a timestamped entry to .kiro/CHANGELOG.md."""
    try:
        os.makedirs(os.path.dirname(CHANGELOG_FILE), exist_ok=True)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"- {now} — {summary}\n"
        header = (
            "# RoadIQ Auto-Changelog\n"
            "_Auto-updated on every .py/.html save. Newest first. "
            "Read this to see what changed without opening every file._\n\n"
        )
        if os.path.exists(CHANGELOG_FILE):
            with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            entries = [l for l in lines if l.startswith("- ")]
        else:
            entries = []
        entries.insert(0, entry)
        entries = entries[:100]
        with open(CHANGELOG_FILE, "w", encoding="utf-8") as f:
            f.write(header)
            f.writelines(entries)
    except Exception as e:
        print(f"[sync_status] WARNING: could not write changelog: {e}", file=sys.stderr)


def main():
    saved_file = sys.argv[1] if len(sys.argv) > 1 else ""
    if not saved_file:
        print("[sync_status] No file path provided.", file=sys.stderr)
        return

    abs_saved = os.path.normcase(os.path.abspath(saved_file))
    if abs_saved in SKIP_FILES:
        # Avoid infinite loop — don't re-trigger on the docs themselves
        return

    summary = make_summary(saved_file)
    update_last_updated(STATUS_FILE, summary)
    update_last_updated(ONBOARD_FILE, summary)
    append_changelog(summary)
    print(f"[sync_status] ✓ {summary}")


if __name__ == "__main__":
    main()
