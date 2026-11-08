from types import SimpleNamespace

from django.test import SimpleTestCase
from google.genai import errors

from .llm_service import LLMService


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


def embed_success(values):
    """做出一個 embed 成功回應；真的回應是用 result.embeddings[0].values 取向量。"""
    return SimpleNamespace(embeddings=[SimpleNamespace(values=values)])


class LLMServiceRetryTests(SimpleTestCase):

    def test_transient_error_twice_then_success(self):
        client = FakeClient([server_error(), server_error(), embed_success([0.1, 0.2])])
        sleep = FakeSleep()
        llm = LLMService(client=client, sleep=sleep)

        result = llm.embed('hello')

        self.assertEqual(result, [0.1, 0.2])          # 最後拿到成功的結果
        self.assertEqual(client.models.call_count, 3)  # 總共呼叫 3 次
        self.assertEqual(sleep.calls, [1, 2])          # 等了 2 次：1 秒、2 秒（指數退避），但沒有真的等
