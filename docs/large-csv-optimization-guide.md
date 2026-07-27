# 20 小時 CSV 資料最佳化修改指引

## 1. 文件目的

本文件用來指導 LFP、3-axis 與資料完整性檢查功能支援長達 20 小時的 CSV 資料。

目前程式會將 CSV 的所有列與所有通道一次載入 Pandas DataFrame，之後又為 raw、filtered signal 與時間軸建立完整副本。短資料可以正常工作，但資料時間增加至 20 小時後，載入時間、記憶體峰值及 GUI 無回應時間都可能不可接受。

修改時應達成以下目標：

1. 匯入大型 CSV 時，GUI 不應長時間無回應。
2. 顯示一個通道時，不應載入或處理其他未使用通道。
3. overview 波形不應依賴所有原始點常駐記憶體。
4. 區段分析只讀取和處理所選區間。
5. 完整資料檢查與 peak detection 可分塊執行。
6. 不改變現有 CSV 格式、channel ID、時間單位、同步公式與濾波結果定義。

---

## 2. 現有資料流

主要呼叫流程如下：

```text
ImportController.import_signal()
  -> parse_lfp_csv_info()
       -> parse_signal_csv_metadata()
  -> WavePanel.set_lfp_info()
  -> WavePanel.plot_lfp()
  -> WavePanel.ensure_lfp_dataset()
  -> LfpDataset.from_csv()
  -> read_signal_csv()
  -> pandas.read_csv() 讀取完整 CSV
  -> LFP()
       -> 對所有通道建立 raw signal cache
       -> 對所有通道建立 filtered signal cache
       -> 最後才降採樣為繪圖點
```

主要相關檔案：

| 檔案 | 現有責任 | 主要風險 |
| --- | --- | --- |
| `src/data_import/import_controller.py` | CSV 匯入入口 | 同步觸發後續讀取 |
| `src/signal_data/csv_loader.py` | 解析 metadata、unit、TTL | header 重複開檔；TTL 整檔轉 list |
| `src/signal_data/readers/signal_reader.py` | 將 signal CSV 讀成 DataFrame | 一次讀完整檔案 |
| `src/signal_data/lfp_dataset.py` | 保存完整 DataFrame 與 signal cache | 所有資料常駐；多份完整副本 |
| `src/signal_data/lfp_processing.py` | 濾波及區段擷取 | 對完整陣列複製、遮罩及濾波 |
| `src/charts/lfp_chart.py` | 建立 LFP 圖表 | 預先處理所有通道及兩種 signal |
| `src/charts/acceleration_chart.py` | 讀取及繪製 3-axis | 重建圖表時重新讀完整 CSV |
| `src/data_validation/input_checks.py` | 完整性檢查 | 再次完整讀取並產生大型 boolean array |
| `src/ui/find_peak_panel.py` | 全時段 peak detection | 對完整時間軸與 signal 建立陣列 |

---

## 3. 修改前先確認資料規模

樣本數的估算公式：

```text
樣本數 = 20 × 60 × 60 × sample_rate_hz
       = 72,000 × sample_rate_hz
```

單一 `float64` 欄位的最低記憶體估算：

```text
欄位記憶體 = 樣本數 × 8 bytes
```

例如 1,000 Hz：

```text
72,000,000 samples/channel
約 576 MB/channel
```

八個訊號通道加一個時間欄，僅 DataFrame 數值約 5.2 GB。若 raw 與 filtered cache 各複製八個通道，總量可能超過 14 GB，尚未計入 CSV parser、濾波中間陣列、boolean mask 與 Python/Pandas 額外開銷。

開始修改前，應取得實際資料的：

- 檔案大小。
- 通道數。
- 各通道 sample rate。
- 總列數或錄製秒數。
- 缺值比例。
- 時間戳是否等間距且單調遞增。
- signal 是否可接受 `float32` 精度。

不要只用小型測試 CSV 判斷效能。

---

## 4. 建議目標架構

建議將資料分成三層：

