"""Small git subprocess boundary."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from pathlib import Path

from .store import ThreadError

# The whole store is one repo, so two sessions committing in the same instant
# collide on .git/index.lock. The other commit takes milliseconds: wait it out.
LOCK_WAITS = (0.1, 0.2, 0.4, 0.8, 1.5)


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    for wait in (*LOCK_WAITS, None):
        result = subprocess.run(
            ["git", *args], cwd=cwd, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if result.returncode == 0 or "index.lock" not in result.stderr:
            break
        if wait is None:
            # By now the change is already on disk; only the commit is missing.
            raise ThreadError(
                "Recorded, but not committed to git yet: another git process held the store's "
                "lock. Don't run the command again; this is committed with the thread's next "
                "change. If it keeps happening while no git is running, a crashed git left "
                f"{cwd / '.git' / 'index.lock'} behind; delete that file.", code=5,
            )
        time.sleep(wait)
    if check and result.returncode:
        raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result


def init(root: Path) -> None:
    if not (root / ".git").is_dir():
        _git(root, "init", "-q")
    # A fresh machine may not have identity configured. It is repository-local.
    if _git(root, "config", "user.email", check=False).returncode:
        _git(root, "config", "user.email", "thread@localhost")
    if _git(root, "config", "user.name", check=False).returncode:
        _git(root, "config", "user.name", "thread")
    commit(
        root, "initialize thread store",
        [root / ".gitignore", root / ".gitattributes"],
    )


def head(root: Path) -> str | None:
    result = _git(root, "rev-parse", "HEAD", check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def commit(root: Path, message: str, paths: Iterable[Path]) -> str:
    scoped = []
    for path in paths:
        resolved = path if path.is_absolute() else root / path
        scoped.append(resolved.relative_to(root).as_posix())
    if not scoped:
        raise ValueError("a commit needs at least one scoped path")
    scoped = list(dict.fromkeys(scoped))
    scoped = [
        path for path in scoped
        if (root / path).exists()
        or _git(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode == 0
    ]
    if not scoped:
        return head(root) or ""
    _git(root, "add", "-A", "--", *scoped)

    if _git(root, "diff", "--cached", "--quiet", "--", *scoped, check=False).returncode == 0:
        return head(root) or ""
    # Naming paths on commit keeps unrelated pre-staged work out of this commit.
    result = _git(root, "commit", "-q", "-m", message, "--only", "--", *scoped, check=False)
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return head(root) or ""


