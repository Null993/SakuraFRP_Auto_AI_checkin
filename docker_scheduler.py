import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv


CODE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("APP_DATA_DIR", CODE_DIR)).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

ENV_FILE = DATA_DIR / ".env"
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


def log(message: str) -> None:
    print(f"[scheduler] {datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def parse_hhmm(value: str, name: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = int(hour_text, 10)
        minute = int(minute_text, 10)
    except ValueError as exc:
        raise ValueError(f"{name} must use HH:MM format, got {value!r}") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{name} must be a valid time, got {value!r}")
    return hour, minute


def minutes_to_time(total_minutes: int, seconds: int) -> str:
    total_minutes %= 24 * 60
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}:{seconds:02d}"


def random_time_for_today() -> str:
    start = os.getenv("CHECKIN_WINDOW_START")
    end = os.getenv("CHECKIN_WINDOW_END")

    if start and end:
        start_hour, start_minute = parse_hhmm(start, "CHECKIN_WINDOW_START")
        end_hour, end_minute = parse_hhmm(end, "CHECKIN_WINDOW_END")
        start_total = start_hour * 60 + start_minute
        end_total = end_hour * 60 + end_minute
    else:
        schedule_time = os.getenv("SCHEDULE_TIME", "08:00")
        window_minutes = int(os.getenv("SCHEDULE_WINDOW_MINUTES", "30"))
        hour, minute = parse_hhmm(schedule_time, "SCHEDULE_TIME")
        center_total = hour * 60 + minute
        start_total = max(0, center_total - window_minutes)
        end_total = min(24 * 60 - 1, center_total + window_minutes)

    if end_total < start_total:
        raise ValueError("Overnight check-in windows are not supported; keep start <= end")

    random_minute = random.randint(start_total, end_total)
    random_second = random.randint(0, 59)
    return minutes_to_time(random_minute, random_second)


def target_datetime(today: str, value: str) -> datetime:
    hour_text, minute_text, second_text = value.split(":", 2)
    base = datetime.strptime(today, "%Y-%m-%d")
    return base.replace(
        hour=int(hour_text, 10),
        minute=int(minute_text, 10),
        second=int(second_text, 10),
    )


def ensure_random_time(today: str) -> str:
    random_file = DATA_DIR / f"random_time_{today}.txt"
    if random_file.exists():
        return random_file.read_text(encoding="utf-8").strip()

    value = random_time_for_today()
    random_file.write_text(value + "\n", encoding="utf-8")
    log(f"generated today's random check-in time: {value}")
    return value


def run_checkin(today: str, target: str) -> None:
    lock_file = DATA_DIR / f".executed_{today}.lock"
    if lock_file.exists():
        return

    lock_file.write_text(datetime.now().strftime("%H:%M:%S") + "\n", encoding="utf-8")
    env = os.environ.copy()
    env["APP_DATA_DIR"] = str(DATA_DIR)

    log(f"starting check-in for scheduled time {target}")
    result = subprocess.run(
        [sys.executable, str(CODE_DIR / "main.py"), "--both"],
        cwd=str(CODE_DIR),
        env=env,
    )

    if result.returncode == 0:
        log("check-in finished successfully")
        return

    lock_file.unlink(missing_ok=True)
    log(f"check-in failed with exit code {result.returncode}; lock removed for retry")


def sleep_until_next_check(seconds: float) -> None:
    max_sleep = int(os.getenv("SCHEDULER_MAX_SLEEP_SECONDS", "300"))
    time.sleep(max(1, min(max_sleep, int(seconds))))


def main() -> None:
    log(f"data directory: {DATA_DIR}")
    if not ENV_FILE.exists():
        log("warning: /data/.env not found")
    if not (DATA_DIR / "account.txt").exists():
        log("warning: /data/account.txt not found")

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        lock_file = DATA_DIR / f".executed_{today}.lock"
        random_value = ensure_random_time(today)
        target = target_datetime(today, random_value)

        if lock_file.exists():
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=2, microsecond=0)
            sleep_until_next_check((tomorrow - now).total_seconds())
            continue

        if now >= target:
            run_checkin(today, random_value)
            continue

        sleep_until_next_check((target - now).total_seconds())


if __name__ == "__main__":
    main()
