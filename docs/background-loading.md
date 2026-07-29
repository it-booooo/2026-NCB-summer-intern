# 背景載入、進度與取消

大型訊號工作會由 `QThread` worker 執行，GUI thread 只負責建立或更新
Qt widget、Matplotlib figure，以及套用 worker 回傳的純資料。

## 已移到背景執行的工作

- CSV 轉換為磁碟 cache，以及 overview/coarse cache 建立。
- 專案還原時的訊號 cache 準備。
- 資料完整性檢查與報告輸出。
- LFP segment 濾波、power spectrum 與 spectrogram 計算。
- 全時段 peak detection。
- filtered coarse 建立。
- LFP 圖片匯出所需的 segment、濾波與頻譜資料準備。

Matplotlib figure 的建立、標記繪製與 `QMessageBox` 顯示仍在 GUI thread
執行。Worker 不持有也不修改 QWidget、Axes、Canvas 或 Line2D。

## 避免舊結果覆蓋新檔案

每次工作都有唯一 request ID，並記錄來源檔案的：

- 絕對路徑
- 檔案大小
- 修改時間

套用結果前會同時確認 request ID 仍是最新、來源 identity 未改變，而且
widget 尚未被銷毀。因此快速選擇 A 檔後再選 B 檔時，晚完成的 A 結果會
被丟棄，不會蓋掉 B。

## 取消與關閉

取消採 cooperative cancellation。UI 設定 `threading.Event`，讀取 CSV
chunk、建立 cache 或分塊濾波時會定期檢查旗標並安全離開。不使用
`QThread.terminate()`，避免 Pandas、NumPy、SciPy 或檔案 handle 停在
不完整狀態。

程式關閉時會通知所有已知 worker 取消並等待結束。暫存報告與 cache
半成品會清除；只有完整寫入、flush 並關閉後的檔案才會成為有效 cache。

## 進度

長時間工作會顯示非 modal 進度視窗，所以載入期間主視窗仍可移動、取消
或關閉。進度按工作階段前進，例如讀取/濾波、分析、完成，不使用無限期
的忙碌指示。取消不顯示錯誤；真正的錯誤只由最新 request 顯示一次。

