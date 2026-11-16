#!/usr/bin/env python3
"""Validate every ```mermaid block in wiki/ by rendering it with mmdc.

Usage: validate-mermaid.py <wiki_dir> [puppeteer_config]

Extracts each fenced mermaid block from .md files, writes it to a temp file,
and runs `mmdc` to render-check it. Exits 1 if any block fails to render.

If the headless browser cannot be launched (missing system libraries on
self-hosted runners), the check degrades to a warning rather than failing —
this is an infrastructure issue, not a diagram error.
"""
import re
import subprocess
import sys
import tempfile
import os
from pathlib import Path


def extract_mermaid_blocks(md_path: Path):
    """Yield (block_index, content) for each mermaid block."""
    content = md_path.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"```mermaid\n(.*?)```", content, re.DOTALL)
    for i, block in enumerate(blocks, 1):
        yield i, block


def find_chrome():
    """Find a Chrome/Chromium binary in puppeteer cache or system paths."""
    # Check explicit env override first
    p = os.environ.get("PUPPETEER_EXECUTABLE_PATH", "")
    if p and os.path.isfile(p):
        return p
    # Search puppeteer cache
    cache_dirs = [
        os.path.expanduser("~/.cache/puppeteer"),
        "/root/.cache/puppeteer",
        "/home/runner/.cache/puppeteer",
    ]
    for cd in cache_dirs:
        if os.path.isdir(cd):
            for root, _dirs, files in os.walk(cd):
                if "chrome" in files and os.access(os.path.join(root, "chrome"), os.X_OK):
                    return os.path.join(root, "chrome")
    # System chromium
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        try:
            r = subprocess.run(["which", name], capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return None


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <wiki_dir> [puppeteer_config]", file=sys.stderr)
        sys.exit(2)

    wiki_dir = Path(sys.argv[1])
    puppeteer_config = sys.argv[2] if len(sys.argv) > 2 else None

    if not wiki_dir.is_dir():
        print(f"Error: {wiki_dir} is not a directory", file=sys.stderr)
        sys.exit(2)

    # Probe whether mmdc can launch a browser at all.
    # If not, degrade to a warning (infrastructure issue, not a content issue).
    chrome_path = find_chrome()
    env = os.environ.copy()
    if chrome_path:
        env["PUPPETEER_EXECUTABLE_PATH"] = chrome_path

    browser_available = False
    probe_err = "mmdc exited without a diagnostic"
    with tempfile.TemporaryDirectory() as tmpdir:
        probe = Path(tmpdir) / "probe.mmd"
        probe.write_text("graph TD\n  A --> B\n")
        out = Path(tmpdir) / "probe.svg"
        cmd = ["mmdc", "-i", str(probe), "-o", str(out), "--quiet"]
        if puppeteer_config:
            cmd.extend(["-p", puppeteer_config])
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
            browser_available = r.returncode == 0
            if not browser_available:
                lines = (r.stderr or r.stdout or "").strip().splitlines()
                if lines:
                    probe_err = lines[0]
        except Exception as e:
            probe_err = str(e)

    if not browser_available:
        print("WARNING: headless browser unavailable — mermaid render check skipped.")
        print("This is an infrastructure issue on the runner, not a diagram error.")
        print(f"chrome binary: {chrome_path or 'NOT FOUND (puppeteer cache empty and no system chromium)'}")
        print(f"probe failure: {probe_err}")
        print("Install Chrome/Chromium and its system libraries on the runner to enable render validation.")
        sys.exit(0)

    md_files = sorted(wiki_dir.rglob("*.md"))
    total = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        out_svg = Path(tmpdir) / "out.svg"
        block_file = Path(tmpdir) / "block.mmd"

        for md_path in md_files:
            for idx, block in extract_mermaid_blocks(md_path):
                total += 1
                block_file.write_text(block)
                cmd = [
                    "mmdc",
                    "-i", str(block_file),
                    "-o", str(out_svg),
                    "--quiet",
                ]
                if puppeteer_config:
                    cmd.extend(["-p", puppeteer_config])
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=env,
                )
                if result.returncode != 0:
                    failed += 1
                    rel = md_path.relative_to(wiki_dir.parent) if md_path.parent != wiki_dir.parent else md_path
                    print(f"  FAIL: {rel} (block {idx})", file=sys.stderr)
                    err_line = result.stderr.strip().split("\n")[0] if result.stderr.strip() else "unknown error"
                    print(f"        {err_line}", file=sys.stderr)

    if failed > 0:
        print(f"\n{failed}/{total} mermaid blocks failed to render", file=sys.stderr)
        sys.exit(1)

    print(f"OK ({total} mermaid block(s) validated)")


if __name__ == "__main__":
    main()
