# accounts/tests.py

from django.contrib.auth.models import User
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse


class RegisterTests(APITestCase):
    """測試 register API 的各種情境"""

    def setUp(self):
        # setUp 會在「每一個」測試方法執行前自動先跑一次
        # 這裡先用 reverse() 把 urls.py 裡的 name='register' 轉成真正的路徑
        # 好處：以後路徑改了，測試不用跟著改
        self.register_url = reverse('register')

    def test_register_success(self):
        """測試項目 1：正常註冊應該成功，並回傳 201"""
        data = {
            "username": "newuser01",
            "email": "newuser01@example.com",
            "password": "StrongPass123!"
        }
        response = self.client.post(self.register_url, data, format='json')

        # assertEqual：斷言，如果左右兩邊不相等，測試就會標記為失敗
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 順便驗證：資料庫裡真的多了這個使用者
        self.assertTrue(User.objects.filter(username="newuser01").exists())

    def test_register_duplicate_username(self):
        """測試項目 2：username 重複註冊，應該回傳 400"""
        # 先手動建立一筆已存在的使用者，模擬「已經有人註冊過」
        User.objects.create_user(username="existuser", password="Pass123!")

        # 再用同一個 username 嘗試註冊
        data = {
            "username": "existuser",
            "email": "another@example.com",
            "password": "AnotherPass123!"
        }
        response = self.client.post(self.register_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
    def test_register_password_blank(self):
        """測試項目 3：密碼欄位空白，應該回傳 400"""
        data = {
            "username": "newuser02",
            "email": "newuser02@example.com",
            "password": ""
        }
        response = self.client.post(self.register_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.login_url = reverse('login')
    
    def test_login_success(self):
        """測試項目 1：帳號密碼都正確，應該成功拿到 token"""
        data = {
            "username": "testuser",
            "password": "testpass123"
        }
        response = self.client.post(self.login_url, data, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_login_wrong_password(self):
        data = {
            "username": "testuser",
            "password": "wrongpass111"
        }
        response = self.client.post(self.login_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_nonexistent_user(self):
        data = {
            "username": "nonexistentuser",
            "password": "somepass123"
        }
        response = self.client.post(self.login_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
