import sys

# ---------- logging ----------
def log(msg: str, *, debug: bool):
    if debug:
        print(f"[debug] {msg}", file=sys.stderr)

def info(msg: str):
    print(f"[info] {msg}", file=sys.stderr)

def warn(msg: str):
    print(f"[warn] {msg}", file=sys.stderr)