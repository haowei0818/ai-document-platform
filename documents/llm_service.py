"""LLM Service：所有 LLM 呼叫的唯一入口（總機）。

除了這個模組，其他地方都不能直接 import Gemini SDK。
對外只提供兩個能力：
- embed：文字轉成向量
- generate：根據 prompt 產生回答
"""
import os
import time

from google.genai import errors   # 不變條件允許 Service 自己 import SDK


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
            except errors.ServerError:
                if attempt >= self.MAX_RETRIES:      # 重試次數用完 → 放棄，往外丟
                    raise
                self._sleep(self.BASE_DELAY * 2 ** attempt)   # 等 1、2、4 秒
                attempt += 1

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
