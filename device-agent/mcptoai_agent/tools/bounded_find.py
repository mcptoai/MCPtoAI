"""Bounded filesystem walk. Best-effort wall clock deadline (cannot preempt OS calls)."""
from __future__ import annotations

import fnmatch
import os
import time
from pathlib import Path
from typing import Callable

DEFAULT_SECONDS = 10.0
DEFAULT_DEPTH = 6
MAX_MATCHES = 200
MAX_VISITS = 20_000


def find_bounded(base: Path, pattern: str, *, check_path: Callable, limit: int = 200,
                 seconds: float = DEFAULT_SECONDS, max_depth: int = DEFAULT_DEPTH,
                 clock: Callable = time.monotonic) -> str:
    """Return only inspected files, with explicit incomplete status on any limit."""
    limit = max(1, min(int(limit), MAX_MATCHES))
    max_depth = max(0, min(int(max_depth), 16))
    seconds = max(.1, min(float(seconds), DEFAULT_SECONDS))
    deadline = clock() + seconds
    queue: list[tuple[Path, int]] = [(base, 0)]
    hits: list[tuple[int, Path]] = []
    skipped = visits = 0
    stop_reason = ''
    depth_skipped = False
    while queue:
        if clock() >= deadline:
            stop_reason = 'time limit'; break
        directory, depth = queue.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if clock() >= deadline:
                        stop_reason = 'time limit'; break
                    visits += 1
                    if visits > MAX_VISITS:
                        stop_reason = 'entry limit'; break
                    path = Path(entry.path)
                    try:
                        # No symlink traversal, including directories/junctions.
                        if entry.is_symlink():
                            skipped += 1; continue
                        check_path(path.resolve(strict=False), write=False)
                        if entry.is_dir(follow_symlinks=False):
                            if depth < max_depth:
                                queue.append((path, depth+1))
                            else:
                                depth_skipped = True
                        elif entry.is_file(follow_symlinks=False) and fnmatch.fnmatch(path.name, pattern):
                            hits.append((entry.stat(follow_symlinks=False).st_size, path))
                            if len(hits) >= limit:
                                stop_reason = 'result limit'; break
                    except (PermissionError, OSError, ValueError):
                        skipped += 1
                if stop_reason:
                    break
        except (PermissionError, OSError):
            skipped += 1
    hits.sort(key=lambda item: item[0], reverse=True)
    lines = [f'{size:>12} {path}' for size, path in hits]
    lines.append(f'{skipped} protected paths skipped (including unreadable entries)')
    if stop_reason or depth_skipped:
        reason = ', '.join(filter(None,[stop_reason, 'depth limit' if depth_skipped else '']))
        lines.append(f'[PARTIAL RESULTS: {reason}; scan stopped or skipped deeper folders; not a complete search]')
    else:
        lines.append('[COMPLETE: scanned within configured depth]')
    return '\n'.join(lines)
