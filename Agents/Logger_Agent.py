import logging
import os
import sys
import json
import time
import traceback
from datetime import datetime
from typing import Optional


_CURRENT: Optional["LoggerAgent"] = None


def set_current(logger: "LoggerAgent") -> None:
    global _CURRENT
    _CURRENT = logger


def get_current() -> Optional["LoggerAgent"]:
    return _CURRENT


class _Sub:
    def __init__(self, parent: "LoggerAgent", prefix: str):
        self.parent = parent
        self.prefix = prefix

    def info(self, msg, **data):
        self.parent.info(f"[{self.prefix}] {msg}", **data)

    def warn(self, msg, **data):
        self.parent.warn(f"[{self.prefix}] {msg}", **data)

    def error(self, msg, exc_info: bool = False, **data):
        self.parent.error(f"[{self.prefix}] {msg}", exc_info=exc_info, **data)

    def step_start(self, step, **data):
        self.parent.step_start(f"{self.prefix}.{step}", **data)

    def step_end(self, step, **data):
        self.parent.step_end(f"{self.prefix}.{step}", **data)

    def child(self, name: str) -> "_Sub":
        return _Sub(self.parent, f"{self.prefix}.{name}")


class LoggerAgent:
    def __init__(self, log_dir: str = "output/logs", session_id: str = None):
        os.makedirs(log_dir, exist_ok=True)
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"{self.session_id}.log")
        self.jsonl_path = os.path.join(log_dir, f"{self.session_id}.jsonl")

        self.logger = logging.getLogger(f"teacher_ai.{self.session_id}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.logger.handlers.clear()

        fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
        fh = logging.FileHandler(self.log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        self.logger.addHandler(fh)
        self.logger.addHandler(sh)

        self._timers: dict = {}

    def child(self, name: str) -> _Sub:
        return _Sub(self, name)

    def info(self, msg, **data):
        self._emit("INFO", msg, data)

    def warn(self, msg, **data):
        self._emit("WARNING", msg, data)

    def error(self, msg, exc_info: bool = False, **data):
        if exc_info:
            data["traceback"] = traceback.format_exc()
        self._emit("ERROR", msg, data)

    def step_start(self, step, **data):
        self._timers[step] = time.time()
        self._emit("INFO", f"START {step}", data)

    def step_end(self, step, **data):
        elapsed = time.time() - self._timers.pop(step, time.time())
        data["elapsed_s"] = round(elapsed, 2)
        self._emit("INFO", f"END   {step}", data)

    def _emit(self, level, msg, data):
        if data:
            self.logger.log(getattr(logging, level), f"{msg} | {json.dumps(data, default=str)[:1200]}")
        else:
            self.logger.log(getattr(logging, level), msg)
        try:
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.now().isoformat(),
                    "level": level,
                    "session": self.session_id,
                    "msg": msg,
                    "data": data,
                }, default=str) + "\n")
        except Exception:
            pass


def log_or_print(msg: str, level: str = "info", **data):
    """Helper for agents — uses current LoggerAgent if set, else prints."""
    cur = get_current()
    if cur is None:
        print(f"[{level.upper()}] {msg}", data if data else "")
        return
    getattr(cur, level)(msg, **data)
