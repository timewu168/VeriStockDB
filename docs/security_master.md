# 官方證券主檔

狀態：`v0.7.0` 起納入 VeriStockDB canonical SQLite truth，提供股票名稱、產業別與生效期間，供 active disposal API 使用。

## 官方來源

| 市場 | 端點 | 使用欄位 |
| --- | --- | --- |
| TWSE | `https://openapi.twse.com.tw/v1/opendata/t187ap03_L` | `出表日期`、`公司代號`、`公司簡稱`、`產業別` |
| TPEX | `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O` | `Date`、`SecuritiesCompanyCode`、`CompanyAbbreviation`、`SecuritiesIndustryCode` |

原始 JSON 會依來源日期封存於 `data/csv/security_master/YYYY/`，canonical rows 同時保存 `source_updated_date` 與 `source_url`。

## 更新與資料模型

```bash
python3 main.py update-security-master
python3 main.py update-security-master --market TWSE --no-cooldown
```

`security_master` 以 `(market, stock_id, effective_from)` 為主鍵。當名稱或產業異動時，舊版本會填入 `effective_to`，新版本從來源日期起生效；同日重跑可修正同一版本，不會製造重複 current row。

## 品質邊界

- 每個市場必須是非空完整快照，正式匯入最低筆數為 `100`。
- 必填欄位、來源日期、代號唯一性與產業代碼都必須通過驗證。
- 未知產業代碼、過期快照或不一致日期會擋下整批，不部分寫入 canonical rows。
- 產業名稱由市場別明確 mapping，不從公告文字推測。
- active disposal API 只接受能在有效期間對上主檔的四碼股票；衍生商品不會冒用標的股票產業。

## API 使用邊界

`security_master` 目前透過 dataset status、health 與 jobs API 管理，不提供任意全文主檔匯出 endpoint。下游處置股專案應使用 `GET /api/v1/disposal-notices/active`，不要直接讀 SQLite 或自行重解官方處置文字。
