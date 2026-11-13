# AI 文件管理平台

一個結合 Django REST API 與 AI 檢索增強生成（RAG）的文件管理系統，讓使用者上傳文件後，能用自然語言直接向 AI 提問，取得根據自己文件內容生成的答案，而不只是關鍵字搜尋。

## 功能

- 使用者註冊 / 登入（JWT 認證）
- 文件上傳、列表、刪除（支援 `.txt`、`.pdf`、`.docx`）
- 上傳文件自動切段、向量化，存入向量資料庫
- 文件處理狀態（`pending` / `ready` / `failed`），處理失敗的文件可以一鍵重新處理
- 刪除文件時同步清除向量資料庫裡的段落，不會殘留在問答結果中
- 針對使用者自己上傳過的所有文件進行自然語言問答（RAG）
- AI 服務暫時性錯誤自動重試；服務無法使用時回傳清楚的 503，不洩漏內部細節
- 每次 AI 呼叫都留下結構化 log（耗時、重試次數、token 用量），log 不含 prompt 或文件內容
- 每位使用者的文件與問答結果彼此隔離，互不可見

## 技術棧

- **後端框架**：Django 6 + Django REST Framework
- **認證**：JWT（`djangorestframework-simplejwt`）
- **AI 生成模型**：Google Gemini API（`gemini-3.6-flash`）
- **向量化模型**：Gemini Embedding（`gemini-embedding-001`）
- **向量資料庫**：Chroma（`chromadb`，本機持久化模式）
- **文件解析**：`pypdf`（PDF）、`python-docx`（Word）
- **測試**：Django `SimpleTestCase` / DRF `APITestCase`，以假的 LLM 與記憶體模式的 Chroma 執行，不打網路、不需要 API key

## 系統架構：RAG 如何運作

1. **上傳**：使用者上傳文件，系統依副檔名讀取純文字內容
2. **切段（Chunking）**：長文件切成多個重疊段落，避免語意在切點斷裂
3. **向量化（Embedding）**：每個段落轉換成向量，連同 `user_id`／`document_id` 等中繼資料存入 Chroma
4. **問答（Retrieval + Generation）**：使用者提問時，問題同樣向量化後，在 Chroma 中依 `user_id` 篩選並檢索最相關的段落，將檢索結果連同問題組成 prompt 交給 Gemini 生成答案

### 分層設計

```
views.py（API）
  ├─ rag_utils.py   文件處理流程、所有向量的寫入與刪除（以 document_id 為單位）
  └─ llm_service.py LLM Service：所有 Gemini 呼叫的唯一入口
                      ├─ embed()     文字 → 向量
                      └─ generate()  prompt → 回答
```

- 只有 `llm_service.py` 會 import Gemini SDK，其他模組都透過它呼叫 AI，方便替換模型、集中處理錯誤，也讓測試可以整個換成假的 LLM
- Gemini client 與 sleep 函式都可以注入（dependency injection），測試不需要真的連線或等待

### 文件處理狀態

```
上傳 / 重新處理 → pending → 先清除舊段落 → 切段、向量化
                                 ├─ 成功 → ready
                                 └─ 失敗 → 清除寫到一半的段落 → failed
```

- 向量資料庫裡只會有 `ready` 文件的段落，所以問答不需要另外判斷狀態
- 「先清除舊段落再重建」讓重新處理具有冪等性：同一份文件處理幾次，段落數量都一樣
- `status` 是唯讀欄位，使用者上傳時夾帶也不會被寫入

### 錯誤處理策略

LLM Service 會先把錯誤分類，再決定要不要重試（最多 3 次，指數退避 1、2、4 秒）：

| 錯誤 | 處理 |
|---|---|
| Gemini 5xx、429 每分鐘流量限制、逾時、連線錯誤 | 暫時性，重試 |
| 429 每日額度用完（`quotaId` 含 `PerDay`）、其他 4xx、其他網路錯誤 | 持續性，不重試 |

重試用完或遇到持續性錯誤時，一律丟出自訂的 `LLMUnavailableError`，呼叫端看不到 SDK 的原生例外。各 API 的處理方式：

| 情境 | 回應 |
|---|---|
| 上傳 / 重新處理時 LLM 失敗 | `200` / `201`，文件 `status` 為 `failed`（文件已收件，只是處理失敗，可以之後重新處理） |
| 問答時 LLM 失敗 | `503`：`{"code": "llm_unavailable", "detail": "AI 服務暫時無法使用，請稍後再試。"}` |

