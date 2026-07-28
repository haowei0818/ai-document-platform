from rest_framework import serializers
from django.contrib.auth.models import User


# 這是「註冊表格」，規定填寫規則
class RegisterSerializer(serializers.ModelSerializer):
    # write_only=True：這個欄位只能被填入，絕對不會被回傳出去給任何人看
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User  # 這張表格對應到「User（使用者）」這個資料表
        fields = ('username', 'email', 'password')  # 表格上只有這三個欄位

    # 當表格內容通過檢查後，這個方法決定「怎麼把它變成真正的資料庫記錄」
    def create(self, validated_data):
        # validated_data：已經檢查過、確認格式正確的表格內容
        # User.objects.create_user()：Django 內建方法，會自動把密碼加密後才存進資料庫
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user  # 回傳建立好的使用者

        # 「查詢自己資料」時使用的表格：只回傳基本資料，故意不放 password 進去
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')  # 只列出這三個安全的欄位