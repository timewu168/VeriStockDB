# DB Backup / Restore SOP

此文件是 VeriStockDB SQLite canonical DB 的備份與還原標準流程。任何正式還原都必須由人工執行，不可透過 PWA/API 自動觸發。

## 適用範圍

- 主 SQLite DB：`VERISTOCK_DB_PATH`
- 最新備份：`VERISTOCK_BACKUP_PATH`，未設定時為 `VERISTOCK_BACKUP_DIR/veristock_latest_backup.db`
- 時間戳備份：`VERISTOCK_BACKUP_DIR/veristock_*.db`

此 SOP 不處理 ClickHouse。若未來加入 ClickHouse，它只能在另行驗證前作為 analytics/high-volume serving，不可取代 SQLite canonical truth。

## Restore 前不可省略的判斷

正式還原前先確認：

- 是否已停止所有會寫 DB 的服務或 timer。
- 是否已保留事故當下 DB，不可直接覆蓋。
- backup 檔案是否存在、大小合理、可讀。
- backup `PRAGMA integrity_check` 是否為 `ok`。
- backup 的 row count、latest date/month 是否符合要回復的時間點。
- restore copy 是否能用 `main.py status` 讀取。

若任一項失敗，不可覆寫正式 DB。

## 1. 載入 production env

```bash
cd /opt/veristockdb/app
set -a
. /etc/veristockdb/veristockdb.env
set +a

echo "$VERISTOCK_DB_PATH"
echo "${VERISTOCK_BACKUP_PATH:-$VERISTOCK_BACKUP_DIR/veristock_latest_backup.db}"
```

不要把 `/etc/veristockdb/veristockdb.env` 內容貼到公開 issue 或 commit，裡面可能有 Telegram token。

## 2. 停止會寫 DB 的服務

正式 restore 前先停止 production writers。依目前部署，至少包含：

```bash
sudo systemctl stop veristockdb-update-close.timer
sudo systemctl stop veristockdb-update-legal.timer
sudo systemctl stop veristockdb-update-attention.timer
sudo systemctl stop veristockdb-update-disposal.timer
sudo systemctl stop veristockdb-update-margin.timer
sudo systemctl stop veristockdb-update-day-trading.timer
sudo systemctl stop veristockdb-update-revenue.timer
```

若 API/PWA 正在執行，也要停止對外服務或確認沒有 manual update job 正在跑。

```bash
systemctl list-timers 'veristockdb-*' --no-pager
```

## 3. 保留事故當下 DB

不可直接覆寫正式 DB。先把事故 DB 搬成 forensic copy：

```bash
STAMP=$(date +%Y%m%d_%H%M%S)
cp -a "$VERISTOCK_DB_PATH" "$VERISTOCK_DB_PATH.incident_$STAMP"
ls -lh "$VERISTOCK_DB_PATH" "$VERISTOCK_DB_PATH.incident_$STAMP"
```

若 DB 旁邊存在非 0 bytes 的 `-wal` 或 `-shm`，先停掉所有 writer，再評估是否一併保留；不要手動刪除。

## 4. 選擇 backup 並做唯讀驗證

建議先驗證 `veristock_latest_backup.db`：

```bash
BACKUP_PATH="${VERISTOCK_BACKUP_PATH:-$VERISTOCK_BACKUP_DIR/veristock_latest_backup.db}"
ls -lh "$BACKUP_PATH"
sqlite3 "$BACKUP_PATH" 'PRAGMA integrity_check;'
```

若要改用時間戳備份：

```bash
ls -lh "$VERISTOCK_BACKUP_DIR"/*.db | tail -n 20
BACKUP_PATH="$VERISTOCK_BACKUP_DIR/veristock_restore_drill_v063_YYYYMMDD_HHMMSS.db"
```

## 5. 先 restore 到 /tmp 演練

正式覆寫前，必須先在 `/tmp` 建立 restore copy 並驗證：

```bash
RESTORE_TEST="/tmp/veristock_restore_test.db"
rm -f "$RESTORE_TEST"
cp "$BACKUP_PATH" "$RESTORE_TEST"

sqlite3 "$RESTORE_TEST" 'PRAGMA integrity_check;'
VERISTOCK_DB_PATH="$RESTORE_TEST" python3 main.py status
```

再比對 row count 與 latest period：