錯誤細節只寫進 log，log 與 API 回應都不包含 prompt、文件內容或內部錯誤訊息。

### LLM 呼叫 log

每次 `embed` / `generate` 都會寫一筆結構化 log（一次呼叫一筆，重試次數記在 `retries`）：

```
INFO:documents.llm_service:llm_call operation=generate model=gemini-3.6-flash duration_ms=850 success=True retries=0 tokens=1234
```

| 欄位 | 說明 |
|---|---|
| `operation` | `embed` 或 `generate` |
| `model` | 模型名稱 |
| `duration_ms` | 耗時（毫秒，包含重試等待時間） |
| `success` | 成功或失敗；成功為 `INFO`，失敗為 `WARNING` |
| `retries` | 重試次數 |
| `tokens` | token 用量；Gemini 沒有回傳時為 `None`（embed 的回應沒有這個欄位） |

同一包欄位也放在 log 紀錄的 `extra={'llm': ...}`，方便程式讀取或之後轉成 JSON。

## API 清單

| 方法 | 路徑 | 說明 | 需要登入 |
|---|---|---|---|
| POST | `/api/accounts/register/` | 註冊 | 否 |
| POST | `/api/accounts/login/` | 登入，取得 JWT token | 否 |
| GET | `/api/accounts/me/` | 取得目前使用者資訊 | 是 |
| POST | `/api/documents/upload/` | 上傳文件 | 是 |
| GET | `/api/documents/` | 列出自己的文件 | 是 |
| DELETE | `/api/documents/<id>/` | 刪除自己的文件（同步清除向量） | 是 |
| POST | `/api/documents/<id>/reprocess/` | 重新處理自己的文件 | 是 |
| POST | `/api/documents/ask/` | 針對自己的文件提問 | 是 |

上傳、列表、重新處理的回應都會包含文件的 `status`。操作別人的文件一律回 `404`，不透露文件是否存在。

## 本機執行方式

```bash
git clone https://github.com/haowei0818/ai-document-platform.git
cd ai-document-platform
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 只跑測試（不需要 API key）

```bash
python manage.py test
```

### 啟動伺服器（需要 Gemini API key）

```bash
# 在專案根目錄建立 .env，填入自己的 Gemini API Key
echo "GEMINI_API_KEY=你的Key" > .env

python manage.py migrate
python manage.py runserver
```

## 實際操作範例

以下是在本機實際執行的結果（`<token>` 為登入取得的 JWT）。流程中刻意用錯誤的 API key 啟動伺服器，展示 AI 服務失敗時的行為，再換回正確的 key 重新處理。

**1. 註冊、登入**

```bash
curl -X POST http://127.0.0.1:8000/api/accounts/register/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","email":"demo@example.com","password":"DemoPass123!"}'
# {"username":"demo_user","email":"demo@example.com"}

curl -X POST http://127.0.0.1:8000/api/accounts/login/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"demo_user","password":"DemoPass123!"}'
# {"refresh":"...","access":"<token>"}
```

**2. AI 服務失敗時上傳：文件仍然收下，狀態為 `failed`**

```bash
curl -X POST http://127.0.0.1:8000/api/documents/upload/ \
  -H 'Authorization: Bearer <token>' \
  -F 'title=公司資訊' -F 'file=@company.txt'
# HTTP 201
# {"id":9,"title":"公司資訊","file":"http://127.0.0.1:8000/media/uploads/company.txt","uploaded_at":"2026-11-13T15:18:03.873393Z","status":"failed"}
```

**3. AI 服務失敗時問答：回 `503`，不洩漏內部錯誤**

```bash
curl -X POST http://127.0.0.1:8000/api/documents/ask/ \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"question":"公司在哪裡？"}'
# HTTP 503
# {"code":"llm_unavailable","detail":"AI 服務暫時無法使用，請稍後再試。"}
```

此時伺服器 log（只記錄欄位，不含問題、文件內容或 API key）：

```
llm_call operation=embed model=gemini-embedding-001 duration_ms=62 success=False retries=0 tokens=None
ask failed: llm unavailable, user_id=5
```

Gemini 對錯誤的 API key 回 `400 INVALID_ARGUMENT`，被判斷為持續性錯誤，所以沒有重試（`retries=0`）。

**4. 換回正確的 key，重新處理：變成 `ready`**

```bash
curl -X POST http://127.0.0.1:8000/api/documents/9/reprocess/ \
  -H 'Authorization: Bearer <token>'
