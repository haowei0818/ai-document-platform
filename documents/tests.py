from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Document


class DocumentTests(APITestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username='user_a', password='testpass123')
        self.user_b = User.objects.create_user(username='user_b', password='testpass123')

    def test_upload_success(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            response = self.client.post(
                reverse('document-upload'),
                {'title': '我的文件', 'file': f}
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_upload_unauthenticated(self):
        with open('test.txt', 'rb') as f:
            response = self.client.post(
                reverse('document-upload'),
                {'title': '我的文件', 'file': f}
            )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_success(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            self.client.post(reverse('document-upload'), {'title': '我的文件', 'file': f})
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_list_unauthenticated(self):
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_list_only_shows_own_documents(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            self.client.post(reverse('document-upload'), {'title': '我的文件', 'file': f})

        self.client.force_authenticate(user=self.user_b)
        response = self.client.get(reverse('document-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_delete_success(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            response = self.client.post(reverse('document-upload'), {'title': '我的文件', 'file': f})
        doc_id = response.data['id']
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_delete_unauthenticated(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            response = self.client.post(reverse('document-upload'), {'title': '我的文件', 'file': f})
        doc_id = response.data['id']

        self.client.force_authenticate(user=None)
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_other_users_document(self):
        self.client.force_authenticate(user=self.user_a)
        with open('test.txt', 'w') as f:
            f.write('測試內容')
        with open('test.txt', 'rb') as f:
            response = self.client.post(reverse('document-upload'), {'title': '我的文件', 'file': f})
        doc_id = response.data['id']

        self.client.force_authenticate(user=self.user_b)
        response = self.client.delete(reverse('document-delete', args=[doc_id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