```bash
python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

paths = {
    "current": Path(os.environ["VERISTOCK_DB_PATH"]),
    "restore_copy": Path("/tmp/veristock_restore_test.db"),
}
tables = {
    "daily_close": "trade_date",
    "attention_notices": "trade_date",
    "disposal_notices": "trade_date",
    "legal_investors": "trade_date",
    "margin_trading": "trade_date",
    "day_trading": "trade_date",
    "monthly_revenue": "revenue_month",
    "trading_days": "trade_date",
    "ops_jobs": "created_at",
}

for label, path in paths.items():
    print(f"[{label}] {path} bytes={path.stat().st_size}")
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        for table, period_col in tables.items():
            row = conn.execute(
                f"SELECT COUNT(*), MIN({period_col}), MAX({period_col}) FROM {table}"
            ).fetchone()
            print(f"{table}: count={row[0]} min={row[1]} max={row[2]}")
    finally:
        conn.close()
PY
```

驗證完成後刪除 `/tmp` copy：

```bash
rm -f "$RESTORE_TEST"
```

## 6. 正式 restore

只有第 4、5 步全部通過，才可正式覆寫：

```bash
cp -a "$BACKUP_PATH" "$VERISTOCK_DB_PATH.restore_source"
mv "$VERISTOCK_DB_PATH.restore_source" "$VERISTOCK_DB_PATH"
```

還原後立即驗證：

```bash
sqlite3 "$VERISTOCK_DB_PATH" 'PRAGMA integrity_check;'
python3 main.py status
python3 main.py ops-check --skip-systemd
```

若驗證失敗，保留現場，不要反覆覆寫。改用另一個 backup 或回報人工判斷。

## 7. 恢復服務

確認 DB 可讀、row count/latest period 正確後，再恢復 timer：

```bash
sudo systemctl start veristockdb-update-close.timer
sudo systemctl start veristockdb-update-legal.timer
sudo systemctl start veristockdb-update-attention.timer
sudo systemctl start veristockdb-update-disposal.timer
sudo systemctl start veristockdb-update-margin.timer
sudo systemctl start veristockdb-update-day-trading.timer
sudo systemctl start veristockdb-update-revenue.timer

systemctl list-timers 'veristockdb-*' --no-pager
```

## v0.6.3 Restore Drill Result

日期：2026-07-01

實測方式：

- 發現原 `veristock_latest_backup.db` 可讀且 `PRAGMA integrity_check` 為 `ok`，但只到 `2026-06-30`，且缺 `monthly_revenue`、`ops_jobs`，不可作為目前狀態 restore baseline。
- 建立時間戳備份：`$VERISTOCK_BACKUP_DIR/veristock_restore_drill_v063_20260701_212107.db`。
- 將 `veristock_latest_backup.db` 重建為目前 DB 的最新備份。
- 複製 latest backup 到 `/tmp/veristock_restore_drill_v063_latest.db` 做 restore copy 驗證。
- restore copy `PRAGMA integrity_check` 回傳 `ok`。
- restore copy 可用 `VERISTOCK_DB_PATH=/tmp/veristock_restore_drill_v063_latest.db python3 main.py status` 讀取。
- restore copy 驗證後已刪除。

已驗證的 latest backup：

- path: `$VERISTOCK_BACKUP_DIR/veristock_latest_backup.db`
- bytes: `4383870976`
- integrity: `ok`

Row count / latest period 比對結果：

| Table | Current count | Restore count | Current latest | Restore latest |
| --- | ---: | ---: | --- | --- |
| `daily_close` | 8715496 | 8715496 | 2026-07-01 | 2026-07-01 |
| `attention_notices` | 102605 | 102605 | 2026-07-01 | 2026-07-01 |
| `disposal_notices` | 7716 | 7716 | 2026-07-01 | 2026-07-01 |
| `legal_investors` | 5832010 | 5832010 | 2026-07-01 | 2026-07-01 |
| `margin_trading` | 8146089 | 8146089 | 2026-07-01 | 2026-07-01 |
| `day_trading` | 4037752 | 4037752 | 2026-07-01 | 2026-07-01 |
| `monthly_revenue` | 280711 | 280711 | 2026-05 | 2026-05 |
| `trading_days` | 6655 | 6655 | 2026-07-01 | 2026-07-01 |
| `ops_jobs` | 1 | 1 | 2026-07-01T09:47:03Z | 2026-07-01T09:47:03Z |

結論：`veristock_latest_backup.db` 於 2026-07-01 已重建並通過非破壞性 restore drill，可作為目前 DB 的 restore baseline。
