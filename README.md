# Pig Behavior Sync 使用者操作手冊

Pig Behavior Sync 是一套 Windows 桌面程式，主要用途是把動物行為影片和實驗訊號對到同一條時間線。同步完成後，播放影片時可以同時查看相同時間點的 LFP、三軸訊號、TTL 與行為標記，也能進行 LED 偵測、LFP 峰值偵測、圖表匯出和專案保存。

## 壹、主要功能

- 播放 MP4 行為影片，支援逐格移動、跳至指定時間／影格，以及 90°、180° 旋轉。
- 顯示 LFP 與三軸訊號，共用可拖曳的時間範圍。
- 選擇 LFP channel，使用 Bandpass、Notch filter 或 Sinusoidal regression 處理訊號。
- 顯示 LFP 的 Power spectrum 與 Spectrogram。
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
- OpenCL 相容 GPU 與驅動程式為選用項目；可加速 LED 偵測及部分大型 LFP 處理，沒有可用 GPU 時會自動改用 CPU，只是處理時間可能較長
- 本程式不需要安裝 Python 或其他套件。

## 參、取得與啟動程式

正式交付版本為 PigBehaviorSync.exe。使用方式：

1. 將 PigBehaviorSync.exe 複製到本機資料夾。
2. 雙擊執行程式。
3. 從「File > Import」選擇自己的影片及 CSV 資料。

程式是單一執行檔，不需執行安裝程序，也不需要下載額外的 Python 套件。第一次啟動或第一次分析大型影片時，Windows 防毒軟體可能需要較長時間檢查檔案。

> **GPU 加速說明：** 電腦若有相容的 GPU 與 OpenCL 驅動，程式會用它加速 LED 偵測及部分大型 LFP 處理；沒有可用 GPU 時會自動改用 CPU，不影響分析功能與結果，但處理時間可能較長。

## 肆、輸入資料格式

### 一、行為影片

- 格式：.mp4
- 程式會讀取影片的 FPS（每秒影格數）、總影格數、畫面尺寸及播放時間。
- 若影片內記錄的 FPS 不正確，顯示時間和同步結果也可能不準確。

### 二、LFP 與三軸 CSV

訊號 CSV 需包含資料說明列及「Time[us]」表頭。程式會辨識：

- 「Channels」：各資料欄對應的 channel 編號。
- 「Sample Rate...」：每秒記錄多少筆資料。
- 「Unit」或「Units」：訊號單位（選填）。
- 「Time[us]」：訊號資料的開始位置；其後每列第一欄為時間，其餘欄位為各 channel 數值。us 代表微秒，1 秒等於 1,000,000 微秒。

Time[us] 必須填寫數字，而且每一列時間不能比上一列更早。資料區至少需要兩筆訊號資料，否則程式可能無法顯示波形或進行分析。

概念範例：前三列依序填寫 Channels、Sample Rate[Hz] 與 Unit；接著以 Time[us] 作為資料表頭，後續每列填寫時間與各 channel 數值。

目前三軸顯示流程會使用 channel 260，因此三軸資料應包含該 channel。

### 三、TTL Marker CSV

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

### 一、匯入影片

選擇「File > Import > Import Video (.mp4)」。

影片載入後可使用：

- 「Play」／「Stop」：播放、暫停或回到起點。
- 「Prev Frame」／「Next Frame」：逐格檢查。
- 「Go time」：輸入秒數、MM:SS 或 HH:MM:SS 後按 Enter。
- 「Go frame」：輸入影格編號後按 Enter。
- 「Rotate 180°」／「Rotate 90°」：調整影片方向。
- 下方 slider：快速移動至其他影格。

重新匯入影片會清除目前的同步、TTL、影片標記、LED ROI 與 LED 分析狀態，因此如需保留工作，請先保存專案。

### 二、匯入訊號資料

依需求選擇：

- 「File > Import > Import LFP (.csv)」
- 「File > Import > Import 3-axis (.csv)」

大型 CSV 第一次匯入時，程式需要先整理資料，因此可能等待較久、使用較多記憶體及額外的磁碟空間。畫面會顯示處理進度；如不想繼續，可按「Cancel」，請不要直接強制關閉程式。相同檔案之後通常會載入得比較快。

若要釋放訊號暫存所占用的磁碟與記憶體，可使用「Settings > Clear signal cache」。此操作不會刪除原始 CSV，但下次使用相關訊號時需要重新建立暫存，因此第一次顯示或分析可能較慢。

