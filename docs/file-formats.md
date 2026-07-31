# 程式資料格式與狀態模型開發指引

本文件是給本專案的程式編輯者使用，說明模組之間交換的資料結構、`AppState` 欄位、時間座標、Marker 模型、檔案邊界，以及 `.pigproj` 的序列化規則。

重點不是教使用者如何操作檔案，而是讓開發者在新增功能、修改 state、匯入／匯出或跨元件傳值時，有一致的資料契約可遵循。

## 1. 核心設計原則

### 1.1 `AppState` 是共享資料的 composition root

`src/app_state.py` 的 `AppState` 聚合所有 feature state：

```text
AppState
├── video: VideoState
├── data: DataState
├── sync: SyncState
├── ttl: TtlState
├── led: LedState
├── markers: MarkerState
├── analysis: AnalysisSettings
└── project: ProjectState
```

只有應用程式根元件應持有完整 `AppState`。一般 widget、controller 或 service 應只注入自己需要的 feature state，避免任意跨領域修改。

物件組裝發生在 `src/application/composer.py`：

- `ApplicationComposer` 建立共享的 `MarkerStore`、service、controller 與 UI。
- 各元件收到的是同一份 state 物件引用，不是複製。
- state dataclass 本身不負責通知 UI；通知仍由 Qt signals/slots 或 `MarkerStore` signal 負責。

### 1.2 區分三種資料

| 類型 | 說明 | 例子 |
| --- | --- | --- |
| 來源資料 | 從外部檔案載入，可重新建立 | MP4、CSV、`LfpDataset.data` |
| 執行期狀態 | UI 或運算過程需要，不一定保存 | `is_playing`、`loading_video`、signal cache |
| 持久化狀態 | 關閉後需恢復，寫入 `.pigproj` | 目前影格、濾波設定、Marker、LED ROI |

新增欄位前必須先判斷它屬於哪一類。若欄位需要保存，除了 dataclass 外，還要同步修改：

1. `ExportController.save_project()`；
2. `ImportController.prepare_project_restore()`／`apply_project_restore()`；
3. `project_format.validate_state()`；
4. 必要時提升 `PROJECT_VERSION` 並處理舊版遷移；
5. 本文件及測試。

---

## 2. 共通型別與單位約定

### 2.1 時間

| 命名 | 單位／語意 |
| --- | --- |
| `*_us`、`[us]`、`(us)` | 微秒 |
| `*_sec`、`*_s` | 秒 |
| `video_time_sec` | 從影片第 0 秒起算 |
| `record_time_sec` | 從訊號／錄製第 0 秒起算 |
| `local_time_us` | Unix timestamp，微秒 |
| `frame_index` | 從 0 開始的影格編號 |

禁止只使用 `time` 當新欄位名稱；必須在名稱中表達時間域與單位。

影片與錄製時間的關係為：

```text
time_offset_sec = video_time_sec - record_time_sec
video_time_sec  = record_time_sec + time_offset_sec
record_time_sec = video_time_sec - time_offset_sec
```

`src/synchronization/time_conversion.py` 的：

- `relative_time(value, origin)`：`value - origin`；
- `absolute_time(value, origin)`：`value + origin`。

`origin` 是顯示座標原點，不等同於 video/record 兩個 domain 之間的 offset。

### 2.2 數值與集合

- 檔案載入的訊號值為 `float32`；分析函式通常轉為 NumPy `float`。
- JSON 內只應放可序列化的有限數字、字串、布林、`null`、list 與 object。
- state 中的可變預設值必須使用 `field(default_factory=...)`。
- 對外傳遞集合時，除非刻意共享所有權，應回傳 tuple 或 copy。
- 路徑在 state 中目前使用 `str`；實際檔案操作時轉為 `pathlib.Path`。

### 2.3 `None`、空集合與零

三者意義不同：

- `None`：尚未設定、尚未分析或沒有來源；
- `[]`／`{}`：已有此類資料，但目前內容為空；
- `0`／`0.0`：有效的數值零。

不得用 `if value` 取代需要區分零與未設定的判斷。

---

## 3. `AppState` 欄位完整說明

### 3.1 `VideoMetadata`

影片成功載入後，由 `VideoState.metadata` 持有。

| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `path` | `str` | 影片完整或已解析路徑 |
| `filename` | `str` | 只含檔名 |
| `file_format` | `str` | 容器／副檔名資訊 |
| `codec` | `str` | OpenCV 偵測到的 codec |
| `width` | `int` | 原始影格寬度，pixel |
| `height` | `int` | 原始影格高度，pixel |
| `detected_fps` | `float` | 從影片 metadata 偵測到的 FPS |
| `using_fps` | `float` | 程式實際採用的 FPS |
| `total_frames` | `int` | 總影格數 |
| `detected_duration_sec` | `float` | 由來源偵測的長度 |
| `duration_sec` | `float` | 程式實際採用的影片長度 |

時間換算應使用 `using_fps`，不要直接使用 `detected_fps`。邊界檢查使用 `total_frames` 與 `duration_sec`。

`VideoMetadata` 可由來源 MP4 重建，因此 `.pigproj` 不直接序列化整個物件。

### 3.2 `VideoState`

| 欄位 | 型別／預設 | 說明 | 是否持久化 |
| --- | --- | --- | --- |
| `metadata` | `VideoMetadata \| None` | 當前影片 metadata | 否，可由來源重建 |
| `current_frame` | `int = 0` | 當前影格，從 0 開始 | 是 |
| `is_playing` | `bool = False` | 播放器是否正在播放 | 否 |
| `rotation_degrees` | `int = 0` | 顯示／分析旋轉角度，只允許 0/90/180/270 | 是 |
| `rotate_180_enabled` | `bool = False` | 舊版相容旗標，等價於旋轉 180 度 | 是，相容用途 |

規則：

- `rotation_degrees` 是目前主要欄位。
- `rotate_180_enabled` 必須與 `rotation_degrees == 180` 一致。
- 新程式不要只更新其中一個欄位。
- 新影片載入時會重設目前影格、播放狀態、旋轉與部分同步／LED state。

### 3.3 `DataState`

保存 LFP、三軸資料及跨圖表設定。

| 欄位 | 型別／預設 | 說明 | 是否持久化 |
| --- | --- | --- | --- |
| `lfp_info` | `dict \| None` | LFP 檔案路徑及解析後 metadata | 來源路徑存於 manifest，其餘重建 |
| `lfp_dataset` | `LfpDataset \| None` | 完整 LFP DataFrame 與訊號 cache | 否 |
| `axis_info` | `dict \| None` | 三軸檔案路徑及解析後 metadata | 來源路徑存於 manifest，其餘重建 |
| `lfp_step` | `int \| None` | LFP 顯示抽樣／繪圖步長 | 是 |
| `axis_step` | `int \| None` | 三軸顯示抽樣／繪圖步長 | 是 |
| `line_noise_hz` | `float = 60.0` | UI 共用的電源線頻率 | 是 |
| `timeline_xlim` | `tuple[float, float] \| None` | 共用時間軸左右範圍，秒 | 是 |
| `selected_lfp_channel` | `int \| None` | 目前選取的實際通道 ID | 是 |
| `lfp_filter_settings` | `dict` | LFP 顯示／分析濾波設定 | 是 |
| `follow_video_playback` | `bool = True` | 波形是否跟隨影片播放位置 | 是 |

### `lfp_info`／`axis_info`

由 `parse_lfp_csv_info()` 產生，標準形狀為：

```python
{
    "path": str,
    "filename": str,
    "metadata": {
        "channels": list[int],
        "sample_rates": list[float],
        "header_row": int | None,
        "data_column_count": int | None,
        "time_unit": "s",
        "value_unit": str,
    },
    "channels": list[int],
    "sample_rates": list[float],
    "channel_count": int,
    "header_row": int | None,
    "data_column_count": int | None,
    "time_unit": "s",
    "value_unit": str,
}
```

注意：

- `channels` 是實際通道 ID，不保證從 0 或 1 連續排列。
- `selected_lfp_channel` 應存 channel ID，不是 list index。
- `metadata["header_row"]` 是從 0 開始的 CSV 列索引。
- 原始 CSV 時間為微秒；`time_unit: "s"` 表示 UI／圖表的標準時間單位。

### `lfp_filter_settings`

```python
{
    "show_filtered": False,
    "bandpass_enabled": False,
    "bandpass_low_hz": 1.0,
    "bandpass_high_hz": 100.0,
    "line_noise_hz": 60.0,
    "notch_quality": 30.0,
}
```

