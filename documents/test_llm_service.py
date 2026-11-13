import os
import subprocess
import sys
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase
from google.genai import errors
import httpx

from .llm_service import LLMService, LLMUnavailableError


class FakeModels:
    """假的 client.models：照順序演出預先排好的劇本（錯誤或成功值）。"""

    def __init__(self, script):
        self._script = list(script)   # 劇本，例如 [錯誤, 錯誤, 成功值]
        self.call_count = 0           # 記錄被呼叫幾次，給測試檢查

    def embed_content(self, model, contents):
        return self._next()

    def generate_content(self, model, contents):
        return self._next()

    def _next(self):
        self.call_count += 1
        outcome = self._script.pop(0)     # 拿出劇本的下一幕
        if isinstance(outcome, Exception):
            raise outcome                 # 這一幕是錯誤 → 丟出去
        return outcome                    # 這一幕是成功 → 回傳


class FakeClient:
    """假的 Gemini client；真的 client 是用 client.models.xxx() 呼叫，所以結構照抄。"""

    def __init__(self, script):
        self.models = FakeModels(script)


class FakeSleep:
    """假的 sleep：不真的等待，只記下被要求等幾秒。"""

    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def server_error():
    """做出一個 Gemini 503 錯誤（伺服器太忙，屬於暫時性錯誤）。"""
    return errors.ServerError(503, {'error': {'code': 503, 'status': 'UNAVAILABLE', 'message': 'overloaded'}})


def client_error_400():
    """做出一個 Gemini 400 錯誤（請求格式錯誤，屬於持續性錯誤，重試也沒用）。"""
    return errors.ClientError(400, {'error': {'code': 400, 'status': 'INVALID_ARGUMENT', 'message': 'bad request'}})

def rate_limit_error(quota_id):
    """做出一個 Gemini 429 錯誤；格式參考真實回應（見論壇查證）。"""
    return errors.ClientError(429, {'error': {
        'code': 429,
        'status': 'RESOURCE_EXHAUSTED',
        'message': 'You exceeded your current quota',
        'details': [
            {'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
             'violations': [{'quotaId': quota_id}]},
            {'@type': 'type.googleapis.com/google.rpc.RetryInfo',
             'retryDelay': '1s'},
        ],
    }})

def bare_rate_limit_error():
    """做出一個沒有 details 的 429（論壇上有人回報過這種格式），無法判斷是不是每日額度。"""
    return errors.ClientError(429, {'error': {
        'code': 429,
        'status': 'RESOURCE_EXHAUSTED',
        'message': 'Resource has been exhausted (e.g. check quota).',
    }})

def embed_success(values):
    """做出一個 embed 成功回應；真的回應是用 result.embeddings[0].values 取向量。"""
    return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])


def generate_success(text, total_tokens=None):
    """做出一個 generate 成功回應；真的回應用 response.usage_metadata.total_token_count 取 token 用量。"""
    usage = SimpleNamespace(total_token_count=total_tokens) if total_tokens is not None else None
    return SimpleNamespace(text=text, usage_metadata=usage)


class LLMServiceRetryTests(SimpleTestCase):

    def test_transient_error_twice_then_success(self):
        client = FakeClient([server_error(), server_error(), embed_success([0.1, 0.2])])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        result = llm.embed('hello')

        self.assertEqual(result, [0.1, 0.2])          # 最後拿到成功的結果
        self.assertEqual(client.models.call_count, 3)  # 總共呼叫 3 次
        self.assertEqual(sleep.calls, [1, 2])          # 等了 2 次：1 秒、2 秒（指數退避），但沒有真的等

    def test_transient_error_forever_raises_unified_error(self):
        # 劇本：連續 4 次都是 503（第 1 次 + 重試 3 次）
        client = FakeClient([server_error()] * 4)
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        with self.assertRaises(LLMUnavailableError):   # 期待丟出「我們自己的」例外
            llm.embed('hello')

        self.assertEqual(client.models.call_count, 4)  # 第 1 次 + 重試 3 次 = 4 次
        self.assertEqual(sleep.calls, [1, 2, 4])       # 每次重試前都等，時間加倍

    def test_permanent_error_raises_without_retry(self):
        # 劇本只放 1 幕：如果程式去重試，劇本會不夠用而出錯
        client = FakeClient([client_error_400()])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        with self.assertRaises(LLMUnavailableError):
            llm.embed('hello')

        self.assertEqual(client.models.call_count, 1)  # 只呼叫 1 次
        self.assertEqual(sleep.calls, [])              # 完全沒有等待

    def test_rate_limit_per_minute_is_retried(self):
        # 劇本：每分鐘流量限制 1 次 → 成功
        client = FakeClient([
            rate_limit_error('GenerateRequestsPerMinutePerProjectPerModel-FreeTier'),
            embed_success([0.3]),
        ])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        result = llm.embed('hello')

        self.assertEqual(result, [0.3])                # 最後成功
        self.assertEqual(client.models.call_count, 2)  # 第 1 次失敗 + 重試 1 次
        self.assertEqual(sleep.calls, [1])             # 重試前有等待

    def test_daily_quota_exhausted_is_not_retried(self):
        # 劇本只放 1 幕：每日額度用完，重試也沒用；如果程式去重試，劇本會不夠用而出錯
        client = FakeClient([rate_limit_error('GenerateRequestsPerDayPerProjectPerModel-FreeTier')])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        with self.assertRaises(LLMUnavailableError):
            llm.embed('hello')

        self.assertEqual(client.models.call_count, 1)  # 只呼叫 1 次
        self.assertEqual(sleep.calls, [])              # 完全沒有等待

    def test_rate_limit_without_details_is_retried(self):
        # 分不出是哪種 429 時，當成暫時性：最多多花 3 次呼叫，用完一樣會拋出統一例外
        client = FakeClient([bare_rate_limit_error(), embed_success([0.5])])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        result = llm.embed('hello')

        self.assertEqual(result, [0.5])
        self.assertEqual(client.models.call_count, 2)
        self.assertEqual(sleep.calls, [1])

    def test_timeout_and_connection_error_are_retried(self):
        # 劇本：讀取逾時 → 連不上 → 成功
        client = FakeClient([
            httpx.ReadTimeout('timed out'),
            httpx.ConnectError('connection refused'),
            embed_success([0.7]),
        ])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        result = llm.embed('hello')

        self.assertEqual(result, [0.7])
        self.assertEqual(client.models.call_count, 3)  # 失敗 2 次 + 第 3 次成功
        self.assertEqual(sleep.calls, [1, 2])          # 退避等待照常

    def test_other_network_error_is_translated_without_retry(self):
        # 讀到一半連線斷掉：不在重試清單裡，但也不能讓 httpx 的原生例外漏給呼叫端
        client = FakeClient([httpx.ReadError('connection reset')])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        with self.assertRaises(LLMUnavailableError):
            llm.embed('hello')

        self.assertEqual(client.models.call_count, 1)  # 只呼叫 1 次
        self.assertEqual(sleep.calls, [])              # 完全沒有等待


