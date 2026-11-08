"""LLM Service：所有 LLM 呼叫的唯一入口（總機）。

除了這個模組，其他地方都不能直接 import Gemini SDK。
對外只提供兩個能力：
- embed：文字轉成向量
- generate：根據 prompt 產生回答
"""
import os


class LLMService:
    EMBED_MODEL = 'gemini-embedding-001'
    GENERATE_MODEL = 'gemini-3.6-flash'

    def __init__(self, api_key=None):
        self._api_key = api_key
        self._client = None

    def _get_client(self):
        # 延遲初始化：第一次真的要呼叫時才讀 .env、才連線
        if self._client is None:
            from dotenv import load_dotenv
            from google import genai

            load_dotenv()
            api_key = self._api_key or os.environ.get('GEMINI_API_KEY')
            self._client = genai.Client(api_key=api_key)
        return self._client

    def embed(self, text: str) -> list[float]:
        result = self._get_client().models.embed_content(
            model=self.EMBED_MODEL,
            contents=text,
        )
        return list(result.embeddings[0].values)

    def generate(self, prompt: str) -> str:
        response = self._get_client().models.generate_content(
            model=self.GENERATE_MODEL,
            contents=prompt,
        )
        return response.text
