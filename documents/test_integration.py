"""真實 Gemini 整合測試：預設跳過，設定 RUN_LLM_INTEGRATION=1 才執行。

執行方式：
    RUN_LLM_INTEGRATION=1 python manage.py test documents.test_integration

會真的呼叫 Gemini（需要 .env 裡的 GEMINI_API_KEY），單次執行共 2 次請求。
"""
import os
from unittest import skipUnless

from django.test import SimpleTestCase

from .llm_service import LLMService

RUN_INTEGRATION = os.environ.get('RUN_LLM_INTEGRATION') == '1'


@skipUnless(RUN_INTEGRATION, '設定 RUN_LLM_INTEGRATION=1 才執行（會呼叫真實 Gemini）')
class GeminiIntegrationTests(SimpleTestCase):

    def setUp(self):
        self.llm = LLMService()
        self.llm.MAX_RETRIES = 0      # 關掉重試：每個測試最多 1 次請求

    def test_embed_returns_float_vector(self):
        vector = self.llm.embed('整合測試')

        self.assertIsInstance(vector, list)
        self.assertEqual(len(vector), 3072)                      # gemini-embedding-001 的維度
        self.assertTrue(all(isinstance(v, float) for v in vector))

    def test_generate_returns_text_and_token_usage(self):
        with self.assertLogs('documents.llm_service', level='INFO') as logs:
            answer = self.llm.generate('請只回覆「OK」兩個字。')

        self.assertIsInstance(answer, str)
        self.assertTrue(answer.strip())                          # 不是空字串
        self.assertIsNotNone(logs.records[0].llm['tokens'])      # 驗證 T7 的查證：generate 有 token 用量
