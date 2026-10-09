from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_SIZE = 2 * 1024 * 1024
PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?" + r"PRIVATE KEY-----"
    ),
}


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / name for name in result.stdout.decode("utf-8").split("\0") if name]


def main() -> int:
    findings: list[str] = []
    for path in repository_files():
        if not path.is_file() or path.stat().st_size > MAX_FILE_SIZE:
            continue
        content = path.read_bytes()
        if b"\0" in content:
            continue
        text = content.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}: {label}")

    if findings:
        print("Potential secrets detected:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print(f"Secret scan passed for {len(repository_files())} repository files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
