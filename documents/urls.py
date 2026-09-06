from django.urls import path
from . import views

urlpatterns = [
    path('upload/', views.DocumentUploadView.as_view(), name='document-upload'),
    path('', views.DocumentListView.as_view(), name='document-list'),
    path('<int:pk>/', views.DocumentDeleteView.as_view(), name='document-delete'),
]