匯入 LFP 後，先選擇 channel，再選擇 Raw（原始訊號）或 Filtered（濾波後訊號）。勾選「Bandpass」後可設定 Low／High；「Line noise」可選 None、Notch filter 或 Sinusoidal regression。Frequencies 可輸入一個或多個以逗號或空白分隔的頻率，例如 60, 90。使用 Notch filter 時可設定 Q；使用 Sinusoidal regression 時可設定 Window、Overlap，並可勾選「All harmonics」自動處理倍頻。完成後按「confirm」套用；波形、Power spectrum、Spectrogram 與 LFP 圖片匯出會使用同一組設定。

第一次切換到 Filtered 或變更濾波設定時，程式會分段準備波形。時間範圍列上方的紅色表示尚未完成，綠色表示已完成；波形會隨處理進度逐步更新。大型資料可能需要較長時間，程式會依電腦環境自動使用 GPU 或 CPU。

套用 Filtered 後，程式會在背景依序準備所有 LFP channel。畫面會顯示已完成的 channel 數量；尚未完成的 channel 名稱後方會出現「...」。切換到尚未完成的 channel 時，可能會暫時顯示 Raw，待處理完成後再自動換成 Filtered，並不代表濾波設定失效。

若 Sinusoidal regression 無法使用 GPU，程式會顯示警告。此時仍可使用 CPU 處理，但大型資料可能需要很長時間；可考慮改用 Notch filter，或取消「All harmonics」以縮短等待時間。

「Power spectrum」與「Spectrogram」會分析目前選擇的 channel 和畫面時間範圍。分析時會使用原始 CSV 在這段時間內的所有取樣點，不會因為畫面波形顯示得比較稀疏而漏掉資料；選擇的時間越長，等待時間通常也越久。

使用 Filtered 並啟用 Bandpass 時，Spectrogram 只會顯示 Low 到 High 之間的頻率；使用 Raw 時則顯示完整頻率範圍。如果圖表很寬，可拖曳視窗下方的水平捲軸查看。處理期間會顯示進度，需要時可按「Cancel」中止。

Spectrogram 視窗中的「PSD color scale」預設使用 Auto，會依目前可見頻率範圍自動調整顏色。若要固定不同圖表的顏色範圍，可取消 Auto，輸入 Min／Max（dB）後按「Apply」重新繪製；Min 必須小於 Max。

「Follow video playback」開啟時，完成同步後的波形視窗會跟隨影片播放位置。

使用 Notch filter 顯示或匯出 Power spectrum 時，圖中的 notch 頻率缺口會以鄰近頻譜補齊顯示，並在圖名標示「notch gaps display-interpolated」。這只影響 Power spectrum 的顯示方式，不會改變 Filtered 波形或 Spectrogram。

### 三、建立或匯入 TTL

可使用「File > Import > Import TTL Markers (.csv)」匯入 TTL；匯入後 Sync Area 會切換至「TTL」頁面。

也可手動新增：

1. 在 TTL 輸入欄填入秒數或 HH:MM:SS.ffffff。
2. 按「Add TTL」或 Enter。
3. 選取表格中的資料列後按「Remove TTL」可刪除。

若輸入欄留白，程式會把影片目前暫停的位置當成 TTL 時間。這種方式必須先載入影片並暫停播放。

### 四、建立影片事件標記

將 Sync Area 切換到「Video」，把影片停在目標影格，再按下事件按鈕：

- 「LED On」／「LED Off」
- 「Action Start」／「Action End」
- 「Seizure-like」

點選表格中的標記，影片就會跳到該位置。「Edit Selected」可修改標記順序、類型、時間、影格與備註；「Delete Selected」可刪除標記。Action Start／End 及 LED On／Off 會按照表格順序兩兩配對，並在訊號圖上顯示成一段有顏色的區間。

若 Action End 或 LED Off 前方沒有相對應的 Start／On，或 End／Off 時間沒有晚於 Start／On，Video 頁面會顯示橘色提示。請調整事件順序或時間，否則該組事件不會形成有效區間。

### 五、LED 自動偵測

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

### 六、時間同步

預設使用自動同步。只要影片標記中至少有一個 LED On，而且記錄資料中至少有一個 TTL，程式就會把最早的 LED On 和最早的 TTL 視為同一個事件，並用這一組事件對齊影片與訊號。

若最早的兩個事件並非同一次同步訊號，不需要刪除其他標記。請到「Video」頁面按「Select Sync Events...」，將 Mode 改為「Manual selection」，分別選擇「TTL event」及「Video event」，再按「Apply」。影片端可選擇 LED On 或 Action Start；若要恢復自動選擇，將 Mode 改回「Automatic: earliest TTL + earliest LED On」。

同步完成後，影片會跳到所選的同步事件。影片、TTL、LFP 與三軸圖會開始使用相同的時間；之後點選 TTL、影片標記、LFP 峰值或波形位置，都可以跳到相對應的影片位置。

同步後，所選的同步事件會顯示為 0 秒。畫面出現負數時間是正常現象，例如 -2 秒表示該影格或訊號發生在同步點前 2 秒。

