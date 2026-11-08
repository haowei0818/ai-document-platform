import shutil
import tempfile
from unittest.mock import patch

import chromadb
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from . import rag_utils
from .models import Document


class FakeLLMService:
    """測試用的假總機：不打網路、不需要 API key、每次結果都一樣"""

    def embed(self, text):
        return [float(len(text)), 1.0, 0.0]

    def generate(self, prompt):
        return '這是測試用的假回答'


class DocumentTests(APITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 上傳的檔案存到暫存資料夾，不留在專案的 media/
        cls._media_root = tempfile.mkdtemp()
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._media_override.enable()
        # Chroma 換成記憶體倉庫，不寫硬碟
        cls.chroma = chromadb.EphemeralClient()
        rag_utils.set_chroma_client(cls.chroma)

    @classmethod
    def tearDownClass(cls):
        rag_utils.set_chroma_client(None)
        cls._media_override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        # 擦黑板：每個測試開始前清空 Chroma
        for collection in self.chroma.list_collections():
            self.chroma.delete_collection(collection.name)

        # 上傳（rag_utils）和問答（views）兩個使用的地方都要換成假總機
        for target in ('documents.rag_utils.LLMService', 'documents.views.LLMService'):
            patcher = patch(target, FakeLLMService)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.user_a = User.objects.create_user(username='user_a', password='testpass123')
        self.user_b = User.objects.create_user(username='user_b', password='testpass123')

    def _upload(self, title='我的文件', content='測試內容'):
        file = SimpleUploadedFile('test.txt', content.encode('utf-8'))
        return self.client.post(reverse('document-upload'), {'title': title, 'file': file})

    def test_upload_success(self):
        self.client.force_authenticate(user=self.user_a)
        response = self._upload()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_unauthenticated(self):
        response = self._upload()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_success(self):
        self.client.force_authenticate(user=self.user_a)
        self._upload()
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_list_unauthenticated(self):
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_only_shows_own_documents(self):
        self.client.force_authenticate(user=self.user_a)
        self._upload()

        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_delete_success(self):
        self.client.force_authenticate(user=self.user_a)
        response = self._upload()
        doc_id = response.data['id']
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_unauthenticated(self):
        self.client.force_authenticate(user=self.user_a)
        response = self._upload()
        doc_id = response.data['id']

        self.client.force_authenticate(user=None)
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_other_users_document(self):
        self.client.force_authenticate(user=self.user_a)
        response = self._upload()
        doc_id = response.data['id']

        self.client.force_authenticate(user=self.user_b)
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_removes_document_chunks(self):
        self.client.force_authenticate(user=self.user_a)
        doc_id = self._upload().data['id']
        other_id = self._upload('其他文件', '其他內容').data['id']

        self.client.delete(reverse('document-delete', args=[doc_id]))

        collection = rag_utils.get_chroma_collection()
        self.assertEqual(collection.get(where={'document_id': doc_id})['ids'], [])
        self.assertNotEqual(collection.get(where={'document_id': other_id})['ids'], [])

    def test_deleted_document_not_in_ask_sources(self):
        self.client.force_authenticate(user=self.user_a)
        doc_id = self._upload('要刪的文件', '公司地址位於台北市').data['id']
        self.client.delete(reverse('document-delete', args=[doc_id]))

        response = self.client.post(reverse('document-ask'), {'question': '公司在哪裡?'})
        source_titles = [s['title'] for s in response.data['sources']]
        self.assertNotIn('要刪的文件', source_titles)

    def test_delete_does_not_affect_other_users_chunks(self):
        self.client.force_authenticate(user=self.user_b)
        b_doc_id = self._upload('B的文件', 'B的內容').data['id']
        self.client.force_authenticate(user=self.user_a)
        a_doc_id = self._upload().data['id']

        self.client.delete(reverse('document-delete', args=[a_doc_id]))

        collection = rag_utils.get_chroma_collection()
        self.assertNotEqual(collection.get(where={'document_id': b_doc_id})['ids'], [])

    def test_delete_document_without_chunks(self):
        self.client.force_authenticate(user=self.user_a)
        doc_id = self._upload().data['id']
        rag_utils.delete_document_chunks(doc_id)  # 模擬「Chroma 裡本來就沒有向量」

        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_ask_success(self):
        self.client.force_authenticate(user=self.user_a)
        self._upload('公司地址文件', '公司地址位於台北市信義區松仁路100號。')

        response = self.client.post(reverse('document-ask'), {'question': '公司在哪裡?'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('answer', response.data)
        self.assertTrue(len(response.data['answer']) > 0)
        source_titles = [s['title'] for s in response.data['sources']]
        self.assertIn('公司地址文件', source_titles)

    def test_ask_unauthenticated(self):
        response = self.client.post(reverse('document-ask'), {'question': '隨便問一個問題'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_ask_does_not_leak_other_users_documents(self):
        self.client.force_authenticate(user=self.user_a)
        self._upload('A的秘密文件', '特殊通關密語是紫色的獨角獸在跳舞。')

        self.client.force_authenticate(user=self.user_b)
        response = self.client.post(reverse('document-ask'), {'question': '特殊通關密語是什麼?'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        source_titles = [s['title'] for s in response.data['sources']]
        self.assertNotIn('A的秘密文件', source_titles)


class DocumentStatusMigrationTests(TransactionTestCase):
    """用時光機測 migration：倒帶到沒有 status 的過去，放一份舊文件，再快轉回來。"""

    before = [('documents', '0002_alter_document_file')]
    after = [('documents', '0003_document_status')]

    def tearDown(self):
        # 不管測試成功或失敗，都把資料庫結構還原到最新版，避免影響其他測試
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_documents_become_ready(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old_apps = executor.loader.project_state(self.before).apps
        OldUser = old_apps.get_model('auth', 'User')
        OldDocument = old_apps.get_model('documents', 'Document')
        user = OldUser.objects.create(username='old_user')
        OldDocument.objects.create(user=user, title='舊文件', file='uploads/old.txt')

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new_apps = executor.loader.project_state(self.after).apps
        NewDocument = new_apps.get_model('documents', 'Document')
        self.assertEqual(NewDocument.objects.get(title='舊文件').status, 'ready')