```text
原始 CSV
  -> 一次性匯入 / 建立索引
      -> 磁碟快取（可選欄、可分段）
          -> overview cache（低解析度，供全時段繪圖）
          -> segment reader（原解析度，供區段分析）
          -> chunk iterator（供驗證與全時段 peak detection）
```

各層責任：

### 4.1 Metadata 層

只讀取 CSV header，保存：

- channel ID 與實際欄位位置。
- sample rate。
- unit。
- data header row。
- data row count。
- 起始與結束時間。
- 原始檔案 identity，例如 path、size、mtime。

### 4.2 Overview 層

只保存適合繪圖的低解析度資料，目標約 5,000～50,000 點/通道。

overview 不應只使用固定間隔抽樣，否則可能漏掉短暫 peak。優先考慮每個時間 bucket 保存：

- 第一點與最後一點，或
- minimum 與 maximum。

min/max envelope 比單純 `data[::step]` 更能保留尖峰外觀。

### 4.3 原始資料存取層

提供清楚且不依賴 UI 的介面：

```python
class SignalDataSource:
    def channels(self) -> list[int]: ...
    def sample_rate_hz(self, channel: int) -> float: ...
    def duration_s(self) -> float: ...
    def overview(self, channel: int, max_points: int) -> SignalSegment: ...
    def read_segment(
        self,
        channel: int,
        start_s: float,
        end_s: float,
    ) -> SignalSegment: ...
    def iter_chunks(
        self,
        channels: list[int],
        chunk_rows: int,
    ): ...
```

UI、圖表、驗證及 peak detection 應依賴這個介面，而不是直接依賴完整 Pandas DataFrame。

### 4.4 背景工作層

大型操作應放在 Qt worker/thread：

- 建立磁碟快取。
- 建立 overview。
- 讀取大型 segment。
- 全時段資料檢查。
- 全時段 peak detection。

worker 必須提供：

- progress。
- cancel。
- success result。
- error result。
- 工作完成後安全更新 UI 的 signal。

---

## 5. 分階段修改方案

不要一次把 DataFrame、繪圖、分析及驗證全部替換。以下每個階段都應能獨立測試及回退。

## Phase 0：建立基準與測試資料

### 修改內容

先建立不提交大型原始資料的 benchmark 工具或測試 fixture，可產生：

- 多通道 CSV。
- 可設定 sample rate 與 duration。
- 固定可預測的正弦波及 peak。
- 可插入缺值、重複 timestamp、時間不連續。

至少記錄：

- metadata parse 時間。
- 首次顯示時間。
- 切換通道時間。
- 讀取 10 秒 segment 時間。
- peak memory。
- 取消背景工作所需時間。

### 驗收標準

- 同一份測試資料每次產生相同結果。
- 能比較修改前後的時間與記憶體。
- 測試資料包含非連續 channel ID，例如 `[2, 5, 260]`。

### 注意事項

- 測試產生器不要一次在 Python list 中建立所有文字列。
- 大型 benchmark 檔案不要提交 Git。
- Windows 上應確認測試結束後檔案 handle 已關閉，否則暫存檔無法刪除。

---

## Phase 1：低風險減少重複讀取與複製

### 5.1 合併 header scan

修改 `src/signal_data/csv_loader.py`，讓一次 header scan 同時取得：

- channels。
- sample rates。
- unit。
- header row。
- data column count。

可以新增：

```python
def parse_signal_csv_header(path) -> dict:
    ...
```

`parse_lfp_csv_info()` 僅呼叫此函式一次。保留既有 `parse_signal_csv_metadata()` 與 `parse_signal_csv_units()` 時，可讓它們包裝新函式以維持相容性。

這項修改只減少兩次 header 開檔，不會解決主要的大型資料瓶頸，因此不要把它當作 20 小時支援已完成。

### 5.2 明確指定 dtype

在 `read_signal_csv()` 中評估並明確指定：

```python
dtype = {
    "time_us": "int64",
    "channel_x": "float32",
}
```

但因為目前 `header=None`、`names=...` 與 `usecols=...` 同時使用，需先用實際 Pandas 版本測試 dtype key 是以來源欄位位置還是指定後名稱解析。

如果 timestamp 可能缺值，普通 NumPy `int64` 無法表示 `NaN`。可選：

