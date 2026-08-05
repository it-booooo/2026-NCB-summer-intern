# Pig Behavior Sync 使用者操作手冊

Pig Behavior Sync 是一套用於動物行為實驗的 Windows 桌面工具，可同時檢視行為影片、LFP 與三軸感測訊號，並透過影片中的 LED 事件及記錄端 TTL 時間標記對齊兩條時間軸。程式也提供事件標記、LFP 峰值偵測、LED 自動偵測、資料檢查、圖表匯出及分析專案保存功能。

## 主要功能

- 播放 MP4 行為影片，支援逐格移動、跳至指定時間／影格，以及 90°、180° 旋轉。
- 顯示 LFP 與三軸訊號，共用可拖曳的時間範圍。
- 選擇 LFP channel，套用 band-pass，以及 notch 或滑動視窗正弦波回歸電源雜訊移除。
- 顯示 LFP power spectrum 與 spectrogram。
- 匯入或手動新增 TTL 時間標記。
- 在影片上建立 LED On、LED Off、Action Start、Action End 與 Seizure-like 標記。
- 選取影片中的 LED ROI，自動分析亮度變化並建立 LED 事件。
- 可自動使用最早的 LED On 與 TTL，或手動指定同步事件，計算影片／記錄時間差。
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

### TTL Marker CSV

TTL CSV 建議包含：

- 一個名稱以「_time(us)」結尾的絕對時間欄位。
- 「record_time(us)」、「recording_time(us)」或「record time(us)」記錄時間欄位。

舊格式若無上述欄名，程式會嘗試將前兩欄分別視為絕對時間及記錄時間。所有時間值皆以微秒為單位；無法轉成數字的資料列會被略過。

例如第一列可使用「event_time(us), record_time(us)」作為欄位名稱，後續每列填入兩個以微秒為單位的時間值。

## 介面概覽

主畫面分為三區：

- **Waveform Area**：LFP、三軸訊號與共用時間軸。
- **Sync Area**：可切換「TTL」、「Video」、「LFP Peak」、「LED Analysis」四個頁面。
- **Behavior Video**：影片畫面、時間／影格資訊、跳轉欄位及播放控制。

功能表包含：

- 「File > Open Project...」：開啟既有 .pigproj。
- 「File > Save Project...」：保存目前分析狀態。
- 「File > Import」：匯入影片、LFP、三軸及 TTL。
- 「File > Export」：匯出標記、檢查結果及圖表。
- 「Settings」：調整 LFP／三軸繪圖步距、電源雜訊頻率、LFP 峰值門檻、檢查 OpenCL GPU，以及清除訊號暫存資料。

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

大型 CSV 第一次匯入時，程式需要先準備訊號資料，會顯示處理進度，並可能使用較多記憶體及額外的本機磁碟空間。後續再次使用相同檔案時通常會較快；如不想繼續，可按進度視窗中的「Cancel」，請避免直接強制關閉程式。

若要釋放訊號暫存所占用的磁碟與記憶體，可使用「Settings > Clear signal cache」。此操作不會刪除原始 CSV，但下次使用相關訊號時需要重新建立暫存，因此第一次顯示或分析可能較慢。

匯入 LFP 後可選擇 channel 與訊號顯示模式。勾選「Bandpass」後設定 Low／High cutoff；「Line noise」可選 None、Notch filter 或 Sinusoidal regression。Frequencies 可輸入一個或多個以逗號／空白分隔的頻率，例如 `60, 90`。Notch 使用同一個 Q 依序處理各頻率；正弦波回歸會在同一個 least-squares design matrix 中共同估計所有頻率。勾選「All harmonics」時，程式會自動加入每個輸入頻率的所有整數倍頻，僅處理嚴格低於目前 sample rate Nyquist frequency 的項目，重複的倍頻只估計一次；不會自動加入公因數。預設為 60 Hz、4 秒、50% overlap、只處理輸入頻率。完成設定後按「confirm」套用；波形、power spectrum、spectrogram 與 LFP 影像匯出會共用同一組已選處理設定。

