# Ubuntu 私有部署備忘

狀態：v0.2.5 起支援環境變數路徑設定；v0.2.6 起提供 systemd service/timer 範本。

## 硬碟分層

Ubuntu server 目前有兩顆硬碟：

- M.2 1TB：熱資料與主要執行環境。
- SSD 2TB：冷資料、封存 ZIP、DB backup。

建議分配如下：

| 類型 | 建議位置 | 說明 |
| --- | --- | --- |
| Git repo / CLI 程式 | `/srv/veristockdb/app` | 主程式、未來 API/PWA |
| 主 SQLite DB | `/srv/veristockdb/app/data/db/veristock.db` | 熱資料，日常查詢與匯入會使用 |
| 未封存 Close CSV | `/srv/veristockdb/app/data/csv/daily_close` | 月封存前暫存 |
| 月封存 ZIP | `/app/dirty_box/veristockdb/archive` | 冷資料，ZIP 驗證通過後可刪 loose CSV |
| DB backup | `/app/dirty_box/veristockdb/backup` | 備份不與主 DB 放同顆硬碟 |
| log | `/srv/veristockdb/logs` | systemd 執行紀錄 |

長期歷史 CSV 散檔若已完成 ZIP 封存且驗證通過，不需要再保留另一份 loose CSV。保留封存 ZIP 即可。

## 環境變數

v0.2.5 支援以下環境變數：

| 變數 | 用途 | 預設值 |
| --- | --- | --- |
| `VERISTOCK_DATA_DIR` | 資料根目錄 | `<repo>/data` |
| `VERISTOCK_CSV_DIR` | 熱 CSV 目錄 | `<data>/csv` |
| `VERISTOCK_DB_DIR` | DB 目錄 | `<data>/db` |
| `VERISTOCK_DB_PATH` | 主 SQLite DB 檔案 | `<db_dir>/veristock.db` |
| `VERISTOCK_TRADING_DAY_SEED_DB` | 交易日種子 DB | `<db_dir>/trading_days.db` |
| `VERISTOCK_BACKUP_DIR` | DB backup 目錄 | `<data>/backup` |
| `VERISTOCK_BACKUP_PATH` | 最新 DB backup 檔案 | `<backup_dir>/veristock_latest_backup.db` |
| `VERISTOCK_ARCHIVE_DIR` | 月封存 ZIP 目錄 | `<csv_dir>/monthly_zip` |
| `VERISTOCK_LOG_DIR` | ops-check 檢查的 log 目錄 | `<repo>/logs` |

Ubuntu 私有部署建議設定：

```bash
export VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
export VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
export VERISTOCK_ARCHIVE_DIR=/app/dirty_box/veristockdb/archive
export VERISTOCK_BACKUP_DIR=/app/dirty_box/veristockdb/backup
export VERISTOCK_LOG_DIR=/srv/veristockdb/logs
```

若沒有設定，程式仍會使用 repo 內的 `data/` 預設路徑，維持 Windows 本機開發行為。

## Ubuntu 目錄建立

先確認冷資料 SSD 已掛載到 `/app/dirty_box`。

```bash
sudo mkdir -p /srv/veristockdb/app/data/db
sudo mkdir -p /srv/veristockdb/app/data/csv/daily_close
sudo mkdir -p /srv/veristockdb/logs
sudo mkdir -p /app/dirty_box/veristockdb/archive
sudo mkdir -p /app/dirty_box/veristockdb/backup
sudo chown -R timewu:timewu /srv/veristockdb
sudo chown -R timewu:timewu /app/dirty_box/veristockdb
```

## 手動驗證

在 SSH 連線後：

```bash
cd /srv/veristockdb/app

export VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
export VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
export VERISTOCK_ARCHIVE_DIR=/app/dirty_box/veristockdb/archive
export VERISTOCK_BACKUP_DIR=/app/dirty_box/veristockdb/backup

python3 main.py status
python3 main.py update-close
python3 main.py status --problems --details
python3 main.py backup
python3 main.py ops-check --skip-systemd
```

確認 backup 寫入冷資料 SSD：

```bash
ls -lh /app/dirty_box/veristockdb/backup
```

## systemd 排程安裝

範本位於：

```text
deploy/systemd/
```

先建立環境變數檔：

```bash
sudo mkdir -p /etc/veristockdb
sudo cp /srv/veristockdb/app/deploy/systemd/veristockdb.env.example /etc/veristockdb/veristockdb.env
sudo chown root:root /etc/veristockdb/veristockdb.env
sudo chmod 0644 /etc/veristockdb/veristockdb.env
```

確認內容符合本機硬碟配置：

```bash
cat /etc/veristockdb/veristockdb.env
```

目前 private server 建議內容：

```text
VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
VERISTOCK_ARCHIVE_DIR=/app/dirty_box/veristockdb/archive
VERISTOCK_BACKUP_DIR=/app/dirty_box/veristockdb/backup
VERISTOCK_LOG_DIR=/srv/veristockdb/logs
```

安裝 service 與 timer：

```bash
sudo cp /srv/veristockdb/app/deploy/systemd/veristockdb-*.service /etc/systemd/system/
sudo cp /srv/veristockdb/app/deploy/systemd/veristockdb-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

建議排程分工：

- `veristockdb-update-close.timer`：週一至週五 19:30 執行 `update-close`。
- `veristockdb-rollback-close.timer`：週二至週六 01:30 執行 `rollback-close`。
- `veristockdb-backup.timer`：每日 02:30 執行 `backup`，backup 寫到冷資料 SSD。

先手動測 service：

```bash
sudo systemctl start veristockdb-update-close.service
sudo systemctl start veristockdb-rollback-close.service
sudo systemctl start veristockdb-backup.service
```

查看狀態：

```bash
systemctl status veristockdb-update-close.service --no-pager
systemctl status veristockdb-rollback-close.service --no-pager
systemctl status veristockdb-backup.service --no-pager
```

查看 log：

```bash
tail -n 100 /srv/veristockdb/logs/update-close.log
tail -n 100 /srv/veristockdb/logs/rollback-close.log
tail -n 100 /srv/veristockdb/logs/backup.log
```

執行正式部署健康檢查：

```bash
python3 main.py ops-check
```

`ops-check` 會檢查：

- 主 DB 是否存在且可讀。
- backup DB 是否存在且可讀。
- archive 目錄是否存在。
- `update-close` / `rollback-close` / `backup` log 是否存在。
- 三個 `veristockdb-*` timer 是否啟用。

確認手動 service 都正常後，再啟用 timer：

```bash
sudo systemctl enable --now veristockdb-update-close.timer
sudo systemctl enable --now veristockdb-rollback-close.timer
sudo systemctl enable --now veristockdb-backup.timer
```

列出排程：

```bash
systemctl list-timers 'veristockdb-*'
```
