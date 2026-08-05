# Pig Behavior Sync 使用者操作手冊

Pig Behavior Sync 是一套 Windows 桌面程式，主要用途是把動物行為影片和實驗訊號對到同一條時間線。同步完成後，播放影片時可以同時查看相同時間點的 LFP、三軸訊號、TTL 與行為標記，也能進行 LED 偵測、LFP 峰值偵測、圖表匯出和專案保存。

## 壹、主要功能

- 播放 MP4 行為影片，支援逐格移動、跳至指定時間／影格，以及 90°、180° 旋轉。
- 顯示 LFP 與三軸訊號，共用可拖曳的時間範圍。
- 選擇要查看的 LFP channel，並使用 Bandpass 或 Notch 減少不需要的頻率與電源雜訊。
- 顯示 LFP 的頻率分布圖（Power spectrum）與時間－頻率圖（Spectrogram）。
- 匯入或手動新增 TTL 時間標記。
- 在影片上建立 LED On、LED Off、Action Start、Action End 與 Seizure-like 標記。
- 選取影片中的 LED ROI，自動分析亮度變化並建立 LED 事件。
- 可自動使用最早的 LED On 與 TTL，或手動指定同步事件，計算影片／記錄時間差。
- 在同步後的 LFP 訊號中尋找正向與負向峰值。
- 將標記、檢查結果與各類分析圖匯出成 CSV、Excel 或圖片。
- 將工作狀態儲存為 .pigproj，稍後繼續分析。

## 貳、系統需求

- Windows 10／11
- 可讀取的 MP4、LFP／三軸 CSV 或 TTL CSV 實驗資料
- OpenCL 相容 GPU 與驅動程式為選用項目；沒有可用 GPU 時，LED 偵測會自動改用 CPU，只是處理時間可能較長

本程式不需要安裝 Python 或其他套件。

## 參、取得與啟動程式

正式交付版本為 PigBehaviorSync.exe。

使用方式：

1. 將 PigBehaviorSync.exe 複製到本機資料夾。
2. 雙擊執行程式。
3. 從「File > Import」選擇自己的影片及 CSV 資料。

程式是單一執行檔，不需執行安裝程序，也不需要下載額外的 Python 套件。第一次啟動或第一次分析大型影片時，Windows 防毒軟體可能需要較長時間檢查檔案。

> **GPU 加速說明：** 電腦若有相容的 GPU 與 OpenCL 驅動，程式會用它加速 LED 偵測；沒有可用 GPU 時會自動改用 CPU，不影響其他功能。

## 肆、輸入資料格式

### 行為影片

- 格式：.mp4
- 程式會讀取影片的 FPS（每秒影格數）、總影格數、畫面尺寸及播放時間。
- 若影片內記錄的 FPS 不正確，顯示時間和同步結果也可能不準確。

### LFP 與三軸 CSV

訊號 CSV 需包含資料說明列及「Time[us]」表頭。程式會辨識：

- 「Channels」：各資料欄對應的 channel 編號。
- 「Sample Rate...」：每秒記錄多少筆資料。
- 「Unit」或「Units」：訊號單位（選填）。
- 「Time[us]」：訊號資料的開始位置；其後每列第一欄為時間，其餘欄位為各 channel 數值。us 代表微秒，1 秒等於 1,000,000 微秒。

Time[us] 必須填寫數字，而且每一列時間不能比上一列更早。資料區至少需要兩筆訊號資料，否則程式可能無法顯示波形或進行分析。

概念範例：前三列依序填寫 Channels、Sample Rate[Hz] 與 Unit；接著以 Time[us] 作為資料表頭，後續每列填寫時間與各 channel 數值。

目前三軸顯示流程會使用 channel 260，因此三軸資料應包含該 channel。

### TTL Marker CSV

TTL CSV 建議包含：

- 一個名稱以「_time(us)」結尾的絕對時間欄位。
- 「record_time(us)」、「recording_time(us)」或「record time(us)」記錄時間欄位。

舊格式若無上述欄名，程式會嘗試將前兩欄分別視為絕對時間及記錄時間。所有時間值皆以微秒為單位；無法轉成數字的資料列會被略過。

例如第一列可使用「event_time(us), record_time(us)」作為欄位名稱，後續每列填入兩個以微秒為單位的時間值。

## 伍、介面概覽

主畫面分為三區：

- **Waveform Area**：上方的訊號區，用來查看 LFP、三軸訊號與時間位置。
- **Sync Area**：左下方的操作區，可切換「TTL」、「Video」、「LFP Peak」、「LED Analysis」四個頁面。
- **Behavior Video**：右下方的影片區，可播放影片、逐格移動或跳到指定時間。

功能表包含：

- 「File > Open Project...」：開啟既有 .pigproj。
- 「File > Save Project...」：保存目前分析狀態。
- 「File > Import」：匯入影片、LFP、三軸及 TTL。
- 「File > Export」：匯出標記、檢查結果及圖表。
- 「Settings」：調整波形在畫面上的顯示密度、電源雜訊頻率、LFP 峰值偵測條件、檢查 GPU，以及清除訊號暫存資料。