大型正弦波回歸區段會自動使用 OpenCL GPU：設計矩陣的偽逆只在 CPU 建立並快取一次，大量視窗係數、Hann overlap-add 重建與相減則在 GPU 執行；少於 100,000 samples、GPU 不支援 double precision，或 OpenCL 不可用時會安全改用 NumPy。可用環境變數 `PIG_LFP_COMPUTE_BACKEND=cpu|opencl|auto` 強制選擇，並以 `PIG_LFP_OPENCL_MIN_SAMPLES` 調整自動啟用門檻。LFP 與 LED 共用 `PIG_OPENCL_DEVICE`／`PIG_OPENCL_VENDOR` 裝置選擇及 `.opencl_temp` cache。

「Power spectrum」與「Spectrogram」會依目前所選 LFP channel、時間軸範圍及已套用的濾波設定產生分析結果。建立 filtered overview、power spectrum 或 spectrogram 時會顯示進度，需要時可按「Cancel」中止。「Follow video playback」開啟時，完成同步後的波形視窗會跟隨影片播放位置。

使用 Notch filter 顯示或匯出 power spectrum 時，程式會在轉換為 dB 後，依 notch 中心頻率與 Q 推算的頻寬，使用兩側頻譜做僅供顯示的線性插值，並在圖名標示 `notch gaps display-interpolated`。此步驟不修改 Welch PSD、filtered LFP、波形、spectrogram 或資料匯出內容；Raw 與 Sinusoidal regression 的 power spectrum 也不會套用。

### 3. 建立或匯入 TTL

可使用「File > Import > Import TTL Markers (.csv)」匯入 TTL；匯入後 Sync Area 會切換至「TTL」頁面。

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

點選表格資料列可跳回該事件位置。使用「Edit Selected」可修改事件編號、類型、時間、影格與 note，或使用「Delete Selected」刪除標記。Action Start／End 及 LED On／Off 會依表格順序配成事件區間並顯示在訊號圖上。

若 Action End 或 LED Off 前方沒有相對應的 Start／On，或 End／Off 時間沒有晚於 Start／On，Video 頁面會顯示橘色提示。請調整事件順序或時間，否則該組事件不會形成有效區間。

### 5. LED 自動偵測

使用前必須先新增或匯入至少一個 TTL。新版不再區分單一或多事件模式；程式會自動以 TTL 數量作為上限，尋找相同數量以內的 LED On／Off 區間。

1. 將 Sync Area 切換到「LED Analysis」。
2. 視需要輸入 LED scan range。
3. 按「Select LED ROI」，然後在影片畫面上拖曳框選 LED 區域。
4. 完成框選後，程式會自動在背景分析 ROI 的影格亮度變化。
5. 等待進度完成，確認分析圖、門檻及建立的 LED On／Off 標記。

**提醒：LED 偵測結果相當仰賴人工框選的精確度。請盡量貼合 LED 範圍，避免包含會移動、反光或明暗變化明顯的背景；框選過大或偏離 LED 都可能造成誤判或漏判。**

目前偵測會配對 LED On 與 LED Off，尋找亮起時間約為 0.6 至 1.5 秒的區間。若掃描完成後沒有找到事件，請重新精確框選 ROI、調整掃描範圍，或改用 Video 頁面手動新增 LED 標記。

可在「Settings > Check OpenCL GPU」確認 GPU 加速狀態；沒有可用裝置時會自動使用 CPU，處理時間可能較長。

變更 ROI、影片旋轉角度或掃描範圍後，應重新執行偵測。

圖表中的標記會以顏色區分：綠色代表 LED On 或 LED 區段，紅色代表 LED Off，橘色色塊代表 Action Start 至 Action End，紅色標線代表 Seizure-like 或目前影片位置，TTL 則以綠色標線顯示；目前採用的影片同步事件也會在表格中以淡綠色標示。

### 6. 時間同步

預設使用自動同步。當資料中至少有一個影片端 LED On 與一個記錄端 TTL 時，程式會採用最早的 LED On 與最早的 TTL，並以「影片事件時間減去 TTL 記錄時間」計算時間差。

