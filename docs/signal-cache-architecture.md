# 訊號快取架構

這份文件說明 LFP 與 3-axis CSV 在執行期間使用的快取，以及各層資料的用途。

## 磁碟快取

預設位置為：

```text
%LOCALAPPDATA%\PigBehaviorSync\signal-cache
```

若環境沒有 `LOCALAPPDATA`，則改用系統暫存目錄。快取不會寫入 `.pigproj`，也不應提交 Git。

每一份 CSV 會先以 chunk 讀取一次，建立：

- 一份共用的 `time_us.bin`，格式為 little-endian `float64`。
- 每個 channel 一份 `channel_<channel ID>.bin`，格式為 little-endian `float32`。
- 每個 channel 的全時段 overview。
- `metadata.json` 與 `COMPLETE` 完整性標記。

channel ID 只用來選擇對應檔案，不會被當成 CSV 欄位索引。例如 `Channels,2,5,260` 的 channel 260 仍然是第三個訊號欄。

快取識別包含原始 CSV 的絕對路徑、檔案大小、修改時間、所有 channel、格式版本與 overview 設定。檔案變更、版本不符、內容截斷或缺少 `COMPLETE` 時都會重建。

建立時先寫入同磁碟的隱藏暫存目錄，完成 flush 與 close 後才 rename 成正式目錄。取消或失敗會刪除暫存目錄，不會把半成品視為有效快取。

## 全時段 coarse

LFP 圖表在自動 step 模式下，使用完整錄製樣本數計算一次 step，目標約為全時段 5000 點。縮放時間軸不會改變 step，也不會重新解析 CSV。

raw 與 filtered coarse 使用相同的全域 sample index：

```text
0, step, 2 × step, 3 × step, ...
```

filtered coarse 的順序是「原始解析度濾波，再依相同 step 取樣」，不是先降採樣再濾波。第一次建立某組 filter settings 時會為所有 channel 建立同一組 coarse；之後切換 channel 可直接重用。

coarse 只供波形顯示與時間導航，不可作為頻譜、spectrogram、find peak 或其他精確分析的輸入。

## 播放區間 fine cache

縮放或平移時間軸後，會在背景預載所有 channel 的目前可視區間，並向左右各多載一個畫面寬度，減少小幅平移時重建 cache。為避免在全時段畫面誤載數小時資料，只有可視寬度不超過 120 秒時才走這條路。

若目前仍是大型全時段畫面，播放時改為預載：

```text
[前一個 30 秒窗口 | 目前窗口 | 下一個 30 秒窗口]
```

這份 fine cache 保留原始解析度，位於 RAM。選取範圍若落在預載區間內，濾波與分析會直接裁切這份資料，不必再次從 memmap 讀取。即使尚未載入影片，手動縮放至 120 秒內也會觸發預載。

播放進入下一個窗口後，舊的 raw 與 filtered fine entry 會被移除。raw cache 以總 bytes 限制；filtered cache 同時限制最多 32 筆及 128 MiB，並採 LRU（最近最少使用者先移除）。

## 區段濾波

精確分析一律讀取原始解析度 segment。zero-phase 濾波前會根據 sample rate、濾波器結構與最低啟用 cutoff，在左右載入 padding；濾波完成後再裁回使用者要求的 index 範圍。

filtered segment 的 cache key 包含：

- 原始檔 identity。
- channel ID。
- 起訖 sample index。
- 完整 filter settings。

因此變更 bandpass、notch、cutoff 或 quality 不會誤用舊結果。

## 清除與關閉

可使用 `Settings > Clear signal cache` 清除目前載入檔案的磁碟與 RAM 快取。清除前會先取消並等待背景預載，確保 Windows 檔案 handle 已關閉。

CSV 匯入會顯示進度與取消按鈕。關閉程式時也會先取消匯入與播放預載，避免 QThread 或 memmap handle 留在背景。

完整磁碟快取預設上限為 20 GiB，超過時會優先移除最舊的已完成快取。
