"""Root discovery, reference resolution, and filesystem writes."""

from __future__ import annotations

import os
import re
import secrets
import string
import tempfile
from pathlib import Path
from typing import Any

import yaml

ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


# How a thread ends. The three are separate states so the archive tells a
# solved problem from an abandoned one; code that asks "is it finished?"
# goes through is_final, never its own tuple.
FINAL_STATES = ("merged", "completed", "dropped")

def is_final(state: str | None) -> bool:
    """Merged, completed, or dropped: the thread has ended."""
    return state in FINAL_STATES


class ThreadError(Exception):
    """A user-facing refusal."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


class NeedsInput(ThreadError):
    """A command was run without a body it needs; the message is a template
    to fill in, so it goes to stdout (redirectable) with a non-zero exit."""


DEFAULT_ROOT = Path("~/.spindle")


def root_path(value: str | Path | None = None, *, initializing: bool = False) -> Path:
    """The thread store: --root, else SPINDLE_ROOT, else the scope setting (scope.py)."""
    from .scope import locate

    path, how = locate(value)
    if initializing:
        return path
    if path.is_dir():
        if not (path / ".git").exists():
            # Without its own .git, commits silently go nowhere (or into an enclosing repo).
            raise ThreadError(
                f"{path} isn't a git repository, and the thread store must be: every change is a commit. "
                f"Run `thread init --root {path}` to make it one."
            )
        return path
    if how == "project":
        raise ThreadError(f"no thread store in {path.parent}; `thread create` starts one.")
    raise ThreadError(
        f"no thread store at {path}. Run `thread init` to create it, "
        "or point at another one with --root <path> or SPINDLE_ROOT."
    )


def initialize(path: Path) -> None:
    from . import gitops

    path.mkdir(parents=True, exist_ok=True)
    (path / DEFAULT_NAMESPACE / "threads").mkdir(parents=True, exist_ok=True)
    atomic_text(path / ".gitignore", "scratch/\n")
    atomic_text(path / ".gitattributes", "**/log.jsonl merge=union\n")
    gitops.init(path)


def new_thread_id(root: Path) -> str:
    for _ in range(100):
        value = "".join(secrets.choice(ALPHABET) for _ in range(6))
        try:
            resolve_thread(root, value)
        except ThreadError:
            return value
    raise ThreadError("could not allocate a unique thread id")


def slugify(title: str) -> str:
    words: list[str] = []
    current = ""
    for char in title.lower():
        if char in string.ascii_lowercase + string.digits:
            current += char
        elif current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    if not words:
        return "thread"
    slug = words[0][:40]
    for word in words[1:]:
        candidate = f"{slug}-{word}"
        if len(candidate) > 40:
            break
        slug = candidate
    return slug



def is_thread_dir(path: Path) -> bool:
    return path.is_dir() and (path / "log.jsonl").is_file()


# Layout (<store> is ~/.spindle, or <project>/.spindle in project scope):
#   <store>/<ns>/threads/<id>-<slug>/                        active and inactive threads
#   <store>/<ns>/threads/archived/YYYY-MM/<id>-<slug>/       merged, completed, dropped
# The default namespace is an explicit folder, default/. Thread folders are
# always <id>-<slug>, so none can be named "archived".
DEFAULT_NAMESPACE = "default"
ARCHIVED = "archived"


def _namespace_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [entry for entry in root.iterdir() if entry.is_dir() and not entry.name.startswith(".")]


def iter_threads(root: Path) -> list[Path]:
    paths: list[Path] = []
    for ns in _namespace_dirs(root):
        threads = ns / "threads"
        if not threads.is_dir():
            continue
        paths += [p for p in threads.iterdir() if is_thread_dir(p)]
        archived = threads / ARCHIVED
        if archived.is_dir():
            for month in archived.iterdir():
                if month.is_dir():
                    paths += [p for p in month.iterdir() if is_thread_dir(p)]
    return sorted(paths)


def _threads_dir(thread: Path) -> Path:
    """The <root>/<ns>/threads directory a thread folder lives under. Checked
    structurally, up to the store's own .git, so a namespace or slug that
    happens to be called "threads" can't be mistaken for it."""
    for ancestor in thread.parents:  # nearest first: a store can sit under any folder named "threads"
        if ancestor.name == "threads" and (ancestor.parent.parent / ".git").exists():
            return ancestor
    raise ThreadError(f"not inside a thread store: {thread}")


def root_of(thread: Path) -> Path:
    """The store containing a thread folder."""
    return _threads_dir(thread).parent.parent


def is_active(thread: Path) -> bool:
    """In threads/ itself rather than threads/archived/<month>/."""
    return thread.parent == _threads_dir(thread)


def namespace_of(thread: Path) -> str | None:
    """Namespace derived from where the folder sits; the default namespace is None."""
    name = _threads_dir(thread).parent.name
    return None if name == DEFAULT_NAMESPACE else name


def thread_home(root: Path, name: str, namespace: str | None, *, month: str | None = None) -> Path:
    """Where a thread folder named ``name`` lives."""
    threads = root / (namespace or DEFAULT_NAMESPACE) / "threads"
    return (threads if month is None else threads / ARCHIVED / month) / name


def resolve_thread(root: Path, reference: str) -> Path:
    matches = [
        path for path in iter_threads(root)
        if path.name == reference or path.name.split("-", 1)[0].startswith(reference)
    ]
    if not matches:
        raise ThreadError(f"no thread matches {reference!r}. `thread list` shows active threads and their ids.")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches[:10])
        raise ThreadError(f"{reference!r} matches more than one thread ({names}); use more of the id.")
    return matches[0]


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ThreadError(f"invalid YAML in {path}: {exc}") from exc
    return default if value is None else value


def write_yaml(path: Path, value: Any) -> None:
    atomic_text(path, yaml.safe_dump(value, sort_keys=False, allow_unicode=True))


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ThreadError("markdown file must begin with YAML frontmatter")
    try:
        header, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ThreadError("YAML frontmatter is missing its closing ---") from exc
    try:
        metadata = yaml.safe_load(header) or {}
    except yaml.YAMLError as exc:
        raise ThreadError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ThreadError("YAML frontmatter must be a mapping")
    return metadata, body


def markdown(metadata: dict[str, Any], body: str) -> str:
    header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{header}\n---\n{body.lstrip()}"


_COMMENT = re.compile(r"<!--.*?-->\s*", re.S)


def strip_comments(text: str) -> str:
    """Drop HTML comments. Templates the tool prints carry guidance in
    comments; a leftover one must not become a headline or count toward a cap."""
    return _COMMENT.sub("", text)
