from rest_framework import generics
from django.contrib.auth.models import User
from .serializers import RegisterSerializer, UserSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

# 「註冊」這個櫃檯：負責處理新使用者的建立
class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()  # 這個櫃檯負責處理的資料範圍：所有的 User
    serializer_class = RegisterSerializer  # 要用哪張「表格」來檢查、處理送進來的資料

    # 「查詢自己資料」這個櫃檯：只有登入的人，才能看到自己的資料
class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer

    # get_object：告訴這個櫃檯「要回傳誰的資料」
    # self.request.user：DRF 會自動幫我們認出「現在是誰在呼叫這支 API」（靠的就是 Token）
    def get_object(self):
        return self.request.user