對應 `LfpFilterSettings`：

| 鍵 | 型別 | 說明 |
| --- | --- | --- |
| `show_filtered` | `bool` | False 時直接使用原始訊號，其他濾波設定不生效 |
| `bandpass_enabled` | `bool` | 是否套用 band-pass |
| `bandpass_low_hz` | `float` | band-pass 下界 |
| `bandpass_high_hz` | `float` | band-pass 上界 |
| `line_noise_hz` | `float \| None` | notch 頻率；None 表示不套用 |
| `notch_quality` | `float` | notch filter Q factor |

修改濾波設定後要考慮 `LfpDataset._signal_cache` 的 key／失效問題。

### 3.4 `LfpDataset`

`src/signal_data/lfp_dataset.py` 將同一個 LFP 檔案的完整解析結果集中管理：

```python
LfpDataset(
    info=<lfp_info>,
    data=pd.DataFrame(
        columns=["time_us", "channel_1", "channel_2", ...]
    ),
)
```

重要 property／method：

| 名稱 | 回傳 | 說明 |
| --- | --- | --- |
| `time_us` | `np.ndarray` | 原始微秒時間 |
| `record_time_s` | `np.ndarray` | `time_us / 1_000_000` |
| `channels` | `list[int]` | info 中的通道或從欄名推導 |
| `sample_rate_hz(channel)` | `float` | 優先取 metadata，否則由時間差中位數推導 |
| `signal_values(channel, settings)` | `np.ndarray` | 完整 raw／filtered 訊號，含 cache |
| `segment(...)` | `LfpSegment` | 指定秒數範圍的完整解析度片段 |

`LfpSegment` 欄位：

```python
{
    "time_us": np.ndarray,
    "record_time_s": np.ndarray,
    "values": np.ndarray,
    "sample_rate_hz": float,
}
```

`sample_count` 等於 `values.size`。

不要把 `LfpDataset` 或 NumPy array 直接塞進 project JSON。

### 3.5 `SyncState`

| 欄位 | 型別／預設 | 說明 | 是否持久化 |
| --- | --- | --- | --- |
| `time_offset_sec` | `float \| None` | video domain 與 record domain 的差 | 是 |
| `video_time_origin_sec` | `float \| None` | 影片 UI 的相對顯示原點 | 是 |
| `record_time_origin_sec` | `float \| None` | 波形 UI 的相對顯示原點 | 是 |
| `current_record_time_sec` | `float \| None` | 目前影片位置換算到 record domain 的秒數 | 否 |
| `event_intervals` | `list[dict]` | 波形目前顯示的事件區間／點 | 否，可由 Marker 重建 |
| `loading_video` | `bool = False` | 防止載入期間觸發一般同步副作用 | 否 |

目前 offset 由第一個 LED ON 影片 Marker 與第一個 TTL record Marker推導：

```text
time_offset_sec = first_video_led_sec - first_ttl_record_sec
```

`event_intervals` 可能有兩種形狀。

區間事件：

```python
{
    "event_type": "action" | "led",
    "video_start_sec": float,
    "video_end_sec": float,
    "record_start_sec": float,
    "record_end_sec": float,
    "start_marker_id": str,
    "end_marker_id": str,
}
```

單點 seizure-like 事件：

```python
{
    "event_type": "seizure_like_event",
    "video_time_sec": float,
    "record_time_sec": float,
    "marker_id": str,
}
```

若改變 Marker 配對或 offset，必須重新產生 interval，不要直接把 interval 當 canonical data。

### 3.6 `TtlState`

只有一個欄位：

```python
metadata: dict[str, Any] | None
```

由 `parse_time_marker_csv_info()` 產生：

```python
{
    "path": str,
    "filename": str,
    "time_column_name": str | None,
    "marker_count": int,
    "markers": list[dict],
    "first_marker_sec": float | None,
}
```

每個 legacy TTL marker dict 通常包含：

```python
{
    "local_time_us": int,
    "local_time": datetime,       # UTC+8 aware datetime
    "record_time": int,           # 微秒
    "record_hours": int,
    "record_minutes": int,
    "record_seconds": int,
    "record_microseconds": int,
}
```

