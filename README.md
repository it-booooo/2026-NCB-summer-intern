# Pig Behavior Sync 使用者操作手冊

Pig Behavior Sync 是一套用於動物行為實驗的 Windows 桌面工具，可同時檢視行為影片、LFP 與三軸感測訊號，並透過影片中的 LED 事件及記錄端 TTL 時間標記對齊兩條時間軸。程式也提供事件標記、LFP 峰值偵測、LED 自動偵測、資料檢查、圖表匯出及分析專案保存功能。

## 主要功能

- 播放 MP4 行為影片，支援逐格移動、跳至指定時間／影格，以及 90°、180° 旋轉。
- 顯示 LFP 與三軸訊號，共用可拖曳的時間範圍。
- 選擇 LFP channel，套用 band-pass 與電源雜訊 notch filter。
- 顯示 LFP power spectrum 與 spectrogram。
- 匯入或手動新增 TTL 時間標記。
- 在影片上建立 LED On、LED Off、Action Start、Action End 與 Seizure-like 標記。
- 選取影片中的 LED ROI，自動分析亮度變化並建立 LED 事件。
- 使用第一個 LED On 與第一個 TTL 自動計算影片／記錄時間差。
- 在同步後的 LFP 訊號中尋找正向與負向峰值。
- 將標記、檢查結果與各類分析圖匯出成 CSV、Excel 或圖片。
- 將工作狀態儲存為 .pigproj，稍後繼續分析。

## 系統需求

- Windows 10／11
- 可讀取的 MP4、LFP／三軸 CSV 或 TTL CSV 實驗資料
- OpenCL 相容 GPU 與驅動程式為選用項目；沒有可用 GPU 時，LED 偵測會改用 CPU

本程式不需要安裝 Python 或其他套件。

## 取得與啟動程式

正式交付版本為 PigBehaviorSync.exe。

使用方式：

1. 將 PigBehaviorSync.exe 複製到本機資料夾。
2. 雙擊執行程式。
3. 從「File > Import」選擇自己的影片及 CSV 資料。

程式是單一執行檔，不需執行安裝程序，也不需要下載額外的 Python 套件。第一次啟動或第一次分析大型影片時，Windows 防毒軟體可能需要較長時間檢查檔案。

> **GPU 加速說明：** 電腦若有相容的 GPU 與 OpenCL 驅動，程式會用它加速 LED 偵測；沒有可用 GPU 時會自動改用 CPU，不影響其他功能。

## 輸入資料格式

### 行為影片

- 格式：.mp4
- 程式會讀取影片的 FPS、總影格數、尺寸及播放時間。
- 若影片 metadata 中的 FPS 不可靠，實際同步結果也可能受到影響。

### LFP 與三軸 CSV

訊號 CSV 需包含 metadata 列及「Time[us]」表頭。程式會辨識：

- 「Channels」：各資料欄對應的 channel 編號。
- 「Sample Rate...」：各 channel 的 sampling rate。
- 「Unit」或「Units」：訊號單位（選填）。
- 「Time[us]」：資料區起始表頭；其後每列第一欄為微秒時間，其餘欄位為各 channel 數值。

Time[us] 必須是有效數字，時間順序不可往回遞減，且資料區至少需要兩筆訊號資料，否則可能無法顯示波形或進行分析。

概念範例：前三列依序填寫 Channels、Sample Rate[Hz] 與 Unit；接著以 Time[us] 作為資料表頭，後續每列填寫時間與各 channel 數值。

目前三軸顯示流程會使用 channel 260，因此三軸資料應包含該 channel。

### TTL Time Marker CSV

TTL CSV 建議包含：

- 一個名稱以「_time(us)」結尾的絕對時間欄位。
- 「record_time(us)」、「recording_time(us)」或「record time(us)」記錄時間欄位。

舊格式若無上述欄名，程式會嘗試將前兩欄分別視為絕對時間及記錄時間。所有時間值皆以微秒為單位；無法轉成數字的資料列會被略過。

例如第一列可使用「event_time(us), record_time(us)」作為欄位名稱，後續每列填入兩個以微秒為單位的時間值。

## 介面概覽

主畫面分為三區：

