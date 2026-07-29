# 訊號 CSV 基準測試

請在專案根目錄使用專案的 Python 環境執行：

```powershell
python -m benchmarks.run_signal_benchmark `
  --sample-rate 1000 `
  --duration 300 `
  --with-anomalies `
  --output benchmark-results\signal.csv `
  --result benchmark-results\baseline.json
```

修改程式後，以不同的 `--result` 檔名再次執行相同指令，即可比較修改前後的
JSON 結果。`benchmark-results/` 目錄與所有產生的 CSV 檔案都已由 Git 忽略，
不會誤將大型測試資料提交到版本庫。

測試資料固定使用非連續 channel ID：`2`、`5`、`260`。加入
`--with-anomalies` 後，產生器會在固定位置插入缺值、重複 timestamp 與時間
不連續。訊號頻率及 peak 的位置與振幅也都是固定的，因此相同參數每次都會
產生內容完全相同的檔案。

## 參數說明

- `--sample-rate`：每秒取樣數，預設為 `1000` Hz。
- `--duration`：測試訊號長度，單位為秒，預設為 `30` 秒。
- `--with-anomalies`：插入固定且可重現的異常資料。
- `--output`：保留產生的 CSV 測試資料；未指定時會使用可自動清除的暫存目錄。
- `--result`：將 benchmark 結果寫入指定的 JSON 檔案。

產生器會逐列將資料寫入檔案，不會先在 Python list 中建立全部文字列。背景
產生工作也支援透過 cancellation event 中止。

## 量測指標

除了 `peak_memory_bytes` 以 byte 表示之外，其餘時間指標都使用秒：

- `metadata_parse_s`：解析 channel、sample rate、表頭與單位所需時間。
- `first_display_s`：第一次建立多通道 memmap 與 raw coarse 所需時間。
- `channel_switch_s`：從已建立的全通道 coarse 切換至第二個 channel 所需時間。
- `segment_10s_s`：從 memmap 以 sample index 讀取前 10 秒原始解析度資料所需時間。
- `peak_memory_bytes`：benchmark process 的 peak resident working set。
- `background_cancel_s`：送出取消通知至 cache conversion 背景執行緒結束所需時間。

輸出的 `observations` 也會記錄首次顯示及 10 秒 segment 的資料列數，方便確認
不同版本量測的是相同資料範圍。`background_cancel_observed` 應為 `true`。

benchmark 走正式程式使用的 `LfpDataset`／`SignalDataSource`，不是另外以 Pandas
完整讀取 CSV。因此可用相同參數各執行一次修改前與修改後版本，再比較兩份
`--result` JSON。

## 執行自動測試

```powershell
python -m unittest discover -s tests -v
```

測試會驗證：

- 相同設定產生的檔案具有相同 SHA-256 結果。
- metadata 包含 `[2, 5, 260]`。
- 缺值、重複 timestamp 與時間不連續位於預期位置。
- CSV 讀取完成後可立即刪除暫存檔；此項目可在 Windows 上確認檔案 handle
  沒有殘留。