Canonical TTL 事件仍應放進 `MarkerStore`，位置使用 `RecordPosition(record_time_us / 1_000_000)`。`TtlState.metadata` 是來源資訊，不應成為另一份獨立可編輯的 Marker 真相來源。

### 3.7 `LedState`

| 欄位 | 型別／預設 | 說明 | 是否持久化 |
| --- | --- | --- | --- |
| `roi` | `tuple[int,int,int,int] \| None` | `(x, y, width, height)`，pixel | 是 |
| `brightness_cache` | `dict[tuple, Any]` | LED 亮度掃描結果 cache | 是，以另一結構序列化 |
| `analysis_points` | `list \| None` | 最近一次亮度分析點 | 是 |
| `analysis_threshold` | `float = 0.0` | 最近一次偵測門檻 | 是 |
| `analysis_stats` | `dict \| None` | 最近一次分析統計 | 是 |
| `analysis_status` | `str \| None` | 可顯示的狀態摘要 | 是 |

### ROI

```text
(x, y, width, height)
```

- 座標對應旋轉後的顯示／分析影格。
- `x, y >= 0`，`width, height > 0`。
- 恢復專案時會依影片尺寸及旋轉驗證邊界。

### LED 資料類別

```python
LedBrightnessPoint(
    frame_index: int,
    video_time_sec: float,
    brightness: float,  # 灰階平均值正規化到約 0..1
)

LedChangePoint(
    frame_index: int,
    video_time_sec: float,
    delta: float,
)

LedEvent(
    event_type: str,
    video_time_sec: float,
    frame_index: int,
    brightness: float,
)
```

LED event 進入共享 Marker 系統後會轉為：

```python
Marker(
    kind=MarkerKind(event.event_type),
    source=MarkerSource.LED_DETECTION,
    position=VideoPosition(event.video_time_sec, event.frame_index),
    note=f"brightness={event.brightness:.4f}",
    payload={"brightness": float(event.brightness)},
)
```

### `brightness_cache`

執行期 key：

```python
(
    video_path: str,
    roi: tuple[int, int, int, int] | None,
    rotation_degrees: int,
    fps: float,
    start_frame: int,
    end_frame: int,
    coarse_step: int,
)
```

value 為 `list[LedBrightnessPoint]`。

任何會改變亮度結果的輸入都必須納入 key。新增偵測參數時，若結果會受其影響，必須擴充 cache key、專案序列化及恢復邏輯。

### 3.8 `MarkerState` 與 `MarkerStore`

`MarkerState`：

```python
markers: list[Marker]
```

`ApplicationComposer` 用這個同一份 list 建立：

```python
marker_store = MarkerStore(state.markers.markers)
```

### Canonical Marker model

```python
Marker(
    kind: MarkerKind,
    source: MarkerSource,
    position: VideoPosition | RecordPosition,
    note: str = "",
    payload: dict[str, Any] = {},
    marker_id: str = <UUID>,
)
```

`Marker`、`VideoPosition`、`RecordPosition` 都是 frozen dataclass。更新 Marker 不應直接修改欄位，而應使用 `MarkerStore.update()`，由 `dataclasses.replace()` 建立新物件。

### `MarkerKind`

| Enum | 實際字串 |
| --- | --- |
| `TTL` | `TTL` |
| `LED_ON` | `LED_on` |
| `LED_OFF` | `LED_off` |
| `ACTION_START` | `action_start` |
| `ACTION_END` | `action_end` |
| `SEIZURE_LIKE` | `seizure_like_event` |
| `LFP_PEAK` | `LFP_peak` |

### `MarkerSource`

| Enum | 實際字串 |
| --- | --- |
| `MANUAL` | `manual` |
| `TTL_IMPORT` | `ttl_import` |
| `LED_DETECTION` | `led_detection` |
| `LFP_DETECTION` | `lfp_peak` |
| `PROJECT_IMPORT` | `project_import` |

相容 alias：

- `lfp_detection` → `LFP_DETECTION`
- `timeline` → `TTL_IMPORT`

### Position

```python
VideoPosition(time_sec: float, frame_index: int)
RecordPosition(time_sec: float)
```

Marker 必須先保存它原生所在的 domain：

- 影片手動標記／LED 偵測：`VideoPosition`；
- TTL／LFP 訊號事件：`RecordPosition`。

