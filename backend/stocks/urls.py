from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StockViewSet, dashboard

router = DefaultRouter()
router.register(r'stocks', StockViewSet, basename='stock')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', dashboard, name='dashboard'),
]