- Pandas nullable `Int64`。
- 讀成 `float64`。
- 匯入時將非法 timestamp 視為錯誤。

不可未確認資料規格就直接改成 `int64`。

### 5.3 避免 raw signal 無條件複製

檢查 `LfpDataset.signal_values()` 與 `_finite_signal()`：

- 若欄位已經是需要的 dtype，優先取得 view。
- 若所有值 finite，不要再次 `copy()`。
- 只有存在 NaN/Inf 且需要插值時才建立新陣列。

注意：回傳 view 後，呼叫端不得原地修改。建議將這項契約寫入 docstring，並讓濾波函式產生自己的輸出。

### 5.4 快取時間陣列

不要讓 `time_us` 與 `record_time_s` property 每次都重新轉型或除法。可在 dataset 初始化時建立一次，或使用 lazy cached property。

注意：

- `time_us` 的 canonical unit 仍是 microseconds。
- `record_time_s = time_us / 1_000_000`。
- 不要把同步 offset 混入 dataset 的 canonical 時間。

### Phase 1 驗收

- 相同 CSV 的 channels、sample rates、unit 完全相同。
- raw waveform 數值相同。
- filtered waveform 在既定 tolerance 內相同。
- metadata 只開啟 CSV 一次。
- 重複呼叫 `time_us`/`record_time_s` 不重建完整陣列。

---

## Phase 2：只處理選取通道

這是最應優先實作、效益也最高的行為修改。

### 5.5 修改 LFP 圖表初始化

目前 `src/charts/lfp_chart.py` 會遍歷 `dataset.channels`，並為每個通道建立 raw 與 filtered line。

改為：

1. 圖表初始化時只取得 `selected_channel`。
2. 只建立目前顯示模式需要的資料。
3. 切換 raw/filtered 時才計算缺少的版本。
4. 切換 channel 時更新既有 Matplotlib line，不為每個通道保留一條隱藏 line。

建議圖表僅保存：

```python
current_channel: int
current_view: Literal["raw", "filtered"]
line: Line2D
```

不要保存 `(channel, filtered) -> Line2D` 的所有組合。

### 5.6 Reader 必須正確映射 channel ID

`requested_channels` 是 channel ID，不是 CSV 欄位索引。以下例子必須正確：

```text
Channels,2,5,260
```

請沿用：

```python
available_channels.index(channel) + 1
```

不要把 channel 260 當成第 260 欄。

### 5.7 3-axis 共用資料存取策略

`acceleration_chart.py` 不應在每次重建圖表時重新完整讀檔。至少先加入針對 path + channel 的 cache；最終應使用相同 `SignalDataSource`。

### Phase 2 驗收

- 匯入八通道檔案、顯示一個通道時，只解析該通道與時間欄。
- 切換通道後波形正確。
- raw/filtered 切換正確。
- 更改 plot step 不重新解析整份 CSV。
- 非連續 channel ID 正確。
- 原本選取 channel 在 project restore 後仍可恢復。

---

## Phase 3：overview 與原始 segment 分離

只載入一個通道仍可能無法承受 20 小時高取樣率資料，因此需要停止讓整個選取通道常駐記憶體。

### 5.8 建立 overview

匯入 CSV 時以 chunk 讀取：

```python
pd.read_csv(..., chunksize=chunk_rows)
```

對每個 chunk 累計時間 bucket 的 min/max，最後建立 overview。

overview cache key 至少包含：

- 原始 CSV 絕對路徑。
- 檔案大小。
- 修改時間。
- channel ID。
- overview 演算法版本。
- max points 或 bucket 設定。

不能只以 filename 當 key，否則同名檔案可能誤用舊 cache。

### 5.9 建立可分段讀取的磁碟格式

Pandas 對 CSV 無法有效從中間時間隨機讀取。建議匯入時轉換成以下其中一種格式：

- NumPy memmap：結構簡單、讀取快速，但 metadata 與多欄管理需自行設計。
- HDF5：適合分欄與分段，但需確認封裝及 PyInstaller dependency。
- Parquet/Arrow：壓縮與欄位選擇佳，但 row group 與時間區間索引需設計。

