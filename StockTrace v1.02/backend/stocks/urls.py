from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StockViewSet,
    dashboard,
    market_overview,
    market_trend,
    market_sectors,
    market_national_etf,
    market_etf_radar,
    market_etf_detail,
    market_institutions,
)

router = DefaultRouter()
router.register(r'stocks', StockViewSet, basename='stock')

urlpatterns = [
    path('', include(router.urls)),
    path('dashboard/', dashboard, name='dashboard'),
    path('market/', market_overview, name='market-overview'),
    path('market/trend/', market_trend, name='market-trend'),
    path('market/sectors/', market_sectors, name='market-sectors'),
    path('market/national-etf/', market_national_etf, name='market-national-etf'),
    path('market/etf-radar/', market_etf_radar, name='market-etf-radar'),
    path('market/etfs/<str:code>/', market_etf_detail, name='market-etf-detail'),
    path('market/institutions/', market_institutions, name='market-institutions'),
]