只有顯示或跨 domain 操作時才使用 `time_offset_sec` 換算。不要在同步後破壞原生位置。

### `MarkerStore` 是唯一建議的修改入口

可用操作：

- `all()`：回傳 tuple；
- `get(marker_id)`；
- `add(marker)`；
- `update(marker_id, **changes)`；
- `delete(marker_id)`；
- `clear()`；
- `replace_all(markers)`；
- `replace_by_source(source, markers)`；
- `replace_by_kind(kind, markers)`；
- `by_source(source)`；
- `by_kind(kind)`。

一般程式不要直接 append／修改 `AppState.markers.markers`，否則不會觸發：

- `marker_added`
- `marker_updated`
- `marker_removed`
- `changed`

批次恢復時可使用 `emit=False`，但呼叫端必須負責最後的 UI refresh。

`marker_id` 必須唯一且穩定；更新事件時保留 ID，重新偵測並整批替換某 source 時可產生新 ID。

`payload` 只放該事件特有、可 JSON 序列化的附加資料，不要重複存可由 position 推導的主要時間欄位。

### 3.9 `AnalysisSettings`

| 欄位 | 預設 | 單位／意義 | 是否持久化 |
| --- | --- | --- | --- |
| `lfp_peak_height_sigma` | `8.0` | peak 高度相對於雜訊尺度的 sigma 倍數 | 是 |
| `lfp_peak_prominence_sigma` | `6.0` | prominence 的 sigma 倍數 | 是 |
| `lfp_peak_min_distance_sec` | `1.0` | peak 最小間隔，秒 | 是 |

驗證規則：

- height/prominence 必須是有限且 `>= 0`；
- min distance 必須是有限且 `> 0`。

演算法的固定參數不應無條件放入此 state；只有需要跨 UI／service 共用或保存的使用者設定才加入。

### 3.10 `ProjectState`

| 欄位 | 型別／預設 | 說明 |
| --- | --- | --- |
| `path` | `str \| None` | 目前 `.pigproj` 路徑 |
| `dirty` | `bool = False` | 是否存在未保存修改 |
| `loading` | `bool = False` | 是否正在套用專案內容 |

這三個欄位本身不寫入 `state.json`。

修改會影響專案恢復結果的資料時，應透過既有 signal 讓 `ProjectController` 設定 `dirty=True`。載入專案期間以 `loading=True` 抑制把 restore 動作誤判成使用者修改。

---

## 4. 狀態的所有權與更新流程

### 4.1 匯入 LFP

```text
CSV
 → parse_lfp_csv_info()
 → DataState.lfp_info
 → LfpDataset.from_csv()
 → DataState.lfp_dataset
 → WavePanel / LfpAnalysisService
```

不要讓多個 panel 各自重讀完整 CSV。`LfpDataset` 用來共用完整解析資料與 filtered signal cache。

### 4.2 匯入 TTL

```text
TTL CSV
 → parse_time_marker_csv_info()
 → TtlState.metadata
 → legacy TTL dict 轉 Marker
 → MarkerStore
 → SyncController 計算 offset
```

### 4.3 LED 偵測

```text
VideoState.metadata + LedState.roi
 → brightness curve
 → LedState.brightness_cache
 → analysis_points / threshold / stats
 → LedEvent
 → MarkerStore.replace_by_source(LED_DETECTION, ...)
 → SyncController 更新 offset 與 intervals
```

### 4.4 狀態通知

Dataclass assignment 本身沒有 observable 行為。修改 state 後必須確認相依元件是否需要：

- 發出 Qt signal；
- 呼叫 panel refresh／setter；
- 清除衍生 cache；
- 更新同步換算；
- 將 project 標記為 dirty。

不能假設 `state.foo = value` 會自動更新畫面。

---

## 5. `.pigproj` 持久化契約

`.pigproj` 是 ZIP 容器：

```text
*.pigproj
├── manifest.json
└── state.json
```

目前：

```python
PROJECT_FORMAT = "pig-analysis-project"
PROJECT_VERSION = 3
```

### 5.1 `manifest.json`

只保存來源路徑與檔案 identity：

```json
{
  "format": "pig-analysis-project",
  "version": 3,
  "sources": {
    "video": {
      "external_path": "C:\\data\\video.mp4",
      "filename": "video.mp4",
      "fingerprint": {
        "size": 123456,
        "sample_sha256": "64-hex-characters"
      }
    }
  }
}
```