## 陸、第一次使用：請照順序操作

最基本的同步流程是：匯入影片與訊號、建立 TTL、找出影片中的 LED On，最後確認同步結果。若只想查看影片或波形，可只匯入需要的檔案，不必完成全部步驟。

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

大型 CSV 第一次匯入時，程式需要先整理資料，因此可能等待較久、使用較多記憶體及額外的磁碟空間。畫面會顯示處理進度；如不想繼續，可按「Cancel」，請不要直接強制關閉程式。相同檔案之後通常會載入得比較快。

若要釋放訊號暫存所占用的磁碟與記憶體，可使用「Settings > Clear signal cache」。此操作不會刪除原始 CSV，但下次使用相關訊號時需要重新建立暫存，因此第一次顯示或分析可能較慢。

匯入 LFP 後，先選擇要查看的 channel，再選擇 Raw（原始訊號）或 Filtered（濾波後訊號）。使用「Bandpass」時，Low 和 High 代表要保留的最低與最高頻率；勾選 Notch 可減少 50 Hz 或 60 Hz 電源造成的雜訊。完成後按「confirm」套用設定。

「Power spectrum」與「Spectrogram」會分析目前選擇的 channel 和畫面時間範圍。分析時會使用原始 CSV 在這段時間內的所有取樣點，不會因為畫面波形顯示得比較稀疏而漏掉資料；選擇的時間越長，等待時間通常也越久。

使用 Filtered 並啟用 Bandpass 時，Spectrogram 只會顯示 Low 到 High 之間的頻率；使用 Raw 時則顯示完整頻率範圍。如果圖表很寬，可拖曳視窗下方的水平捲軸查看。處理期間會顯示進度，需要時可按「Cancel」中止。

「Follow video playback」開啟時，完成同步後的波形視窗會跟隨影片播放位置。

### 3. 建立或匯入 TTL

可使用「File > Import > Import TTL Markers (.csv)」匯入 TTL；匯入後 Sync Area 會切換至「TTL」頁面。

也可手動新增：

1. 在 TTL 輸入欄填入秒數或 HH:MM:SS.ffffff。
2. 按「Add TTL」或 Enter。
3. 選取表格中的資料列後按「Remove TTL」可刪除。

若輸入欄留白，程式會把影片目前暫停的位置當成 TTL 時間。這種方式必須先載入影片並暫停播放。

### 4. 建立影片事件標記

將 Sync Area 切換到「Video」，把影片停在目標影格，再按下事件按鈕：

- 「LED On」／「LED Off」
- 「Action Start」／「Action End」
- 「Seizure-like」

點選表格中的標記，影片就會跳到該位置。「Edit Selected」可修改標記順序、類型、時間、影格與備註；「Delete Selected」可刪除標記。Action Start／End 及 LED On／Off 會按照表格順序兩兩配對，並在訊號圖上顯示成一段有顏色的區間。

若 Action End 或 LED Off 前方沒有相對應的 Start／On，或 End／Off 時間沒有晚於 Start／On，Video 頁面會顯示橘色提示。請調整事件順序或時間，否則該組事件不會形成有效區間。

### 5. LED 自動偵測

使用前必須先新增或匯入至少一個 TTL。程式最多會尋找和 TTL 數量相同的 LED 亮滅區間；例如有 3 個 TTL，最多會建立 3 組 LED On／Off。若影片中符合條件的事件較少，實際找到的數量也會較少。

1. 將 Sync Area 切換到「LED Analysis」。
2. 視需要輸入 LED scan range，指定要檢查的影片時間；留白代表從頭到尾檢查。
3. 按「Select LED ROI」，然後在影片畫面上拖曳，框住 LED。
4. 放開滑鼠後，程式會自動分析框選範圍內的亮度變化。
5. 等待進度完成，再確認亮度變化圖和建立的 LED On／Off 標記。

**提醒：LED 偵測結果相當仰賴人工框選的精確度。請盡量貼合 LED 範圍，避免包含會移動、反光或明暗變化明顯的背景；框選過大或偏離 LED 都可能造成誤判或漏判。**

目前偵測會配對 LED On 與 LED Off，尋找亮起時間約為 0.6 至 1.5 秒的區間。若掃描完成後沒有找到事件，請重新精確框選 ROI、調整掃描範圍，或改用 Video 頁面手動新增 LED 標記。

可在「Settings > Check OpenCL GPU」確認 GPU 加速狀態；沒有可用裝置時會自動使用 CPU，處理時間可能較長。

變更 ROI、影片旋轉角度或掃描範圍後，應重新執行偵測。再次執行會以新結果取代先前由 LED 自動偵測建立的標記；使用者手動新增的標記不會被刪除。

圖表中的標記會以顏色區分：綠色代表 LED On 或 LED 區段，紅色代表 LED Off，橘色色塊代表 Action Start 至 Action End，紅色標線代表 Seizure-like 或目前影片位置，TTL 則以綠色標線顯示；目前採用的影片同步事件也會在表格中以淡綠色標示。

