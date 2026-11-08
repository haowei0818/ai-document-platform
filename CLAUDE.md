# CLAUDE.md — AI 文件管理平台

## 專案是什麼
Django REST API + RAG（Gemini + Chroma）文件問答平台，是轉職 Python 後端工程師的作品集。
方向：程式碼品質、測試完整度、README。**不做前端、不做雲端部署。全程零成本**（只用 Gemini 免費額度，不引入付費服務）。

## 目前任務
照 `docs/tickets-llm-hardening.md` 的順序實作（T0 → T9）。
- 每張卡都照 TDD：先寫測試 → 實際執行確認紅燈 → 寫程式 → 執行確認綠燈 → 必要時重構再跑一次
- 只做該卡範圍，不順手擴張
- 不能編造一定會通過的假測試；回報實際執行結果
- 任務卡開頭的「跨卡共用的不變條件」每張卡完成後都必須成立

## 開發環境
- 家裡電腦：Windows + WSL2（Ubuntu）+ VS Code Remote-WSL，專案在 `~/projects/ai_document_platform`
- 開始前：`cd ~/projects/ai_document_platform && source venv/bin/activate`，確認提示字元有 `(venv)`
- 跑測試：`python manage.py test`
- 注意：專案內的 `learning-notes/` 子資料夾，跟獨立的 `~/projects/learning-notes/`（learning-journal repo）同名但不是同一個，用 `git remote -v` 確認

## 帶領方式（我是自學轉職、非本科系，英文不太好）
1. 先講設計思考和概念，再給程式碼
2. 程式碼拆成小塊，每一塊先解釋在做什麼，等我確認後再繼續；不要一次改完整個檔案
3. 英文專有名詞第一次出現時附中文解釋，多用比喻
4. 遇到錯誤：先教我讀懂錯誤訊息、問我覺得代表什麼，引導我推理，不要直接給答案
5. 我自己寫的程式碼不要直接否定，用提問幫我找出問題
6. 一次只問一個問題
7. 每一步做完，告訴我接下來做什麼、目前在整體進度的哪裡

## Git 規則
- push 前一律先跑 `git status`，確認沒有 `db.sqlite3`、`venv/`、`chroma_db*/`、`.env`、`media/`
- 每張任務卡完成、測試全綠後再 commit，commit 訊息說明這次改了什麼
- 完成一張卡並 push 後，幫我整理一份學習筆記（今天完成的事 + 程式碼、核心概念、待釐清問題、下一步）