允許的 source key：

- `video`
- `lfp`
- `axis`
- `ttl`

來源檔不內嵌於專案。fingerprint 使用檔案大小與開頭／中間／結尾的抽樣 SHA-256，屬快速 identity，不是完整檔案 hash。

### 5.2 `state.json`

實際保存形狀：

```python
{
    "video": {
        "current_frame": int,
        "rotation_degrees": int,
        "rotate_180_enabled": bool,
    },
    "data": {
        "lfp_step": int | None,
        "axis_step": int | None,
        "line_noise_hz": float,
        "timeline_xlim": [float, float] | None,
        "selected_lfp_channel": int | None,
        "lfp_filter_settings": dict,
        "follow_video_playback": bool,
    },
    "analysis": {
        "lfp_peak_height_sigma": float,
        "lfp_peak_prominence_sigma": float,
        "lfp_peak_min_distance_sec": float,
    },
    "sync": {
        "time_offset_sec": float | None,
        "video_time_origin_sec": float | None,
        "record_time_origin_sec": float | None,
    },
    "ttl": {
        "metadata": dict,
    },
    "led": {
        "roi": [int, int, int, int] | None,
        "analysis_points": list | None,
        "analysis_threshold": float,
        "analysis_stats": dict | None,
        "analysis_status": str | None,
        "brightness_cache": list[dict],
    },
    "markers": list[dict],
}
```

注意 tuple 寫入 JSON 後會變成 list，restore 時需明確轉回 tuple／dataclass。

### 5.3 Marker JSON

Video domain：

```json
{
  "marker_id": "uuid",
  "kind": "LED_on",
  "source": "led_detection",
  "position": {
    "domain": "video",
    "time_sec": 12.34,
    "frame_index": 370
  },
  "note": "brightness=0.9234",
  "payload": {
    "brightness": 0.9234
  }
}
```

Record domain：

```json
{
  "marker_id": "uuid",
  "kind": "TTL",
  "source": "ttl_import",
  "position": {
    "domain": "record",
    "time_sec": 2.5
  },
  "note": "",
  "payload": {}
}
```

`marker_to_dict()` 會處理：

- `datetime` → ISO 8601；
- NumPy scalar → Python scalar；
- 有 `tolist()` 的值 → list。

這只處理 payload 的第一層 value。不要放入任意深層的不可序列化物件。

### 5.4 LED cache JSON

執行期 dict 會轉成 list：

```python
{
    "roi": list[int] | None,
    "rotation_degrees": int,
    "rotate_180": bool,  # 相容欄位
    "fps": float,
    "start_frame": int,
    "end_frame": int,
    "coarse_step": int,
    "points": list[LedBrightnessPoint],
}
```

restore 後再建立 tuple key 與 `LedBrightnessPoint`。

### 5.5 驗證限制

`project_format.py` 目前限制：

- `manifest.json` 最大 1 MiB；
- `state.json` 最大 256 MiB；
- Marker／LED list 最大 1,000,000 筆；
- Marker 文字欄位最大 100,000 字；
- current frame 與各種 index 不得為負；
- rotation 只允許 0/90/180/270；
- timeline 必須為兩個有限數字且左 < 右；
- ROI 必須為四個整數且落在影片邊界內。

新增持久化欄位時，不能只讓 JSON 能寫出；也要加入 restore 前驗證，避免未信任專案內容直接進入 UI 或運算程式。

---

## 6. 外部檔案邊界

這一節只記錄會影響內部資料形狀的格式規則。

### 6.1 訊號 CSV

```csv
Channels,1,2,3
Sample Rate[Hz],1000,1000,1000
Unit,uV,uV,uV
Time[us],1,2,3
0,12.5,-3.2,8.0
1000,12.8,-3.0,8.1
```

解析規則：

- UTF-8 with BOM (`utf-8-sig`)；
- `Channels` 值轉為 `int`；
- 任何第一欄以 `Sample Rate` 開頭的列會解析取樣率；
- `Unit`／`Units` 為選填；
- 必須找到完全相符的 `Time[us]`；
- DataFrame 欄位標準化為 `time_us`, `channel_<id>`；
- 數值以 `float32` 載入。

### 6.2 TTL CSV