### 6. 時間同步

預設使用自動同步。只要影片標記中至少有一個 LED On，而且記錄資料中至少有一個 TTL，程式就會把最早的 LED On 和最早的 TTL 視為同一個事件，並用這一組事件對齊影片與訊號。

若最早的兩個事件並非同一次同步訊號，不需要刪除其他標記。請到「Video」頁面按「Select Sync Events...」，將 Mode 改為「Manual selection」，分別選擇「TTL event」及「Video event」，再按「Apply」。影片端可選擇 LED On 或 Action Start；若要恢復自動選擇，將 Mode 改回「Automatic: earliest TTL + earliest LED On」。

同步完成後，影片會跳到所選的同步事件。影片、TTL、LFP 與三軸圖會開始使用相同的時間；之後點選 TTL、影片標記、LFP 峰值或波形位置，都可以跳到相對應的影片位置。

同步後，所選的同步事件會顯示為 0 秒。畫面出現負數時間是正常現象，例如 -2 秒表示該影格或訊號發生在同步點前 2 秒。

若刪除目前手動指定的同步事件，Video 頁面會提示原選擇已無法使用；請重新按「Select Sync Events...」選擇事件，或切回自動模式。

### 7. 尋找 LFP 峰值

使用前必須：

1. 匯入影片及 LFP。
2. 完成影片與 TTL 同步。
3. 在「LFP Peak」頁面選擇要分析的 LFP channel。
4. 到「Settings > Set LFP peak thresholds」設定峰值高度、明顯程度（prominence）及兩個峰值之間的最短時間。
5. 切換至「LFP Peak」，按「Detect LFP Peaks」。

程式會使用原始 CSV 中的所有 LFP 取樣點，在影片和訊號都有資料的時間範圍內尋找峰值。高於訊號基準線的是正向峰值，低於基準線的是負向峰值，表格的 note 會分別顯示 positive peak 或 negative peak。偵測期間會顯示進度，需要時可按「Cancel」中止。

同一個 channel 再次偵測時，會取代該 channel 上一次自動找到的峰值；其他 channel 的結果不會被刪除。表格內可修改 note、點選峰值跳到影片位置，或刪除選定峰值。

完成峰值偵測後，可按「Analyze Peaks」查看所選 channel 每分鐘的 LFP peak 數量長條圖。圖表會合併統計正向與負向峰值，不會分開顯示。此功能必須先有完成同步的 LFP peak 才能使用。

## 柒、匯出資料

### Export Markers...

用來匯出左下方 Sync Area 中的表格或 LED 分析圖。可選擇：

- 「TTL」：CSV 或 Excel。
- 「Video」：CSV 或 Excel，包含標記類型、影片時間、影格編號與備註。
- 「LFP Peak」：CSV 或 Excel。
- 「LED Analysis」：PNG 或 JPG 分析圖。

### Export Check Results

檢查已載入的 LFP 或三軸 CSV 是否有時間不連續、空值或其他資料問題，並輸出一份 CSV 檢查報告。若 LFP 和三軸資料都已載入，程式會先詢問要檢查哪一份；檢查期間可按「Cancel」中止。

### Export 3-axis Waveform Image

輸出完整三軸波形，支援 PNG、PDF 及 SVG。

### Export LFP Images...

可選擇：

- 要輸出的 channel 和時間範圍；
- Raw 原始訊號或 Filtered 濾波後訊號，以及 Bandpass／Notch 設定；
- 波形圖、Power spectrum、Spectrogram，可同時選擇多種；
- 目的資料夾。

圖片固定以 300 DPI 輸出。檔名會自動包含原始檔名、channel、Raw／Filtered 及圖表類型。準備大量資料或多張圖片時會顯示進度，需要時可按「Cancel」中止。使用 Filtered＋Bandpass 匯出 Spectrogram 時，圖表只會顯示設定的頻率範圍。

### Export Peak analyze Image

將 LFP peak 數量分析圖匯出為 PNG。使用前必須先完成同步與峰值偵測；匯出時可選擇要輸出的 LFP channel。

## 捌、儲存與開啟專案

使用「File > Save Project...」可把目前工作保存成 .pigproj，包括已匯入哪些檔案、目前影格、影片旋轉角度、圖表範圍、濾波設定、標記、同步選擇、LED 框選範圍與分析結果。

.pigproj **不會把原始影片或 CSV 包進專案檔**，只會記住檔案位置，並記錄用來確認檔案沒有被換掉的內容特徵。因此：

- 移動 .pigproj 時，請一併保留原始 MP4／CSV。
- 原始檔路徑失效時，開啟專案會要求重新指定檔案。
- 重新指定時必須選擇原本的檔案；內容修改過的副本可能不會被接受。
- 開啟含大型訊號資料的專案時會顯示準備進度，需要時可按「Cancel」中止開啟。
- 關閉程式或開啟其他專案前，如有未保存變更，程式會要求確認。