若最早的兩個事件並非同一次同步訊號，不需要刪除其他標記。請到「Video」頁面按「Select Sync Events...」，將 Mode 改為「Manual selection」，分別選擇「TTL event」及「Video event」，再按「Apply」。影片端可選擇 LED On 或 Action Start；若要恢復自動選擇，將 Mode 改回「Automatic: earliest TTL + earliest LED On」。

同步完成後，影片會跳至所選的影片端同步事件，影片、TTL、LFP 與三軸圖會共用同步時間基準。點選 TTL、影片標記、峰值或波形位置也可互相跳轉。

同步後會以所選影片事件與 TTL 對應的同步點為 0 秒。畫面出現負數時間是正常現象，表示該影格或訊號發生在同步點之前。

若刪除目前手動指定的同步事件，Video 頁面會提示原選擇已無法使用；請重新按「Select Sync Events...」選擇事件，或切回自動模式。

### 7. 尋找 LFP 峰值

使用前必須：

1. 匯入影片及 LFP。
2. 完成影片與 TTL 同步。
3. 在「LFP Peak」頁面選擇要分析的 LFP channel。
4. 到「Settings > Set LFP peak thresholds」設定高度、prominence 與最小間距門檻。
5. 切換至「LFP Peak」，按「Detect LFP Peaks」。

程式只在與影片時間重疊的訊號範圍尋找峰值，並以訊號基準線區分正向峰值與負向峰值。正向與負向峰值都會加入表格，note 中會標示 positive peak 或 negative peak。偵測期間會顯示進度，需要時可按「Cancel」中止。再次對同一個 channel 執行會取代該 channel 先前自動偵測出的 LFP peak；其他 channel 的峰值會保留。表格內可編輯 note、點選峰值跳轉影片，或刪除選定峰值。

完成峰值偵測後，可按「Analyze Peaks」查看所選 channel 每分鐘的 LFP peak 數量長條圖。圖表會合併統計正向與負向峰值，不會分開顯示。此功能必須先有完成同步的 LFP peak 才能使用。

## 匯出資料

### Export Markers...

可選擇 Sync Area 類型與輸出格式：

- 「TTL」：CSV 或 Excel。
- 「Video」：CSV 或 Excel，包含 event type、video time、frame index、note。
- 「LFP Peak」：CSV 或 Excel。
- 「LED Analysis」：PNG 或 JPG 分析圖。

### Export Check Results

檢查已載入的 LFP 或三軸 CSV，並輸出 CSV check report。若兩者皆已載入，程式會先詢問要檢查哪一份資料；檢查期間會顯示進度，需要時可按「Cancel」中止。

### Export 3-axis Waveform Image

輸出完整三軸波形，支援 PNG、PDF 及 SVG。

### Export LFP Images...

可設定：

- channel 與輸出時間範圍；
- raw／filtered 訊號及 band-pass／notch 參數；
- waveform、power spectrum、spectrogram（可複選）；
- 圖片 DPI 與目的資料夾。

輸出檔名會包含來源檔名、channel、raw／processed 及圖表類型。準備大量資料或多張圖片時會顯示進度，需要時可按「Cancel」中止。

### Export Peak analyze Image

將 LFP peak 數量分析圖匯出為 PNG。使用前必須先完成同步與峰值偵測；匯出時可選擇要輸出的 LFP channel。

## 儲存與開啟專案

使用「File > Save Project...」將目前狀態儲存為 .pigproj。專案會保存匯入來源、目前影格、旋轉角度、圖表範圍、filter 設定、標記、同步事件選擇、LED ROI 與分析結果等資訊。

.pigproj **不會內嵌原始影片或 CSV**，只會記錄外部檔案路徑與檔案指紋。因此：

- 移動 .pigproj 時，請一併保留原始 MP4／CSV。
- 原始檔路徑失效時，開啟專案會要求重新指定檔案。
- 重新指定的檔案必須與原始來源的大小及抽樣雜湊一致；修改過的副本不會被接受。
- 開啟含大型訊號資料的專案時會顯示準備進度，需要時可按「Cancel」中止開啟。
- 關閉程式或開啟其他專案前，如有未保存變更，程式會要求確認。