class LLMServiceLoggingTests(SimpleTestCase):

    def test_successful_call_logs_all_fields(self):
        client = FakeClient([generate_success('答案', total_tokens=42)])
        llm = LLMService(client=client, sleep=FakeSleep())

        with self.assertLogs('documents.llm_service', level='INFO') as logs:
            llm.generate('hello')

        self.assertEqual(len(logs.records), 1)                 # 一次呼叫，剛好一筆 log
        fields = logs.records[0].llm                           # 讀出 extra 掛上去的那一包欄位
        self.assertEqual(fields['operation'], 'generate')
        self.assertEqual(fields['model'], LLMService.GENERATE_MODEL)
        self.assertIsInstance(fields['duration_ms'], int)      # 耗時每次都不同，只檢查型別
        self.assertTrue(fields['success'])
        self.assertEqual(fields['retries'], 0)
        self.assertEqual(fields['tokens'], 42)

    def test_failed_call_logs_retries(self):
        client = FakeClient([server_error()] * 4)            # 第 1 次 + 重試 3 次，全部失敗
        llm = LLMService(client=client, sleep=FakeSleep())

        with self.assertLogs('documents.llm_service', level='INFO') as logs:
            with self.assertRaises(LLMUnavailableError):
                llm.embed('hello')

        self.assertEqual(len(logs.records), 1)                 # 重試 3 次也只有一筆
        record = logs.records[0]
        self.assertEqual(record.levelname, 'WARNING')          # 失敗用 WARNING
        self.assertEqual(record.llm['operation'], 'embed')
        self.assertFalse(record.llm['success'])
        self.assertEqual(record.llm['retries'], 3)
        self.assertIsNone(record.llm['tokens'])                # 失敗了，當然沒有 token 用量

    def test_missing_token_usage_still_logs(self):
        client = FakeClient([embed_success([0.1])])            # embed 的回應沒有 usage_metadata
        llm = LLMService(client=client, sleep=FakeSleep())

        with self.assertLogs('documents.llm_service', level='INFO') as logs:
            llm.embed('hello')

        self.assertIsNone(logs.records[0].llm['tokens'])

    def test_logs_never_contain_prompt(self):
        secret = '機密文件內容-SECRET-12345'
        client = FakeClient([generate_success('答案', total_tokens=1), client_error_400()])
        llm = LLMService(client=client, sleep=FakeSleep())

        with self.assertLogs('documents.llm_service', level='INFO') as logs:
            llm.generate(secret)                               # 成功的呼叫
            with self.assertRaises(LLMUnavailableError):
                llm.embed(secret)                              # 失敗的呼叫

        self.assertEqual(len(logs.records), 2)
        for line in logs.output:                               # 給人看的訊息
            self.assertNotIn(secret, line)
        for record in logs.records:                            # 給程式讀的欄位
            self.assertNotIn(secret, str(record.llm))


class LoggingConfigTests(SimpleTestCase):

    def test_info_logs_are_visible_outside_tests(self):
        """模擬 runserver：在測試環境以外，documents 的 INFO log 要真的印出來。"""
        code = (
            'import logging, django; django.setup(); '
            'logging.getLogger("documents.llm_service").info("probe-visible")'
        )
        result = subprocess.run(
            [sys.executable, '-c', code],
            cwd=settings.BASE_DIR,
            env={**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings'},
            capture_output=True, text=True,
        )
        self.assertIn('probe-visible', result.stderr)     # log 預設印在 stderr（標準錯誤輸出）
