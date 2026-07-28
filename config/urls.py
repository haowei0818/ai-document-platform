from django.contrib import admin
from django.urls import path, include  # 多 import 一個 include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/accounts/', include('accounts.urls')),  # 新增這一行
]