- **Waveform Area**：LFP、三軸訊號與共用時間軸。
- **Sync Area**：可切換「TTL」、「Video」、「Find Peak」、「LED Analysis」四個頁面。
- **Behavior Video**：影片畫面、時間／影格資訊、跳轉欄位及播放控制。

功能表包含：

- 「File > Open Project...」：開啟既有 .pigproj。
- 「File > Save Project...」：保存目前分析狀態。
- 「File > Import」：匯入影片、LFP、三軸及 TTL。
- 「File > Export」：匯出標記、檢查結果及圖表。
- 「Settings」：調整 LFP／三軸繪圖步距、電源雜訊頻率、LFP 峰值門檻，以及檢查 OpenCL GPU。

## 建議操作流程

### 1. 匯入影片

選擇「File > Import > Import Video (.mp4)」。

影片載入後可使用：

- 「Play」／「Stop」：播放、暫停或回到起點。
- 「Prev Frame」／「Next Frame」：逐格檢查。
- 「Go time」：輸入秒數、MM:SS 或 HH:MM:SS 後按 Enter。
- 「Go frame」：輸入影格編號後按 Enter。
- 「Rotate 180°」／「Rotate 90°」：調整影片方向。
- 下方 slider：快速移動至其他影格。

重新匯入影片會清除目前的同步、TTL、影片標記、LED ROI 與 LED 分析狀態，因此如需保留工作，請先保存專案。

### 2. 匯入訊號資料

依需求選擇：

- 「File > Import > Import LFP (.csv)」
- 「File > Import > Import 3-axis (.csv)」

大型 CSV 第一次匯入，或第一次切換到尚未讀取的 channel 時，程式需要先準備訊號資料，可能會等待較久並使用額外的本機磁碟空間。後續再次使用相同檔案與 channel 時通常會較快；處理期間請耐心等待，避免強制關閉程式。

匯入 LFP 後可選擇 channel 與訊號顯示模式。勾選「Bandpass」後設定 Low／High cutoff；勾選 notch filter 可去除「Settings > Set power noise frequency」設定的電源雜訊。完成設定後按「confirm」套用。

「Power spectrum」與「Spectrogram」會依目前所選 LFP channel、時間軸範圍及已套用的濾波設定產生分析結果。「Follow video playback」開啟時，完成同步後的波形視窗會跟隨影片播放位置。

### 3. 建立或匯入 TTL

可使用「File > Import > Import Time Marker (.csv)」匯入 TTL；匯入後 Sync Area 會切換至「TTL」頁面。

也可手動新增：

1. 在 TTL 輸入欄填入秒數或 HH:MM:SS.ffffff。
2. 按「Add TTL」或 Enter。
3. 選取表格中的資料列後按「Remove TTL」可刪除。

若輸入欄留白，程式會使用目前暫停中的影片時間新增 TTL；影片必須已載入且處於暫停狀態。

### 4. 建立影片事件標記

將 Sync Area 切換到「Video」，把影片停在目標影格，再按下事件按鈕：

- 「LED On」／「LED Off」
- 「Action Start」／「Action End」
- 「Seizure-like」

點選表格資料列可跳回該事件位置。使用「Edit Selected」編輯標記，或使用「Delete Selected」刪除標記。Action Start／End 及 LED On／Off 會依表格順序配成事件區間並顯示在訊號圖上。

### 5. LED 自動偵測

1. 將 Sync Area 切換到「LED Analysis」。
2. 視需要輸入 LED scan range。
3. 按「Select LED」，然後在影片畫面上拖曳框選 LED 區域。
4. 完成框選後，程式會自動在背景分析 ROI 的影格亮度變化。
5. 等待進度完成，確認分析圖、門檻及建立的 LED On／Off 標記。

**提醒：LED 偵測結果相當仰賴人工框選的精確度。請盡量貼合 LED 範圍，避免包含會移動、反光或明暗變化明顯的背景；框選過大或偏離 LED 都可能造成誤判或漏判。**

若勾選「Detect multiple LED events」，必須先匯入 TTL；程式會依 TTL 數量限制要尋找的事件數。可在「Settings > Check OpenCL GPU」確認 GPU 加速狀態，沒有可用裝置時會自動使用 CPU，處理時間可能較長。

