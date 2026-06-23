from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta

from .models import Stock, DailyQuote, MinuteBar
from .serializers import (
    StockSerializer, DailyQuoteSerializer,
    MinuteBarSerializer, DashboardStockSerializer,
    StockSearchSerializer,
)
from .services import (
    fetch_stock_info, fetch_daily_data,
    fetch_minute_data, fetch_stock_all_data,
    fetch_all_active_stocks,
    search_stocks,
)


class StockViewSet(viewsets.ModelViewSet):
    """关注股票 CRUD"""
    queryset = Stock.objects.filter(is_active=True)
    serializer_class = StockSerializer

    def create(self, request, *args, **kwargs):
        """添加关注：如果股票已存在但被软删除，则恢复"""
        code = request.data.get('code', '')
        existing = Stock.objects.filter(code=code).first()
        if existing and not existing.is_active:
            # 恢复已软删除的股票
            name = request.data.get('name', '') or ''
            if not name.strip():
                name = fetch_stock_info(code) or code
            existing.is_active = True
            existing.name = name
            existing.save()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        # 正常新建流程
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        """添加关注时自动补全股票名称"""
        code = serializer.validated_data['code']
        name = serializer.validated_data.get('name', '') or ''
        if not name.strip():
            name = fetch_stock_info(code) or code
        serializer.save(name=name)

    def perform_destroy(self, instance):
        """取消关注（软删除）"""
        instance.is_active = False
        instance.save()

    @action(detail=True, methods=['post'], url_path='fetch')
    def fetch_data(self, request, pk=None):
        """手动触发单只股票数据拉取"""
        stock = self.get_object()
        try:
            count = fetch_stock_all_data(stock)
            return Response({
                'status': 'success',
                'code': stock.code,
                'count': count,
            })
        except Exception as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'], url_path='search')
    def search(self, request):
        """搜索股票（支持代码或名称模糊匹配）"""
        keyword = request.query_params.get('q', '')
        results = search_stocks(keyword)
        serializer = StockSearchSerializer(results, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'], url_path='fetch-all')
    def fetch_all(self, request):
        """手动触发所有关注股票数据拉取"""
        results = fetch_all_active_stocks()
        return Response({'results': results})

    @action(detail=True, methods=['get'], url_path='daily')
    def daily_quotes(self, request, pk=None):
        """获取某股票日K数据，支持 ?days=N 和 ?date=YYYY-MM-DD"""
        stock = self.get_object()
        queryset = DailyQuote.objects.filter(stock=stock)

        # 按日期筛选
        if date_str := request.query_params.get('date'):
            from datetime import datetime
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            queryset = queryset.filter(trade_date=date_obj)
        elif days := request.query_params.get('days'):
            days = int(days)
            start_date = timezone.now().date() - timedelta(days=days)
            queryset = queryset.filter(trade_date__gte=start_date)

        queryset = queryset.order_by('-trade_date')
        serializer = DailyQuoteSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='daily/latest')
    def daily_latest(self, request, pk=None):
        """获取某股票最新一天行情（含高低点时间）"""
        stock = self.get_object()
        try:
            latest = DailyQuote.objects.filter(stock=stock).latest('trade_date')
            serializer = DailyQuoteSerializer(latest)
            return Response(serializer.data)
        except DailyQuote.DoesNotExist:
            return Response(
                {'detail': '暂无数据'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['get'], url_path='minutes')
    def minute_bars(self, request, pk=None):
        """获取分钟K线数据，支持 ?date=YYYY-MM-DD"""
        stock = self.get_object()
        queryset = MinuteBar.objects.filter(stock=stock)

        if date_str := request.query_params.get('date'):
            from datetime import datetime
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            start = timezone.make_aware(
                datetime.combine(date_obj, datetime.min.time())
            )
            end = start + timedelta(days=1)
            queryset = queryset.filter(datetime__range=(start, end))

        queryset = queryset.order_by('datetime')
        serializer = MinuteBarSerializer(queryset, many=True)
        return Response(serializer.data)


@api_view(['GET'])
def dashboard(request):
    """Dashboard 聚合数据：所有关注股票当日摘要"""
    stocks = Stock.objects.filter(is_active=True)
    today = timezone.now().date()
    data = []

    for stock in stocks:
        try:
            quote = DailyQuote.objects.get(stock=stock, trade_date=today)
            data.append({
                'id': stock.id,
                'code': stock.code,
                'name': stock.name,
                'trade_date': quote.trade_date,
                'open_price': quote.open_price,
                'close_price': quote.close_price,
                'high_price': quote.high_price,
                'low_price': quote.low_price,
                'high_time': quote.high_time,
                'low_time': quote.low_time,
                'open_close_diff': quote.open_close_diff,
                'open_close_pct': quote.open_close_pct,
                'high_low_diff': quote.high_low_diff,
                'high_low_pct': quote.high_low_pct,
                'prev_close': quote.prev_close,
                'change_diff': quote.change_diff,
                'change_pct': quote.change_pct,
                'volume': quote.volume,
                'turnover': quote.turnover,
            })
        except DailyQuote.DoesNotExist:
            # 如果今天没有数据，取最新的一条
            try:
                latest = DailyQuote.objects.filter(stock=stock).latest('trade_date')
                data.append({
                    'id': stock.id,
                    'code': stock.code,
                    'name': stock.name,
                    'trade_date': latest.trade_date,
                    'open_price': latest.open_price,
                    'close_price': latest.close_price,
                    'high_price': latest.high_price,
                    'low_price': latest.low_price,
                    'high_time': latest.high_time,
                    'low_time': latest.low_time,
                    'open_close_diff': latest.open_close_diff,
                    'open_close_pct': latest.open_close_pct,
                    'high_low_diff': latest.high_low_diff,
                    'high_low_pct': latest.high_low_pct,
                    'prev_close': latest.prev_close,
                    'change_diff': latest.change_diff,
                    'change_pct': latest.change_pct,
                    'volume': latest.volume,
                    'turnover': latest.turnover,
                })
            except DailyQuote.DoesNotExist:
                data.append({
                    'id': stock.id,
                    'code': stock.code,
                    'name': stock.name,
                    'trade_date': None,
                    'open_price': None,
                    'close_price': None,
                    'high_price': None,
                    'low_price': None,
                    'high_time': None,
                    'low_time': None,
                    'open_close_diff': None,
                    'open_close_pct': None,
                    'high_low_diff': None,
                    'high_low_pct': None,
                    'prev_close': None,
                    'change_diff': None,
                    'change_pct': None,
                    'volume': None,
                    'turnover': None,
                })

    serializer = DashboardStockSerializer(data, many=True)
    return Response(serializer.data)