選擇前應確認：

- Windows 與 PyInstaller 打包是否穩定。
- 是否新增大型 dependency。
- 20 小時實際資料的轉換時間。
- segment 隨機讀取延遲。
- cache 被中斷時能否辨識不完整檔案。

### 5.10 原子化建立 cache

不要直接寫最終 cache 路徑。流程應為：

1. 寫入同一磁碟上的暫存檔。
2. 寫完 metadata 與完整性標記。
3. flush/close。
4. 原子 rename 成正式 cache。

如果使用者取消、程式崩潰或磁碟空間不足，不應留下會被當成有效資料的半成品。

### 5.11 Segment 使用索引而非全陣列 mask

若時間軸單調遞增：

```python
left_index = np.searchsorted(time_us, start_us, side="left")
right_index = np.searchsorted(time_us, end_us, side="right")
```

然後只讀 `[left_index:right_index]`。

若資料可能有 timestamp 倒退，匯入/驗證階段必須偵測，不能在未驗證條件下使用 `searchsorted()`。

### Phase 3 驗收

- 全時段圖表只使用 overview。
- 放大或執行分析時才讀取原始 segment。
- 任意時間區間的第一點、最後一點與舊版一致。
- overview 能保留測試資料中的窄 peak。
- cache 過期、被截斷或版本不符時會重建。
- 取消 cache 建立後不會留下有效狀態的半成品。

---

## Phase 4：區段濾波與分析

### 5.12 不要為小區段濾波完整 20 小時

頻譜、spectrogram 與手動選取區間只應處理 segment。

zero-phase filter 會有邊界效應。讀取 segment 時應向左右額外讀取 padding：

```text
requested interval
    [----------------]
loaded interval
[pad--------------------pad]
```

濾波後再裁切回 requested interval。

padding 長度需依 filter 設計、sample rate 與最低 cutoff 決定，不要只固定幾個 sample。

### 5.13 區分 overview filter 與分析 filter

先降採樣再濾波，和先濾波再降採樣的結果不同。必須明確定義：

- overview 僅供視覺導航，不作精確分析。
- 分析結果一律使用原始解析度 segment。
- filtered overview 若要顯示，可另外建立，不能被當成分析輸入。

### 5.14 控制 cache 大小

不要永久保存每個 channel × 每組 filter settings × 完整時段。

可使用有上限的 LRU cache，key 包含：

- source identity。
- channel。
- start/end sample index。
- filter settings。

限制可用：

- 最大 entry 數。
- 最大總 bytes。
- 切換資料檔時全部失效。

### Phase 4 驗收

- 相同 segment 與舊版完整濾波結果在排除邊界後相符。
- 不同 sample rate 的 padding 正確。
- filter settings 改變時不會誤用舊 cache。
- 多次分析不同區間，記憶體不持續無上限增加。

---

## Phase 5：背景載入、進度與取消

### 5.15 UI thread 限制

以下操作不可在 GUI thread 執行：

- 完整 CSV parse。
- cache conversion。
- 大型 overview 建立。
- 大型 segment 濾波。
- 全時段 peak detection。
- 完整資料檢查。

### 5.16 Worker 回傳規則

worker 不應直接操作 QWidget 或 Matplotlib。worker 只回傳純資料或錯誤，由 GUI thread 更新畫面。

需要防止 stale result：

1. 使用者開始載入檔案 A。
2. A 尚未完成時改選檔案 B。
3. A 完成後不得覆蓋 B 的狀態。

可為每次工作建立 request ID，套用結果前確認：

- request ID 仍是最新。
- source path/identity 仍相同。
- widget 尚未銷毀。

### 5.17 取消設計

取消應是 cooperative cancellation。每處理一個 chunk 檢查取消旗標。

不要強制 terminate 正在執行 Pandas、NumPy 或 SciPy 的 thread，這可能留下無效狀態或無法釋放的資源。

### Phase 5 驗收

