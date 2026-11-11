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

# 在專案根目錄建立 .env，填入自己的 Gemini API Key
echo "GEMINI_API_KEY=你的Key" > .env

python manage.py migrate
python manage.py runserver
```

## 測試

```bash
python manage.py test
```

**不需要 API key、不打網路**：測試會把 LLM 換成假的實作，Chroma 改用記憶體模式，上傳檔案存到暫存資料夾，跑完不留任何檔案。

目前共 44 個自動化測試：

| 模組 | 數量 | 涵蓋內容 |
|---|---|---|
| 帳號（`accounts/tests.py`） | 7 | 註冊、登入、取得使用者資訊 |
| 文件（`documents/tests.py`） | 29 | 上傳、列表、刪除、問答、處理狀態、重新處理、503 錯誤處理，以及未登入、跨使用者隔離、不殘留向量、不洩漏內部細節 |
| LLM Service（`documents/test_llm_service.py`） | 8 | 錯誤分類與重試：暫時性錯誤重試後成功、重試用完、持續性錯誤不重試、429 每日額度、逾時與連線錯誤 |

開發時採用 TDD（先寫測試、確認紅燈、再實作），一跑就通過的測試會用「暫時改壞程式、確認測試變紅」的方式驗證它真的有效。

## 已知限制

- AI 回答偶爾會出現「幻覺」（回答中摻入文件未提及的內容），已透過 prompt 設計降低發生機率，但無法完全避免，這是目前 LLM 應用的普遍限制
- `.pdf`/`.docx` 的解析仰賴第三方套件（`pypdf`、`python-docx`），排版複雜的檔案抽取效果可能受影響
- 文件處理是同步進行的：大檔案上傳時，請求會等到所有段落向量化完成才回應
- 429 錯誤的 `quotaId` 格式是參考 Google AI 開發者論壇的社群回報，並非官方文件

## 關於作者

許豪椲｜非本科系轉職 Python 後端工程師，這個專案是自學過程中，從零開始設計並實作的完整後端系統。
