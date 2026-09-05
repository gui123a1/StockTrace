from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    StockViewSet,
    dashboard,
    market_overview,
    market_trend,
    market_sectors,
    market_national_etf,
    market_national_etf_flow,
    market_fund_flow_window,
    market_northbound_window,
    market_etf_radar,
    market_etf_detail,
    market_institutions,
    alert_list,
    alert_detail,
    alert_event_list,
    alert_event_read,
    screener_preset_list,
    screener_preset_detail,
)
from .ai.views import (
    AiProviderViewSet,
    stock_ai_analysis,
    screener,
    screener_ai,
    screener_ai_comment,
)

router = DefaultRouter()
router.register(r'stocks', StockViewSet, basename='stock')
router.register(r'ai-providers', AiProviderViewSet, basename='ai-provider')

urlpatterns = [
    path('', include(router.urls)),
    path('stocks/<int:pk>/ai-analysis/', stock_ai_analysis, name='stock-ai-analysis'),
    path('screener/', screener, name='screener'),
    path('screener/ai/', screener_ai, name='screener-ai'),
    path('screener/ai/comment/', screener_ai_comment, name='screener-ai-comment'),
    path('screener/presets/', screener_preset_list, name='screener-preset-list'),
    path('screener/presets/<int:pk>/', screener_preset_detail, name='screener-preset-detail'),
    path('alerts/', alert_list, name='alert-list'),
    path('alerts/<int:pk>/', alert_detail, name='alert-detail'),
    path('alerts/events/', alert_event_list, name='alert-event-list'),
    path('alerts/events/read/', alert_event_read, name='alert-event-read'),
    path('dashboard/', dashboard, name='dashboard'),
    path('market/', market_overview, name='market-overview'),
    path('market/trend/', market_trend, name='market-trend'),
    path('market/sectors/', market_sectors, name='market-sectors'),
    path('market/national-etf/', market_national_etf, name='market-national-etf'),
    path('market/national-etf/flow/', market_national_etf_flow, name='market-national-etf-flow'),
    path('market/market-flow/', market_fund_flow_window, name='market-fund-flow-window'),
    path('market/northbound/', market_northbound_window, name='market-northbound-window'),
    path('market/etf-radar/', market_etf_radar, name='market-etf-radar'),
    path('market/etfs/<str:code>/', market_etf_detail, name='market-etf-detail'),
    path('market/institutions/', market_institutions, name='market-institutions'),
]