- 載入時視窗仍可拖動、取消及關閉。
- progress 會前進，不長期停在不明狀態。
- 快速切換 A/B 檔案不會顯示 A 的舊結果。
- 關閉應用程式時 worker 能安全結束。
- 錯誤只顯示一次，且 UI 狀態可再次匯入。

---

## Phase 6：資料檢查改為 chunk streaming

`input_checks.py` 不應建立完整 DataFrame 或完整 boolean mask。

### 5.18 Chunk 累計狀態

每個 chunk 累計：

- row count。
- missing value count。
- duplicate timestamp count。
- discontinuous timestamp count。
- 異常明細。
- 前一個 chunk 最後一筆有效 timestamp。

chunk 邊界必須檢查：

```text
previous_chunk.last_timestamp -> current_chunk.first_timestamp
```

否則會漏掉剛好發生在 chunk 邊界的重複或不連續。

### 5.19 異常報告大小

如果檔案有大量缺值，將每個異常都存入 `results` 仍可能耗盡記憶體。

應選擇並明確顯示：

- 報告所有異常並串流寫出，或
- 設定最大明細數，同時保留完整總數。

如果串流寫報告，summary 通常要到最後才知道。可先寫暫存明細，再產生最終報告；或調整報告順序。

### Phase 6 驗收

- chunk size 改變不影響統計結果。
- chunk 邊界的 duplicate/discontinuity 能被偵測。
- 大量缺值時記憶體維持有界。
- 報告中的 CSV line number 與原始檔案一致。

---

## Phase 7：全時段 peak detection 分塊

`find_peak_panel.py` 目前會取得完整 signal 與完整 `video_times`。改成 chunk 時要處理演算法邊界。

### 5.20 Chunk overlap

`scipy.signal.find_peaks()` 的 prominence 與 distance 可能跨越 chunk 邊界。每個 chunk 需要 overlap，並在輸出時：

- 去除重疊區的重複 peak。
- 依全域 sample index 執行 minimum distance 去重。
- 保留足夠鄰域計算 prominence。

### 5.21 全域 baseline 定義

如果 threshold 使用整份資料的 mean/std/median/MAD，不能直接用每個 chunk 自己的統計量，否則結果會改變。

選項：

1. 第一遍串流計算全域統計量，第二遍找 peak。
2. 使用可合併的線上統計演算法。
3. 明確將演算法改為局部 baseline，但這是產品行為改變，需另外確認。

### Phase 7 驗收

- 將同一資料用不同 chunk size 執行，peak 結果一致。
- chunk 邊界附近的 peak 不遺漏、不重複。
- marker 的 record time、video time 與 channel payload 正確。
- 使用者取消時不會先清除舊 marker 再留下空結果。

---

## 6. API 與相容性注意事項

### 6.1 保留時間 domain

canonical 關係不可改變：

```text
record_time_s = time_us / 1_000_000
video_time_s = record_time_s + time_offset_sec
```

資料層只保存 record time。`time_offset_sec` 屬於同步/UI 層。

### 6.2 Channel ID 不是位置

所有 public API 都應接受 channel ID：

```python
read_segment(channel=260, ...)
```

內部才將 ID 映射到 CSV 欄位位置。

### 6.3 不把 cache 寫入 `.pigproj`

`.pigproj` 應保存原始 source identity 與使用者狀態，不應嵌入數 GB 的資料 cache。restore 時驗證原始檔案 identity，再重用或重建本機 cache。

### 6.4 檔案變更與 cache invalidation

至少使用：

- resolved path。
- file size。
- modification time。
- cache schema version。

若資料正確性要求更高，可以額外保存 sampled hash。只靠 path 不足以判斷檔案是否已被替換。

### 6.5 Pandas chunk 的 dtype 一致性

不同 chunk 可能因缺值或非法字串推斷出不同 dtype。必須明確指定 dtype 或在每個 chunk 做相同的 coercion/validation。

### 6.6 `float32` 精度

signal 改為 `float32` 可將記憶體減半，但需用實際資料驗證：

- 原始 ADC 精度。
- peak threshold。
- 濾波後最大誤差。
- PSD/spectrogram tolerance。

timestamp 不建議使用 `float32`。20 小時的 microsecond timestamp 會失去足夠精度。

