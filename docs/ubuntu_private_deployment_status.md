# Ubuntu 私有部署驗證紀錄

驗證日期：2026-06-04
主機：`time-home-server`
部署版本：`v0.2.6`
狀態：通過，已可視為 Ubuntu 私有部署與備份閉環完成。

## 驗證結論

目前 VeriStockDB 已完成以下部署項目：

- Ubuntu server 手動執行流程正常。
- 主 SQLite DB 可讀。
- `daily_close` 批次狀態正常。
- 本機 2TB SSD backup 可寫入。
- backup DB 已完成還原測試。
- systemd timers 已建立並有實際執行紀錄。
- Google Drive 與 GCP VPS 異地備份機制已建立。

## 版本與路徑

驗證命令：

```bash
cd /srv/veristockdb/app
git describe --tags --always
python3 - <<'PY'
import config
print(config.APP_VERSION)
print(config.DB_PATH)
print(config.CSV_DIR)
print(config.ARCHIVE_DIR)
print(config.DEFAULT_BACKUP_PATH)
PY
```

觀察結果：

```text
v0.2.6
0.2.6
/srv/veristockdb/app/data/db/veristock.db
/srv/veristockdb/app/data/csv
/srv/veristockdb/app/data/csv/monthly_zip
/srv/veristockdb/app/data/backup/veristock_latest_backup.db
```

注意：上述 Python config 檢查是在互動 SSH shell 中執行，該 shell 沒有載入 `/etc/veristockdb/veristockdb.env`，所以 `ARCHIVE_DIR` 與 `DEFAULT_BACKUP_PATH` 顯示為 repo 預設值。systemd service 已透過 `EnvironmentFile=/etc/veristockdb/veristockdb.env` 使用冷資料 SSD 路徑，backup log 已驗證實際寫入 `/app/dirty_box/veristockdb/backup`。

若要在互動 SSH shell 使用與 systemd 相同的路徑，先執行：

```bash
set -a
. /etc/veristockdb/veristockdb.env
set +a
```

## 儲存配置

驗證命令：

```bash
df -h /
df -h /app/dirty_box
ls -lh /app/dirty_box/veristockdb/backup
ls -lh /app/dirty_box/veristockdb/archive
```

觀察結果：

```text
/dev/mapper/ubuntu--vg-ubuntu--lv  914G  8.8G  867G   1% /
/dev/sda2                          1.9T  2.1G  1.8T   1% /app/dirty_box

/app/dirty_box/veristockdb/backup:
veristock_latest_backup.db  1.2G

/app/dirty_box/veristockdb/archive:
Close_zip/
```

目前配置：

| 類型 | 路徑 | 驗證狀態 |
| --- | --- | --- |
| 主程式 | `/srv/veristockdb/app` | OK |
| 主 DB | `/srv/veristockdb/app/data/db/veristock.db` | OK |
| 熱 CSV | `/srv/veristockdb/app/data/csv` | OK |
| 冷資料 SSD | `/app/dirty_box` | OK |
| DB backup | `/app/dirty_box/veristockdb/backup/veristock_latest_backup.db` | OK |
| 封存 ZIP | `/app/dirty_box/veristockdb/archive/Close_zip` | OK |

## DB 狀態

驗證命令：

```bash
python3 main.py status
python3 main.py status --problems --details
```

觀察結果：

```text
daily_close
  OK       10140 batches

No problem batches found.
```

結論：目前 `daily_close` 批次狀態正常，沒有 `BLOCKED`、`RECHECK`、`MISSING` 問題批次。

## Backup 還原測試

驗證命令：

```bash
cp /app/dirty_box/veristockdb/backup/veristock_latest_backup.db /tmp/veristock_restore_test.db
VERISTOCK_DB_PATH=/tmp/veristock_restore_test.db python3 main.py status
rm /tmp/veristock_restore_test.db
```

觀察結果：

```text
daily_close
  OK       10140 batches
```

結論：backup DB 不只是有檔案，已確認可複製、可讀取、可被 VeriStockDB 正常使用。

## systemd 排程

驗證命令：

```bash
systemctl list-timers 'veristockdb-*'
systemctl is-enabled veristockdb-update-close.timer
systemctl is-enabled veristockdb-rollback-close.timer
systemctl is-enabled veristockdb-backup.timer
```

觀察結果摘要：

```text
veristockdb-update-close.timer    next 2026-06-04 15:30, last 2026-06-03 15:30
veristockdb-rollback-close.timer  next 2026-06-05 01:30, last 2026-06-04 01:30
veristockdb-backup.timer          next 2026-06-05 02:30
veristockdb-offsite-sync.timer    next 2026-06-05 03:30
```

結論：排程已載入，且 update / rollback 已有實際執行紀錄。backup timer 已列入排程，backup service 也已有手動執行紀錄。

## Log 檢查

驗證命令：

```bash
tail -n 50 /srv/veristockdb/logs/update-close.log
tail -n 50 /srv/veristockdb/logs/rollback-close.log
tail -n 50 /srv/veristockdb/logs/backup.log
```

觀察結果摘要：

```text
update-close:
INFO daily_close already current: latest=2026-06-02 target=2026-06-02
INFO no open trading days to update between 2026-06-03 and 2026-06-03

rollback-close:
INFO rollback-close target latest daily_close date: 2026-06-02
OK: 6 FIXED: 0 BLOCKED: 0 RECHECK: 0 MISSING: 0 SKIPPED: 0

backup:
backup written: /app/dirty_box/veristockdb/backup/veristock_latest_backup.db
```

結論：日常更新、三日回滾、DB backup 都有正常 log。`rollback-close` 已能不帶 `--date` 自動使用最新 Close 日期。

## 異地備份

目前已建立兩個異地備份機制：

- Google Drive
- GCP VPS

已觀察到：

```text
veristockdb-offsite-sync.timer
```

後續建議定期抽查：

- Google Drive 是否存在最新 backup。
- GCP VPS 是否存在最新 backup。
- 異地 backup 是否可下載回本機並通過 `VERISTOCK_DB_PATH=/tmp/... python3 main.py status` 還原測試。

## 待追蹤事項

- 互動 SSH shell 若要執行 archive / backup，需先載入 `/etc/veristockdb/veristockdb.env`，否則會使用 repo 預設路徑。
- `is-enabled` 的逐行輸出未留存於本次貼上的紀錄，後續若要補齊可再記錄三個 timer 是否皆為 `enabled`。
- 異地備份目前已建立機制，後續應補一次 Google Drive 與 GCP VPS 的抽樣還原測試紀錄。
