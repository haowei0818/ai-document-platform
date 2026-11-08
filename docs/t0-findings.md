# T0 查證紀錄（Spike）

查證日期：2026-11-08
查證對象：GitHub `haowei0818/ai-document-platform` 最新 commit（只讀，未修改程式碼）

## 1. 刪除文件時有沒有清 Chroma 向量 → ⚠️ 沒有（已發現漏洞，交給 T2）

- `documents/views.py:28` `DocumentDeleteView` 只繼承 `DestroyAPIView`，沒有覆寫 `perform_destroy`，只刪資料庫紀錄。
- 全專案 grep `signal`、`post_delete`、`pre_delete`、`def delete`：**0 筆**。沒有其他地方處理刪除。
- `documents/apps.py` 沒有 `ready()`，也沒有註冊 signals。
- 結論：刪除後向量仍留在 Chroma；因為問答只用 `user_id` 篩選（`views.py:55`），**已刪除文件的內容仍會出現在該使用者的問答與 `sources` 裡**。

## 2. 直接使用 Gemini SDK 的位置

| 檔案:行號 | 內容 |
|---|---|
| `documents/rag_utils.py:38` | `from google import genai`（唯一 import SDK 的地方） |
| `documents/rag_utils.py:42` | `genai.Client(api_key=...)` |
| `documents/rag_utils.py:66` | `client.models.embed_content(model='gemini-embedding-001', ...)`（上傳時，逐段向量化） |
| `documents/views.py:44` | `get_gemini_client()`（`DocumentAskView` 拿到原生 client） |
| `documents/views.py:47` | `client.models.embed_content(...)`（問題向量化） |
| `documents/views.py:76` | `client.models.generate_content(model='gemini-3.6-flash', ...)`（生成回答） |

模型名稱寫死在兩個檔案裡（`rag_utils.py`、`views.py`）。

## 3. 直接取得 Chroma collection 的位置

| 檔案:行號 | 內容 |
|---|---|
| `documents/rag_utils.py:45-55` | `get_chroma_collection()`：`PersistentClient`，`settings.TESTING` 時用 `./chroma_db_test` |
| `documents/rag_utils.py:60, 71` | 上傳處理時取得 collection 並 `collection.add(...)` |
| `documents/views.py:45, 52` | 問答時取得 collection 並 `collection.query(...)` |
| `config/settings.py:131` | `TESTING = 'test' in sys.argv` |

全專案沒有任何 `collection.delete(...)`。

## 4. 測試數量 → 18 個（與預期一致）

- `accounts/tests.py`：7 個
- `documents/tests.py`：11 個

## 額外發現（不在 T0 範圍，記錄給後續卡參考）

1. **現有測試會真的打 Gemini**：`documents/tests.py` 沒有任何 mock，上傳和問答測試都會呼叫真實 API、寫入 `./chroma_db_test`。→ T1 要處理。
2. **測試之間有順序依賴**：`documents/tests.py:24` `test_upload_unauthenticated` 直接 `open('test.txt', 'rb')`，但自己沒有建立這個檔案，是靠「別的測試先建立過」。在全新 clone 單獨跑這個測試會 `FileNotFoundError`。→ 剛好對應 T1 驗收條件「單獨跑任一個測試結果都相同」。
3. **測試會在專案根目錄留下 `test.txt`**，也會在 `media/uploads/` 留下上傳檔案；`test.txt` 不在 `.gitignore` 裡。→ T1「不留垃圾」可以一併考慮。
4. **chunk id 含隨機 uuid**（`rag_utils.py:70`）：重複處理同一份文件會累積 chunk，不會覆蓋。→ T3/T5「先清舊 chunk 再重建」的必要性來源。
5. 刪除使用者時（`models.py` `on_delete=CASCADE`），文件跟著刪，但向量一樣會殘留；刪除文件時 `media/` 裡的實體檔案也不會刪。→ 不在這次範圍，列入未決事項即可。