若刪除目前手動指定的同步事件，Video 頁面會提示原選擇已無法使用；請重新按「Select Sync Events...」選擇事件，或切回自動模式。

### 七、尋找 LFP 峰值

使用前必須：

1. 匯入影片及 LFP。
2. 完成影片與 TTL 同步。
3. 在「LFP Peak」頁面選擇要分析的 LFP channel。
4. 到「Settings > Set LFP peak thresholds」設定峰值高度、明顯程度（prominence）及兩個峰值之間的最短時間。
5. 切換至「LFP Peak」，按「Detect LFP Peaks」。

程式會使用原始 CSV 中的所有 LFP 取樣點，在影片和訊號都有資料的時間範圍內尋找峰值。高於訊號基準線的是正向峰值，低於基準線的是負向峰值，表格的 note 會分別顯示 positive peak 或 negative peak。偵測期間會顯示進度，需要時可按「Cancel」中止。

同一個 channel 再次偵測時，會取代該 channel 上一次自動找到的峰值；其他 channel 的結果不會被刪除。表格會顯示 Peak Type、Video Time／Sync Time、Peak Value 與 Note；其中 Note 可以修改，也可點選峰值跳到影片位置，或刪除選定峰值。

「Peak Type」可選擇顯示全部、正向或負向峰值；「Sort By」可依 Time 或 Peak Value 排序；「Order」可選擇 Ascending 或 Descending。這些設定只會改變表格的顯示方式，不會重新執行峰值偵測，也不會改變「Analyze Peaks」的統計結果。

偵測完成後，上方 LFP 波形會補充顯示峰值附近的波形細節；切換 channel 或 Raw／Filtered 時會自動更新。大型資料會依電腦環境自動使用 GPU 或 CPU，沒有可用 GPU 時不影響偵測結果，只是處理時間可能較長。

完成峰值偵測後，可按「Analyze Peaks」查看所選 channel 每分鐘的 LFP peak 數量長條圖。圖表會合併統計正向與負向峰值，不會分開顯示。此功能必須先有完成同步的 LFP peak 才能使用。

## 柒、LFP Filter 詳細操作

### 一、調整顯示範圍

LFP 與三軸波形共用下方的時間範圍列，調整其中一個圖的範圍時，其他訊號圖也會同步更新：

- 拖曳藍色範圍左右兩端的白色圓點，可縮小或放大目前顯示的時間範圍。
- 拖曳藍色範圍中央，可保持範圍寬度並前後移動。
- 在波形上向上滾動滑鼠滾輪可放大，向下滾動可縮小；按住滑鼠左鍵拖曳可左右移動。
- 在波形上雙擊滑鼠左鍵，可恢復顯示完整時間範圍。

「Power spectrum」與「Spectrogram」會分析目前選取的 channel 及時間範圍，因此可先用時間範圍列縮小到想查看的區段，再開始分析。

### 二、Filter 參數

選擇 Filtered 後，可依資料狀況設定下列項目。修改參數後必須按「confirm」才會套用。

- Raw／Filtered：Raw 顯示原始訊號；Filtered 顯示套用目前濾波設定後的訊號。
- Bandpass：只保留 Low 與 High 之間的頻率。Low 用來排除較慢的漂移，High 用來排除較快的高頻雜訊。Low 必須小於 High，High 必須低於取樣率的一半。
- Line noise：None 不移除固定頻率雜訊；Notch filter 直接抑制指定頻率附近的窄頻雜訊；Sinusoidal regression 會在每個時間窗估計週期性雜訊後扣除。
- Frequencies：輸入要處理的頻率，單位為 Hz；多個頻率可用逗號或空白分隔，例如 60, 120。每個頻率都必須低於取樣率的一半。
- Q：只在 Notch filter 使用。數值越大，抑制範圍越窄；數值越小，影響的頻率範圍越寬。
- Window：只在 Sinusoidal regression 使用，代表每次估計雜訊的時間窗長度，單位為秒。較短的時間窗較能跟隨快速變化，較長的時間窗較適合穩定的週期性雜訊。
- Overlap：只在 Sinusoidal regression 使用，代表相鄰時間窗的重疊比例。比例較高時銜接通常較平順，但處理時間也可能增加。
- All harmonics：只在 Sinusoidal regression 使用。勾選後，會從輸入頻率開始，自動處理所有低於取樣率一半的整數倍頻。

第一次切換到 Filtered 或套用新設定時，時間範圍列上方會顯示處理狀態：紅色表示尚未完成，綠色表示已完成。處理期間波形會逐步更新。

程式會在背景準備所有 channel，並顯示目前已完成的數量。尚未準備完成的 channel 會以「...」標示；切換至該 channel 時可能先顯示 Raw，完成後會自動換成 Filtered。