### 6.7 CSV quoting 與 encoding

保留目前的 `utf-8-sig` 與標準 CSV parser 行為。不要用單純字串 `split(",")` 取代 `csv.reader`，否則 quoted field、空欄位及 BOM 可能解析錯誤。

### 6.8 Filter state

若全時段濾波改成 chunk causal filter，必須跨 chunk 傳遞 filter state。若仍要求與 `filtfilt` 完全一致，不能直接用逐 chunk `filtfilt`，因為每個邊界都會產生不同結果。

### 6.9 Matplotlib 資料生命週期

`Line2D` 可能保存傳入陣列的參考。更新 line 後，要確認舊資料能釋放；不要同時把相同大型陣列留在 dataset cache、figure cache 與 UI state。

### 6.10 錯誤處理

大型匯入至少應區分：

- 檔案不存在或途中被移除。
- 權限不足。
- 磁碟空間不足。
- CSV 格式錯誤。
- timestamp 無法解析。
- cache 版本不符或損毀。
- 使用者取消。

取消不應顯示成「匯入失敗」。

---

## 7. 測試清單

### 7.1 CSV 格式

- UTF-8 與 UTF-8 BOM。
- `Unit` 與 `Units`。
- metadata 列順序不同。
- header 前有額外資訊列。
- 空檔案。
- 缺少 `Time[us]`。
- 缺少 channel metadata。
- 非連續 channel ID。
- 欄位中有空白。
- data row 欄位數不一致。

### 7.2 時間

- 從 0 開始。
- 非 0 開始。
- 大於 20 小時。
- duplicate timestamp。
- discontinuity。
- timestamp 倒退。
- chunk 邊界異常。
- microsecond 精度維持。

### 7.3 Signal

- 正常 finite signal。
- NaN。
- positive/negative infinity。
- 全欄缺值。
- 單點及極短 segment。
- 不同 sample rate。
- 不同 filter settings。
- peak 位於 chunk 邊界。

### 7.4 UI

- 匯入後立即取消。
- 載入 A 時改選 B。
- 載入時關閉視窗。
- 重複開啟同一檔案。
- 原始檔案修改後重新開啟。
- 切換 channel。
- raw/filtered 切換。
- zoom、pan、timeline 同步。
- project save/restore。

### 7.5 效能

至少測試：

- 小檔案：確認沒有明顯額外延遲。
- 中型檔案：可快速反覆測試。
- 接近實際 20 小時的檔案。

記錄：

```text
metadata parse:
cache build:
first overview:
channel switch:
10-second segment:
peak detection:
validation:
peak RSS:
cache size:
```

---

## 8. 建議的完成定義

20 小時支援不應只以「成功載入一次」判定。建議完成條件：

- GUI 在大型匯入期間仍可回應。
- 使用者可取消。
- overview 的常駐記憶體與總錄製樣本數近似無關。
- 顯示一個通道時不載入其他通道的原始資料。
- 讀取短 segment 的成本與完整錄製長度近似無關。
- 重複切換 channel/filter 不會讓記憶體無上限成長。
- chunk validation 與舊版小檔案結果一致。
- chunk peak detection 不受 chunk size 影響。
- cache 損毀、過期或建立中斷時可以安全重建。
- project save/restore 不保存大型衍生資料，且不破壞現有格式。

---

## 9. 建議實作順序摘要

```text
1. 建立 benchmark 與回歸 fixture
2. 合併 header scan
3. 明確 dtype、減少 raw/time array 複製
4. 圖表只處理目前 channel 與目前 signal view
5. 3-axis 避免重複完整讀取
6. 建立 chunk reader 與 overview
7. 建立可分段讀取的磁碟 cache
8. segment 改為索引擷取
9. 區段濾波與有界 LRU cache
10. 導入背景 worker、progress、cancel、stale-result protection
11. validation 改為 streaming
12. peak detection 改為帶 overlap 的 streaming
13. 使用實際 20 小時資料做最終壓力測試
```

其中第 4 步可快速降低多通道記憶體；第 6～8 步才是讓 20 小時高取樣率資料真正可互動使用的核心。
