#!/usr/bin/env python3
"""
log-market-snapshot.py
執行 market-structure-snapshot.py 並把結果記錄到日誌檔。
可以被 cronjob 每小時或每 4 小時執行。
"""
import sys
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

LOG_DIR = Path(__file__).parent.parent / "data" / "market-snapshots"
SCRIPT = Path(__file__).parent / "market-structure-snapshot.py"
CST = timezone(timedelta(hours=8))

def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # 執行快照腳本，用 JSON 格式輸出
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, timeout=60
    )

    now = datetime.now(CST)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    log_entry = {
        "timestamp": now.isoformat(),
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip() if result.stderr else None,
    }

    # 寫入當日 JSON log
    log_file = LOG_DIR / f"{date_str}.json"
    existing = []
    if log_file.exists():
        with open(log_file) as f:
            try:
                existing = json.load(f)
                if not isinstance(existing, list):
                    existing = [existing]
            except json.JSONDecodeError:
                existing = []
    existing.append(log_entry)
    with open(log_file, "w") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"[{time_str}] Snapshot logged to {log_file}")
    print(result.stdout[-500:] if result.stdout else "(no output)")

if __name__ == "__main__":
    main()