```csv
local_time(us),record_time(us)
1785100800123456,0
1785100801123456,1000000
```

- 第一個名稱結尾為 `_time(us)` 的欄位視為絕對時間；
- record 欄接受 `record_time(us)`、`recording_time(us)`、`record time(us)`；
- 找不到標準名稱時，為相容舊檔而退回前兩欄；
- 絕對時間轉為 UTC+8 aware `datetime`；
- 無效資料列會略過。

### 6.3 MP4

UI 正式接受 `.mp4`，以 OpenCV `VideoCapture` 解析。內部邏輯應使用 `VideoMetadata.using_fps`，且不要由副檔名假設 codec。

### 6.4 匯出格式

這些是輸出邊界，不是 canonical state：

- 事件 CSV/XLSX：`event_type`, `video_time_sec`, `frame_index`, `note`；
- TTL CSV/XLSX：`marker_index`, `local_time(us)`, `local_time`, `record_time(us)`, `record_time`；
- 檢查報告 CSV：`Type`, `File`, `Value`；
- 圖表：PNG、JPG/JPEG、PDF、SVG。

新增輸出欄位時，優先從 canonical Marker／state 推導，不要為了輸出方便在 state 重複保存相同資料。

---

## 7. 開發者變更檢查表

### 新增 `AppState` 欄位

- [ ] 欄位放在正確的 feature state，而不是直接塞進 `AppState`。
- [ ] 名稱表達 domain 與單位。
- [ ] 可變預設值使用 `default_factory`。
- [ ] 決定是來源、執行期或持久化狀態。
- [ ] 找出欄位唯一寫入者與讀取者。
- [ ] 定義修改後的 signal／refresh／cache invalidation。
- [ ] 若需保存，更新 save、validate、restore 與版本相容。

### 新增 Marker 種類

- [ ] 加入 `MarkerKind`。
- [ ] 選擇正確的 `MarkerSource`。
- [ ] 明確定義原生 position domain。
- [ ] payload 只含可 JSON 序列化的額外資料。
- [ ] 更新 UI label／filter／排序。
- [ ] 更新 interval 或同步邏輯（如適用）。
- [ ] 測試 project round trip。

### 修改同步

- [ ] 保持 `video = record + offset` 的符號定義。
- [ ] 不混淆 origin 與 offset。
- [ ] 未同步時允許 `None`，不要假設為 0。
- [ ] 測試 VideoPosition 與 RecordPosition 雙向換算。
- [ ] 重新產生 `event_intervals` 與目前時間游標。

### 修改檔案／專案格式

- [ ] 先定義資料契約與錯誤處理。
- [ ] 對輸入做大小、型別、有限數值與邊界驗證。
- [ ] 測試空檔、缺欄、錯誤型別、巨大集合與中文路徑。
- [ ] 測試 save → close → restore 結果一致。
- [ ] 若破壞相容性，提升 `PROJECT_VERSION`，不要靜默改變 v3 意義。

---

## 8. 常見錯誤

1. **直接改 `state.markers.markers`**  
   UI 收不到 `MarkerStore` 通知。請使用 store API。

2. **把秒和微秒混在一起**  
   外部 CSV 常用微秒，內部圖表、Marker position 與同步一律用秒。

3. **把 channel index 當成 channel ID**  
   `channels=[2, 5]` 時第二個 channel 的 ID 是 5，不是 1。

4. **只新增 dataclass 欄位，忘記專案 restore**  
   執行中看似正常，但重新開啟專案會遺失資料。

5. **把衍生資料當 canonical state**  
   `event_intervals`、顯示時間文字與輸出列都應由 Marker／offset 推導。

6. **修改 state 後期待 UI 自動更新**  
   Dataclass 沒有通知機制，必須走既有 controller 與 signal。

7. **修改濾波或 LED 參數後沿用舊 cache**  
   cache key 必須完整包含所有會影響結果的輸入，否則應清除 cache。

8. **用 0 表示尚未同步或未分析**  
   0 可能是有效值；未設定應使用 `None`。

9. **把任意 Python 物件放入 payload／state**  
   專案保存使用 JSON，應在資料進入 state 時就轉為穩定、明確的基本型別。

10. **將 `.pigproj` 視為自包含資料包**  
    它只包含 JSON 狀態與外部檔案 identity，不包含原始 MP4／CSV。
