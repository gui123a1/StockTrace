from django.contrib import admin
from .models import Stock, DailyQuote, MinuteBar


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'created_at']
    search_fields = ['code', 'name']
    list_filter = ['is_active']
    actions = ['activate_stocks', 'deactivate_stocks']

    @admin.action(description='启用监控')
    def activate_stocks(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='停止监控')
    def deactivate_stocks(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(DailyQuote)
class DailyQuoteAdmin(admin.ModelAdmin):
    list_display = [
        'stock', 'trade_date', 'open_price', 'close_price',
        'high_price', 'low_price', 'open_close_pct', 'high_low_pct',
    ]
    list_filter = ['trade_date', 'stock']
    search_fields = ['stock__code', 'stock__name']
    date_hierarchy = 'trade_date'
    raw_id_fields = ['stock']


@admin.register(MinuteBar)
class MinuteBarAdmin(admin.ModelAdmin):
    list_display = ['stock', 'datetime', 'open', 'close', 'high', 'low', 'volume']
    list_filter = ['stock']
    date_hierarchy = 'datetime'
    raw_id_fields = ['stock']
