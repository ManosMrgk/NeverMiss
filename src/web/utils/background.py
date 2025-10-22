# utils/background.py
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor

# Simple singleton executor for fire-and-forget jobs
_executor: ThreadPoolExecutor | None = None

def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nevermiss-bg")
    return _executor

def submit_background(func, *args, **kwargs):
    return get_executor().submit(func, *args, **kwargs)
