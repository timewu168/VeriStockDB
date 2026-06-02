# Ubuntu 私有部署備忘

狀態：v0.2.5 起支援環境變數路徑設定，作為 SSH 部署、排程、log、backup 的起點。

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
| 月封存 ZIP | `/mnt/veristock-cold/archive` | 冷資料，ZIP 驗證通過後可刪 loose CSV |
| DB backup | `/mnt/veristock-cold/backup` | 備份不與主 DB 放同顆硬碟 |

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

Ubuntu 私有部署建議設定：

```bash
export VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
export VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
export VERISTOCK_ARCHIVE_DIR=/mnt/veristock-cold/archive
export VERISTOCK_BACKUP_DIR=/mnt/veristock-cold/backup
```

若沒有設定，程式仍會使用 repo 內的 `data/` 預設路徑，維持 Windows 本機開發行為。

## Ubuntu 目錄建立

先確認冷資料 SSD 已掛載到 `/mnt/veristock-cold`。

```bash
sudo mkdir -p /srv/veristockdb/app/data/db
sudo mkdir -p /srv/veristockdb/app/data/csv/daily_close
sudo mkdir -p /mnt/veristock-cold/archive
sudo mkdir -p /mnt/veristock-cold/backup
sudo chown -R timewu:timewu /srv/veristockdb
sudo chown -R timewu:timewu /mnt/veristock-cold/archive /mnt/veristock-cold/backup
```

## 手動驗證

在 SSH 連線後：

```bash
cd /srv/veristockdb/app

export VERISTOCK_DB_PATH=/srv/veristockdb/app/data/db/veristock.db
export VERISTOCK_CSV_DIR=/srv/veristockdb/app/data/csv
export VERISTOCK_ARCHIVE_DIR=/mnt/veristock-cold/archive
export VERISTOCK_BACKUP_DIR=/mnt/veristock-cold/backup

python3 main.py status
python3 main.py update-close
python3 main.py status --problems --details
python3 main.py backup
```

確認 backup 寫入冷資料 SSD：

```bash
ls -lh /mnt/veristock-cold/backup
```

## 後續排程方向

systemd service/timer 之後應把上述環境變數寫入 service 檔，讓排程與手動 SSH 執行使用同一套路徑。

建議排程分工：

- `update-close`：每日收盤後或晚上執行。
- `rollback-close`：半夜執行三日回滾檢查。
- `backup`：每日或每週執行，backup 寫到冷資料 SSD。