### 三、Step 與峰值顯示

「Settings > Set LFP step」只控制上方 LFP 波形的顯示密度，不會修改原始 CSV，也不會改變濾波或峰值偵測結果。

- -1 auto：由程式依資料量自動選擇顯示間隔，通常最適合一般操作。
- 0 all：顯示每一個取樣點，細節最多，但大型資料可能明顯變慢並使用更多記憶體。
- 正整數 N：每 N 個取樣點顯示一點；數字越大，波形越簡略，但顯示速度通常越快。

完成「Detect LFP Peaks」後，程式會把偵測到的峰值及每個峰值前後約 1 秒的波形細節補到上方 LFP 波形中；其他沒有峰值的區域仍依 Step 設定簡略顯示。峰值偵測本身會使用完整訊號資料，不受 Step 影響。切換 channel 或 Raw／Filtered 時，峰值附近的細節會依目前選擇重新載入；若峰值很多，程式會控制顯示資料量，以避免畫面操作過慢。

## 捌、匯出資料

### 一、Export Markers...

用來匯出左下方 Sync Area 中的表格或 LED 分析圖。可選擇：

- 「TTL」：CSV 或 Excel。
- 「Video」：CSV 或 Excel，包含標記類型、影片時間、影格編號與備註。
- 「LFP Peak」：CSV 或 Excel。
- 「LED Analysis」：PNG 或 JPG 分析圖。

### 二、Export Check Results

檢查已載入的 LFP 或三軸 CSV 是否有時間不連續、空值或其他資料問題，並輸出一份 CSV 檢查報告。若 LFP 和三軸資料都已載入，程式會先詢問要檢查哪一份；檢查期間可按「Cancel」中止。

### 三、Export 3-axis Waveform Image

輸出完整三軸波形，支援 PNG、PDF 及 SVG。

### 四、Export LFP Images...

可選擇：

- 要輸出的 channel 和時間範圍；
- Raw 原始訊號或 Processed 處理後訊號，以及 Bandpass／Notch 設定；
- 波形圖、Power spectrum、Spectrogram，可同時選擇多種；
- Spectrogram 的 Auto PSD color scale，或自行輸入 Min／Max（dB）；
- 目的資料夾。

圖片固定以 300 DPI 輸出。檔名會自動包含原始檔名、channel、Raw／Processed 及圖表類型。準備大量資料或多張圖片時會顯示進度，需要時可按「Cancel」中止。使用 Processed＋Bandpass 匯出 Spectrogram 時，圖表只會顯示設定的頻率範圍。

### 五、Export Peak analyze Image

將 LFP peak 數量分析圖匯出為 PNG。使用前必須先完成同步與峰值偵測；匯出時可選擇要輸出的 LFP channel。

## 玖、儲存與開啟專案

使用「File > Save Project...」可把目前工作保存成 .pigproj，包括已匯入哪些檔案、目前影格、影片旋轉角度、圖表範圍、濾波設定、標記、同步選擇、LED 框選範圍與分析結果。

.pigproj **不會把原始影片或 CSV 包進專案檔**，只會記住檔案位置，並記錄用來確認檔案沒有被換掉的內容特徵。因此：

- 移動 .pigproj 時，請一併保留原始 MP4／CSV。
- 原始檔路徑失效時，開啟專案會要求重新指定檔案。
- 重新指定時必須選擇原本的檔案；內容修改過的副本可能不會被接受。
- 開啟含大型訊號資料的專案時會顯示準備進度，需要時可按「Cancel」中止開啟。
- 關閉程式或開啟其他專案前，如有未保存變更，程式會要求確認。

## 拾、使用 build.py 打包程式（維護者）

一般使用者不需要執行此步驟；正式交付時，只需提供打包完成的 PigBehaviorSync.exe。

打包前請先準備 Windows 開發環境，並安裝 requirements.txt 中的套件。若使用目前的 Conda 環境，可先執行「conda activate pig_gui」；第一次建立環境時，再執行「python -m pip install -r requirements.txt」。

打包方式：

1. 關閉正在執行的 PigBehaviorSync.exe，包括工作管理員中的背景程序，否則舊檔案可能無法取代。
2. 在專案根目錄執行「python build.py」。
3. 等待 PyInstaller 完成；正式執行檔會輸出至 dist\PigBehaviorSync.exe。
4. 在交付前，請實際開啟 dist\PigBehaviorSync.exe，確認程式可啟動、匯入檔案，並能執行需要使用的 GPU／CPU 功能。

build.py 會建立單一執行檔，並一併打包程式圖示、PyOpenCL 與必要的 Conda DLL。若畫面提示缺少 PyInstaller、PyOpenCL，或 NumPy／PyOpenCL 原生模組無法載入，請先修正打包環境後再重新執行。
