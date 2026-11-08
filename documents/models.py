from django.db import models
from django.contrib.auth.models import User

class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', '處理中'
        READY = 'ready', '可問答'
        FAILED = 'failed', '處理失敗'

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    file = models.FileField(upload_to='uploads/')
    title = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
