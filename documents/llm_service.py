"""LLM Service：所有 LLM 呼叫的唯一入口（總機）。

除了這個模組，其他地方都不能直接 import Gemini SDK。
對外只提供兩個能力：
- embed：文字轉成向量
- generate：根據 prompt 產生回答
"""
import os
import time

import httpx                      # SDK 底層的網路套件；逾時、連不上時會丟出它的例外
from google.genai import errors   # 不變條件允許 Service 自己 import SDK


class LLMUnavailableError(Exception):
    """LLM 服務暫時無法使用。

    呼叫端（上傳處理、問答 API）只需要接這個例外，
    不需要知道背後是 Gemini 還是其他服務。
    """


def _is_daily_quota(exc):
    """429 的 quotaId 含 PerDay 或 Daily → 今天的額度用完了，重試也沒用。"""
    body = exc.details if isinstance(exc.details, dict) else {}   # 不是 dict 就當成空的
    error = body.get('error', body)              # 正常情況外面包一層 'error'；沒有就用自己
    for detail in error.get('details', []):      # details 是一個 list，逐一檢查
        for violation in detail.get('violations', []):
            quota_id = violation.get('quotaId', '')
            if 'PerDay' in quota_id or 'Daily' in quota_id:
                return True
    return False                                 # 找不到 → 不是每日額度


class LLMService:
    EMBED_MODEL = 'gemini-embedding-001'
    GENERATE_MODEL = 'gemini-3.6-flash'
    MAX_RETRIES = 3    # 最多重試 3 次（加上第 1 次，總共最多 4 次）
    BASE_DELAY = 1     # 第一次重試前等 1 秒，之後每次乘以 2

    def __init__(self, api_key=None, client=None, sleep=time.sleep):
        self._api_key = api_key
        self._client = client   # 測試可以直接塞假的 client；正式環境是 None，第一次用到才建立
        self._sleep = sleep     # 等待用的函式；正式環境是真的 time.sleep，測試換成 FakeSleep

    def _get_client(self):
        # 延遲初始化：第一次真的要呼叫時才讀 .env、才連線
        if self._client is None:
            from dotenv import load_dotenv
            from google import genai

            load_dotenv()
            api_key = self._api_key or os.environ.get('GEMINI_API_KEY')
            self._client = genai.Client(api_key=api_key)
        return self._client

    def _call_with_retry(self, func):
        attempt = 0                                  # 已經重試幾次
        while True:
            try:
                return func()                        # 成功就直接回傳，離開迴圈
            except (errors.APIError, httpx.TransportError) as exc:   # Gemini 有回覆的錯誤 + 所有網路錯誤
                if not self._is_transient(exc) or attempt >= self.MAX_RETRIES:
                    raise LLMUnavailableError(       # 不值得重試，或重試次數用完 → 放棄
                        'LLM 服務暫時無法使用'        # 不帶內部細節
                    ) from exc                       # 例外鏈：保留原始錯誤給開發者查
                self._sleep(self.BASE_DELAY * 2 ** attempt)   # 等 1、2、4 秒
                attempt += 1

    @staticmethod
    def _is_transient(exc):
        """判斷表：這個錯誤是暫時性的嗎？（值得重試嗎？）"""
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError)):   # 網路沒回應：逾時或連不上
            return True
        if isinstance(exc, httpx.TransportError):    # 其他網路錯誤（例如讀到一半斷線）：不重試
            return False
        if isinstance(exc, errors.ServerError):      # 5xx：對方的問題，等一下可能就好
            return True
        return exc.code == 429 and not _is_daily_quota(exc)   # 429 要重試，但每日額度用完不重試

    def embed(self, text: str) -> list[float]:
        result = self._call_with_retry(
            lambda: self._get_client().models.embed_content(
                model=self.EMBED_MODEL,
                contents=text,
            )
        )
        return list(result.embeddings[0].values)

    def generate(self, prompt: str) -> str:
        response = self._call_with_retry(
            lambda: self._get_client().models.generate_content(
                model=self.GENERATE_MODEL,
                contents=prompt,
            )
        )
        return response.text