變更 ROI、影片旋轉角度或掃描範圍後，應重新執行偵測。

圖表中的標記會以顏色區分：綠色代表 LED On 或 LED 區段，紅色代表 LED Off，橘色色塊代表 Action Start 至 Action End，紅色標線代表 Seizure-like 或目前影片位置，TTL 則以綠色標線顯示。

### 6. 時間同步

當資料中同時存在：

- 至少一個影片時間軸上的「LED On」；以及
- 至少一個記錄時間軸上的 TTL；

程式會以兩者各自最早的標記計算時間差，也就是「影片 LED On 時間減去 TTL 記錄時間」。

同步完成後，影片會跳至第一個 LED On，影片、TTL、LFP 與三軸圖會共用同步時間基準。點選 TTL、影片標記、峰值或波形位置也可互相跳轉。

同步後會以第一個 LED On 與第一個 TTL 所對應的時間點為 0 秒。畫面出現負數時間是正常現象，表示該影格或訊號發生在第一個同步點之前。

為避免錯誤對齊，請確認第一個 LED On 確實對應第一個 TTL。如果不是，請刪除多餘標記或調整標記內容。

### 7. 尋找 LFP 峰值

使用前必須：

1. 匯入影片及 LFP。
2. 完成影片與 TTL 同步。
3. 在「Find Peak」頁面選擇要分析的 LFP channel。
4. 到「Settings > Set LFP peak thresholds」設定高度、prominence 與最小間距門檻。
5. 切換至「Find Peak」，按「Find Peak」。

程式只在與影片時間重疊的訊號範圍尋找峰值，並以訊號基準線區分正向峰值與負向峰值。正向與負向峰值都會加入表格，note 中會標示 positive peak 或 negative peak。再次對同一個 channel 執行會取代該 channel 先前自動偵測出的 LFP peak；其他 channel 的峰值會保留。表格內可編輯 note、點選峰值跳轉影片，或刪除選定峰值。

完成峰值偵測後，可按「Analyze Peaks」查看所選 channel 每分鐘的 LFP peak 數量長條圖。圖表會合併統計正向與負向峰值，不會分開顯示。此功能必須先有完成同步的 LFP peak 才能使用。

## 匯出資料

### Export Markers...

可選擇 Sync Area 類型與輸出格式：

- 「TTL」：CSV 或 Excel。
- 「Video」：CSV 或 Excel，包含 event type、video time、frame index、note。
- 「Find Peak」：CSV 或 Excel。
- 「LED Analysis」：PNG 或 JPG 分析圖。

### Export Check Results

檢查已載入的 LFP 或三軸 CSV，並輸出 CSV check report。若兩者皆已載入，程式會先詢問要檢查哪一份資料。

### Export 3-axis Waveform Image

輸出完整三軸波形，支援 PNG、PDF 及 SVG。

### Export LFP Images...

可設定：

- channel 與輸出時間範圍；
- raw／filtered 訊號及 band-pass／notch 參數；
- waveform、power spectrum、spectrogram（可複選）；
- 圖片 DPI 與目的資料夾。

輸出檔名會包含來源檔名、channel、raw／processed 及圖表類型。

### Export Peak analyze Image

將 LFP peak 數量分析圖匯出為 PNG。使用前必須先完成同步與峰值偵測；匯出時可選擇要輸出的 LFP channel。

## 儲存與開啟專案

使用「File > Save Project...」將目前狀態儲存為 .pigproj。專案會保存匯入來源、目前影格、旋轉角度、圖表範圍、filter 設定、標記、LED ROI 與分析結果等資訊。

.pigproj **不會內嵌原始影片或 CSV**，只會記錄外部檔案路徑與檔案指紋。因此：

- 移動 .pigproj 時，請一併保留原始 MP4／CSV。
- 原始檔路徑失效時，開啟專案會要求重新指定檔案。
- 重新指定的檔案必須與原始來源的大小及抽樣雜湊一致；修改過的副本不會被接受。
- 關閉程式或開啟其他專案前，如有未保存變更，程式會要求確認。