# HTTP 200
# {"id":9,"title":"公司資訊","file":"http://127.0.0.1:8000/media/uploads/company.txt","uploaded_at":"2026-11-13T15:18:03.873393Z","status":"ready"}
```

**5. 問答**

```bash
curl -X POST http://127.0.0.1:8000/api/documents/ask/ \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"question":"公司在哪裡？"}'
# HTTP 200
# {"answer":"公司位於台北市信義區松仁路100號。","sources":[{"document_id":9,"title":"公司資訊"}]}
```

**6. 刪除文件後再問：向量同步清除，問不到了**

```bash
curl -X DELETE http://127.0.0.1:8000/api/documents/9/ \
  -H 'Authorization: Bearer <token>'
# HTTP 204

curl -X POST http://127.0.0.1:8000/api/documents/ask/ \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"question":"公司在哪裡？"}'
# HTTP 200
# {"answer":"目前找不到相關的文件內容，請確認是否已上傳相關文件。","sources":[]}
```

## 測試

測試分成兩種：

| 種類 | 指令 | 需要 API key | 打網路 |
|---|---|---|---|
| 一般測試（預設） | `python manage.py test` | 否 | 否 |
| 真實 Gemini 整合測試 | `RUN_LLM_INTEGRATION=1 python manage.py test documents.test_integration` | 是 | 是（單次 2 個請求） |

### 一般測試

**不需要 API key、不打網路**：測試會把 LLM 換成假的實作，Chroma 改用記憶體模式，上傳檔案存到暫存資料夾，跑完不留任何檔案。

目前共 50 個自動化測試，預設執行 48 個，2 個整合測試會顯示為已跳過（`OK (skipped=2)`）：

| 模組 | 數量 | 涵蓋內容 |
|---|---|---|
| 帳號（`accounts/tests.py`） | 7 | 註冊、登入、取得使用者資訊 |
| 文件（`documents/tests.py`） | 29 | 上傳、列表、刪除、問答、處理狀態、重新處理、503 錯誤處理，以及未登入、跨使用者隔離、不殘留向量、不洩漏內部細節 |
| LLM Service（`documents/test_llm_service.py`） | 12 | 錯誤分類與重試（暫時性錯誤重試後成功、重試用完、持續性錯誤不重試、429 每日額度、逾時與連線錯誤），以及呼叫 log（欄位完整、失敗記重試次數、沒有 token 用量、不含 prompt） |
| 整合測試（`documents/test_integration.py`） | 2 | 預設跳過；真的呼叫 Gemini，確認 `embed` 回傳 3072 維向量、`generate` 回傳文字且有 token 用量 |

開發時採用 TDD（先寫測試、確認紅燈、再實作），一跑就通過的測試會用「暫時改壞程式、確認測試變紅」的方式驗證它真的有效。

### 真實 Gemini 整合測試

用來偶爾確認 mock 和現實沒有脫節（例如 Gemini 改了回傳格式或模型下架）。預設跳過，需要 `.env` 裡有 `GEMINI_API_KEY`：

```bash
RUN_LLM_INTEGRATION=1 python manage.py test documents.test_integration
```

整合測試內關閉重試，單次執行固定只會用到 2 個請求（embed 1 次、generate 1 次），不會大量消耗免費額度。

## 已知限制

- AI 回答偶爾會出現「幻覺」（回答中摻入文件未提及的內容），已透過 prompt 設計降低發生機率，但無法完全避免，這是目前 LLM 應用的普遍限制
- `.pdf`/`.docx` 的解析仰賴第三方套件（`pypdf`、`python-docx`），排版複雜的檔案抽取效果可能受影響
- 文件處理是同步進行的：大檔案上傳時，請求會等到所有段落向量化完成才回應
- 429 錯誤的 `quotaId` 格式是參考 Google AI 開發者論壇的社群回報，並非官方文件

## 關於作者

許豪椲｜非本科系轉職 Python 後端工程師，這個專案是自學過程中，從零開始設計並實作的完整後端系統。
