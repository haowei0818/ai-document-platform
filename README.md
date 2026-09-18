# AI 文件管理平台

一個結合 Django REST API 與 AI 檢索增強生成（RAG）的文件管理系統，讓使用者上傳文件後，能用自然語言直接向 AI 提問，取得根據自己文件內容生成的答案，而不只是關鍵字搜尋。

## 功能

- 使用者註冊 / 登入（JWT 認證）
- 文件上傳、列表、刪除（支援 `.txt`、`.pdf`、`.docx`）
- 上傳文件自動切段、向量化，存入向量資料庫
- 針對使用者自己上傳過的所有文件進行自然語言問答（RAG）
- 每位使用者的文件與問答結果彼此隔離，互不可見

## 技術棧

- **後端框架**：Django 6 + Django REST Framework
- **認證**：JWT（`djangorestframework-simplejwt`）
- **AI 生成模型**：Google Gemini API（`gemini-3.6-flash`）
- **向量化模型**：Gemini Embedding（`gemini-embedding-001`）
- **向量資料庫**：Chroma（`chromadb`，本機持久化模式）
- **文件解析**：`pypdf`（PDF）、`python-docx`（Word）
- **測試**：Django `TestCase` / DRF `APITestCase`

## 系統架構：RAG 如何運作

1. **上傳**：使用者上傳文件，系統依副檔名讀取純文字內容
2. **切段（Chunking）**：長文件切成多個重疊段落，避免語意在切點斷裂
3. **向量化（Embedding）**：每個段落轉換成向量，連同 `user_id`／`document_id` 等中繼資料存入 Chroma
4. **問答（Retrieval + Generation）**：使用者提問時，問題同樣向量化後，在 Chroma 中依 `user_id` 篩選並檢索最相關的段落，將檢索結果連同問題組成 prompt 交給 Gemini 生成答案

## API 清單

| 方法 | 路徑 | 說明 | 需要登入 |
|---|---|---|---|
| POST | `/api/accounts/register/` | 註冊 | 否 |
| POST | `/api/accounts/login/` | 登入，取得 JWT token | 否 |
| GET | `/api/accounts/me/` | 取得目前使用者資訊 | 是 |
| POST | `/api/documents/upload/` | 上傳文件 | 是 |
| GET | `/api/documents/` | 列出自己的文件 | 是 |
| DELETE | `/api/documents/<id>/` | 刪除自己的文件 | 是 |
| POST | `/api/documents/ask/` | 針對自己的文件提問 | 是 |

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

目前共 18 個自動化測試（帳號模組 7 個、文件管理模組 11 個，含 3 個問答功能測試），涵蓋正常情況、未登入、跨使用者資料隔離等安全情境。

## 已知限制

- AI 回答偶爾會出現「幻覺」（回答中摻入文件未提及的內容），已透過 prompt 設計降低發生機率，但無法完全避免，這是目前 LLM 應用的普遍限制
- `.pdf`/`.docx` 的解析仰賴第三方套件（`pypdf`、`python-docx`），排版複雜的檔案抽取效果可能受影響
- 測試會呼叫真實的 Gemini API，尚未導入 mock 機制

## 關於作者

許豪椲｜非本科系轉職 Python 後端工程師，這個專案是自學過程中，從零開始設計並實作的完整後端系統。
