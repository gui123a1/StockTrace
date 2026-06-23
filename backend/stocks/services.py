"""
多数据源股票数据获取与处理服务

数据源优先级（自动切换）：
1. 东方财富 (em) - AkShare stock_zh_a_hist / stock_zh_a_hist_min_em
2. 新浪 (sina) - AkShare stock_zh_a_daily / stock_zh_a_minute
3. BaoStock (bs) - BaoStock query_history_k_data_plus (5分钟K线)
4. 腾讯 (tx) - AkShare stock_zh_a_hist_tx

核心逻辑：
1. 获取日K线数据 → open, close, high, low, volume, turnover
2. 获取分钟K线数据 → 推算最高/最低点的精确时间
3. 计算差值和百分比
4. 存入数据库
"""

import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

import akshare as ak
import pandas as pd
from django.utils import timezone

from .models import Stock, DailyQuote, MinuteBar

logger = logging.getLogger(__name__)

# A股列表缓存（30分钟过期）
_stock_list_cache = {'df': None, 'expires': 0}
_STOCK_LIST_TTL = 1800

# ============================================================
# 工具函数
# ============================================================

def _to_shsz_prefix(code):
    """6位代码转为 sh/sz 前缀格式: 600000→sh600000, 000001→sz000001"""
    code = code.zfill(6)
    prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
    return f'{prefix}{code}'


# ============================================================
# 数据源适配器 - 每个数据源实现统一的接口
# ============================================================

class DataSource:
    """数据源基类"""
    name = 'base'

    def fetch_daily(self, symbol, start_date, end_date):
        """获取日K线，返回 DataFrame[日期,开盘,收盘,最高,最低,成交量,成交额]"""
        raise NotImplementedError

    def fetch_minute(self, symbol, start_dt, end_dt):
        """获取1分钟K线，返回 DataFrame[时间,开盘,收盘,最高,最低,成交量,成交额]"""
        raise NotImplementedError

    def fetch_stock_name(self, code):
        """获取股票名称，返回 str 或 None"""
        return None


class EastMoneySource(DataSource):
    """东方财富数据源"""
    name = 'eastmoney'

    def fetch_daily(self, symbol, start_date, end_date):
        df = ak.stock_zh_a_hist(
            symbol=symbol, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        # 标准化列名
        return df.rename(columns={
            '日期': '日期', '开盘': '开盘', '收盘': '收盘',
            '最高': '最高', '最低': '最低', '成交量': '成交量', '成交额': '成交额',
        })

    def fetch_minute(self, symbol, start_dt, end_dt):
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol, period="1",
            start_date=start_dt, end_date=end_dt, adjust="qfq"
        )
        return df.rename(columns={
            '时间': '时间', '开盘': '开盘', '收盘': '收盘',
            '最高': '最高', '最低': '最低', '成交量': '成交量', '成交额': '成交额',
        })

    def fetch_stock_name(self, code):
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code]
        if not row.empty:
            return row.iloc[0]['名称']
        return None


class SinaSource(DataSource):
    """新浪数据源"""
    name = 'sina'

    def fetch_daily(self, symbol, start_date, end_date):
        # 新浪接口需要 sh/sz 前缀
        bs_code = _to_shsz_prefix(symbol)
        df = ak.stock_zh_a_daily(
            symbol=bs_code, start_date=start_date,
            end_date=end_date, adjust="qfq"
        )
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'date' in col_lower or '日期' in col:
                col_map[col] = '日期'
            elif 'open' in col_lower or '开盘' in col:
                col_map[col] = '开盘'
            elif 'close' in col_lower or '收盘' in col:
                col_map[col] = '收盘'
            elif 'high' in col_lower or '最高' in col:
                col_map[col] = '最高'
            elif 'low' in col_lower or '最低' in col:
                col_map[col] = '最低'
            elif 'volume' in col_lower or '成交量' in col:
                col_map[col] = '成交量'
            elif 'amount' in col_lower or '成交额' in col:
                col_map[col] = '成交额'
        if col_map:
            df = df.rename(columns=col_map)
        return df

    def fetch_minute(self, symbol, start_dt, end_dt):
        # 新浪分钟线需要 sh 前缀
        bs_code = _to_shsz_prefix(symbol)
        df = ak.stock_zh_a_minute(
            symbol=bs_code, period="1"
        )
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'day' in col_lower or '时间' in col or 'date' in col_lower:
                col_map[col] = '时间'
            elif 'open' in col_lower or '开盘' in col:
                col_map[col] = '开盘'
            elif 'close' in col_lower or '收盘' in col:
                col_map[col] = '收盘'
            elif 'high' in col_lower or '最高' in col:
                col_map[col] = '最高'
            elif 'low' in col_lower or '最低' in col:
                col_map[col] = '最低'
            elif 'volume' in col_lower or '成交量' in col:
                col_map[col] = '成交量'
        if col_map:
            df = df.rename(columns=col_map)
        return df

    def fetch_stock_name(self, code):
        try:
            df = ak.stock_zh_a_spot()
            # 新浪返回列名编码可能不同，用位置匹配
            code_col = df.columns[0]  # 代码列
            name_col = df.columns[1]  # 名称列
            bs_code = _to_shsz_prefix(code)
            row = df[df[code_col] == bs_code]
            if not row.empty:
                return row.iloc[0][name_col]
        except Exception:
            pass
        return None


class TencentSource(DataSource):
    """腾讯数据源"""
    name = 'tencent'

    def fetch_daily(self, symbol, start_date, end_date):
        # 腾讯接口需要 sh/sz 前缀
        bs_code = _to_shsz_prefix(symbol)
        df = ak.stock_zh_a_hist_tx(
            symbol=bs_code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq"
        )
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'date' in col_lower or '日期' in col:
                col_map[col] = '日期'
            elif 'open' in col_lower or '开盘' in col:
                col_map[col] = '开盘'
            elif 'close' in col_lower or '收盘' in col:
                col_map[col] = '收盘'
            elif 'high' in col_lower or '最高' in col:
                col_map[col] = '最高'
            elif 'low' in col_lower or '最低' in col:
                col_map[col] = '最低'
            elif 'volume' in col_lower or '成交量' in col:
                col_map[col] = '成交量'
            elif 'amount' in col_lower or '成交额' in col:
                col_map[col] = '成交额'
        if col_map:
            df = df.rename(columns=col_map)
        return df

    def fetch_minute(self, symbol, start_dt, end_dt):
        # 腾讯分钟线接口(stock_zh_a_tick_tx_js)是逐笔数据，非K线，格式不匹配
        return None

    def fetch_stock_name(self, code):
        return None


class BaoStockSource(DataSource):
    """BaoStock 数据源 - 独立服务器，不受东方财富网络限制"""
    name = 'baostock'

    @staticmethod
    def _format_code(code):
        """6位代码转 BaoStock 格式: sz.000001, sh.600000"""
        code = code.zfill(6)
        prefix = 'sh' if code.startswith(('6', '9')) else 'sz'
        return f'{prefix}.{code}'

    def fetch_daily(self, symbol, start_date, end_date):
        import baostock as bs
        bs_code = self._format_code(symbol)
        # start_date/end_date 格式: YYYYMMDD → YYYY-MM-DD
        sd = f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}'
        ed = f'{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}'

        lg = bs.login()
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                'date,open,high,low,close,volume,amount',
                start_date=sd, end_date=ed,
                frequency='d', adjustflag='2'
            )
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=rs.fields)
        df = df.rename(columns={
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量',
            'amount': '成交额',
        })
        # 转换数值类型
        for col in ('开盘', '收盘', '最高', '最低', '成交量', '成交额'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def fetch_minute(self, symbol, start_dt, end_dt):
        import baostock as bs
        bs_code = self._format_code(symbol)
        # start_dt 格式: 'YYYY-MM-DD HH:MM:SS'，提取日期
        date_str = start_dt[:10] if ' ' in start_dt else start_dt
        sd = date_str.replace('-', '')
        ed = end_dt[:10].replace('-', '') if ' ' in end_dt else end_dt.replace('-', '')

        lg = bs.login()
        try:
            # BaoStock 支持5分钟(frequency='5')，不支持1分钟
            rs = bs.query_history_k_data_plus(
                bs_code,
                'date,time,open,high,low,close,volume,amount',
                start_date=date_str, end_date=end_dt[:10] if ' ' in end_dt else end_dt,
                frequency='5', adjustflag='2'
            )
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=rs.fields)
        # BaoStock 时间格式: '20260612093500000'，解析为 datetime
        df['时间'] = pd.to_datetime(df['time'], format='%Y%m%d%H%M%S%f', errors='coerce')
        df = df.rename(columns={
            'open': '开盘', 'high': '最高', 'low': '最低',
            'close': '收盘', 'volume': '成交量', 'amount': '成交额',
        })
        for col in ('开盘', '收盘', '最高', '最低', '成交量', '成交额'):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df

    def fetch_stock_name(self, code):
        import baostock as bs
        bs_code = self._format_code(code)
        lg = bs.login()
        try:
            rs = bs.query_stock_basic(code=bs_code)
            while rs.next():
                row = rs.get_row_data()
                return row[1]  # code_name 字段
        finally:
            bs.logout()
        return None


# 数据源列表（按优先级排序）
DATA_SOURCES = [EastMoneySource(), SinaSource(), BaoStockSource(), TencentSource()]


def _try_sources(method_name, *args, **kwargs):
    """
    依次尝试多个数据源，成功则返回 (source, result)，全部失败返回 None

    Args:
        method_name: 数据源方法名 'fetch_daily' / 'fetch_minute' / 'fetch_stock_name'
    """
    last_error = None
    for attempt, source in enumerate(DATA_SOURCES):
        try:
            method = getattr(source, method_name)
            result = method(*args, **kwargs)
            if result is not None and (not isinstance(result, pd.DataFrame) or not result.empty):
                logger.info(f"数据源 {source.name} 获取 {method_name} 成功")
                return source, result
            logger.debug(f"数据源 {source.name} 返回空数据，尝试下一个")
        except Exception as e:
            last_error = e
            logger.warning(f"数据源 {source.name} 获取 {method_name} 失败: {e}")
        # 指数退避: 1s, 2s, 4s ...
        if attempt < len(DATA_SOURCES) - 1:
            delay = min(2 ** attempt, 4)
            time.sleep(delay)

    logger.error(f"所有数据源均失败，最后错误: {last_error}")
    return None, None


# ============================================================
# 核心业务逻辑
# ============================================================

def is_trading_time(dt=None):
    """判断当前是否在A股交易时段内"""
    if dt is None:
        dt = timezone.now()

    local_time = dt.astimezone(timezone.get_default_timezone())
    hour, minute = local_time.hour, local_time.minute

    # 上午 9:30 - 11:30
    if hour == 9 and minute >= 30:
        return True
    if hour == 10:
        return True
    if hour == 11 and minute <= 30:
        return True

    # 下午 13:00 - 15:00
    if hour == 13:
        return True
    if hour == 14:
        return True
    if hour == 15 and minute == 0:
        return True

    return False


def is_trading_day(date=None):
    """判断是否为交易日（排除周末和节假日），多源备用"""
    if date is None:
        date = timezone.now().date()

    if date.weekday() >= 5:
        return False

    date_str = date.strftime('%Y-%m-%d')

    # 方式1: 新浪交易日历（AkShare）
    try:
        trade_dates = ak.tool_trade_date_hist_sina()
        trade_date_set = set(pd.to_datetime(trade_dates['trade_date']).dt.date)
        return date in trade_date_set
    except Exception as e:
        logger.debug(f"新浪交易日历获取失败: {e}")

    # 方式2: BaoStock 交易日历
    try:
        import baostock as bs
        lg = bs.login()
        try:
            rs = bs.query_trade_dates(
                start_date=date_str, end_date=date_str
            )
            while rs.next():
                row = rs.get_row_data()
                # row[0]=日期, row[1]='1'表示交易日, '0'表示非交易日
                return row[1] == '1'
        finally:
            bs.logout()
    except Exception as e:
        logger.debug(f"BaoStock交易日历获取失败: {e}")

    # 兜底: 仅排除周末
    logger.warning("所有交易日历源不可用，仅排除周末")
    return date.weekday() < 5


def fetch_stock_info(code):
    """获取股票基本信息（名称等），用于添加关注时自动补全"""
    source, name = _try_sources('fetch_stock_name', code)
    if name:
        return name
    return code


def format_symbol(code):
    """格式化股票代码，AkShare 接口通常需要 6 位代码"""
    return code.zfill(6)


def fetch_daily_data(stock, start_date=None, end_date=None):
    """
    获取日K线数据并保存到 DailyQuote 表（多数据源自动切换）

    Args:
        stock: Stock 模型实例
        start_date: 开始日期 'YYYYMMDD'
        end_date: 结束日期 'YYYYMMDD'
    """
    symbol = format_symbol(stock.code)

    if end_date is None:
        end_date = timezone.now().strftime('%Y%m%d')
    if start_date is None:
        start_date = (timezone.now() - timedelta(days=365)).strftime('%Y%m%d')

    source, df = _try_sources('fetch_daily', symbol, start_date, end_date)

    if df is None or df.empty:
        logger.error(f"获取 {stock.code} 日K线失败：所有数据源均不可用")
        return 0

    # 按日期正序排列，以便计算昨收价
    df = df.sort_values(by='日期').reset_index(drop=True)
    # 同时查库获取该股票最早的日K记录之前的最后一条，作为 prev_close 兜底
    first_date = pd.to_datetime(df.iloc[0]['日期']).date() if len(df) > 0 else None
    db_prev_close = None
    if first_date:
        prev_q = DailyQuote.objects.filter(
            stock=stock, trade_date__lt=first_date
        ).order_by('-trade_date').first()
        if prev_q:
            db_prev_close = prev_q.close_price

    prev_close_val = db_prev_close
    count = 0
    for _, row in df.iterrows():
        try:
            trade_date = pd.to_datetime(row['日期']).date()
            open_price = Decimal(str(row['开盘']))
            close_price = Decimal(str(row['收盘']))
            high_price = Decimal(str(row['最高']))
            low_price = Decimal(str(row['最低']))
            volume = int(row['成交量']) if pd.notna(row.get('成交量')) else None
            turnover = (Decimal(str(row['成交额'])) if pd.notna(row.get('成交额'))
                        else None)

            open_close_diff = close_price - open_price
            open_close_pct = open_close_diff / open_price * 100 if open_price else Decimal('0')
            high_low_diff = high_price - low_price
            high_low_pct = high_low_diff / low_price * 100 if low_price else Decimal('0')

            # 相对昨收的涨跌
            prev_close = prev_close_val
            if prev_close is not None:
                change_diff = close_price - prev_close
                change_pct = change_diff / prev_close * 100
            else:
                change_diff = None
                change_pct = None

            daily_quote, created = DailyQuote.objects.update_or_create(
                stock=stock,
                trade_date=trade_date,
                defaults={
                    'open_price': open_price,
                    'close_price': close_price,
                    'high_price': high_price,
                    'low_price': low_price,
                    'open_close_diff': open_close_diff,
                    'open_close_pct': open_close_pct,
                    'high_low_diff': high_low_diff,
                    'high_low_pct': high_low_pct,
                    'prev_close': prev_close,
                    'change_diff': change_diff,
                    'change_pct': change_pct,
                    'volume': volume,
                    'turnover': turnover,
                }
            )
            count += 1
            # 当前条目的收盘价作为下一条的昨收
            prev_close_val = close_price
        except Exception as e:
            logger.warning(f"解析 {stock.code} 日K行数据失败: {e}")
            continue

    logger.info(f"[{source.name}] 获取 {stock.code} 日K线数据 {count} 条")
    return count


def fetch_minute_data(stock, trade_date=None):
    """
    获取1分钟K线数据，推算最高/最低点精确时间（多数据源自动切换）

    Args:
        stock: Stock 模型实例
        trade_date: 交易日期 'YYYY-MM-DD'，默认今天
    """
    symbol = format_symbol(stock.code)

    if trade_date is None:
        trade_date = timezone.now().strftime('%Y-%m-%d')

    start_dt = f"{trade_date} 09:30:00"
    end_dt = f"{trade_date} 15:00:00"

    source, df = _try_sources('fetch_minute', symbol, start_dt, end_dt)

    if df is None or df.empty:
        logger.error(f"获取 {stock.code} 分钟K线失败：所有数据源均不可用")
        return None

    # 保存分钟数据
    for _, row in df.iterrows():
        try:
            dt = pd.to_datetime(row['时间'])
            MinuteBar.objects.update_or_create(
                stock=stock,
                datetime=dt,
                defaults={
                    'open': Decimal(str(row['开盘'])),
                    'close': Decimal(str(row['收盘'])),
                    'high': Decimal(str(row['最高'])),
                    'low': Decimal(str(row['最低'])),
                    'volume': int(row['成交量']) if pd.notna(row.get('成交量')) else 0,
                    'turnover': (Decimal(str(row['成交额']))
                                 if pd.notna(row.get('成交额')) else None),
                }
            )
        except Exception as e:
            logger.warning(f"解析 {stock.code} 分钟数据行失败: {e}")
            continue

    # 推算最高/最低点精确时间
    try:
        high_idx = df['最高'].astype(float).idxmax()
        low_idx = df['最低'].astype(float).idxmin()
        high_time = pd.to_datetime(df.loc[high_idx, '时间'])
        low_time = pd.to_datetime(df.loc[low_idx, '时间'])

        # 更新 DailyQuote 的高低点时间
        date_obj = datetime.strptime(trade_date, '%Y-%m-%d').date()
        try:
            daily_quote = DailyQuote.objects.get(stock=stock, trade_date=date_obj)
            daily_quote.high_time = high_time
            daily_quote.low_time = low_time
            daily_quote.save()
        except DailyQuote.DoesNotExist:
            logger.warning(
                f"{stock.code} {trade_date} 日K线数据不存在，无法更新高低点时间"
            )

        logger.info(
            f"[{source.name}] {stock.code} {trade_date} "
            f"最高点 {df.loc[high_idx, '最高']} @ {high_time}, "
            f"最低点 {df.loc[low_idx, '最低']} @ {low_time}"
        )

        return {
            'high_time': high_time,
            'low_time': low_time,
            'high_price': Decimal(str(df.loc[high_idx, '最高'])),
            'low_price': Decimal(str(df.loc[low_idx, '最低'])),
        }
    except Exception as e:
        logger.error(f"推算 {stock.code} 高低点时间失败: {e}")
        return None


def fetch_stock_all_data(stock, days_back=30):
    """
    完整数据拉取：日K线 + 分钟K线（推算高低点时间）

    Args:
        stock: Stock 模型实例
        days_back: 拉取多少天的历史分钟数据
    """
    daily_count = fetch_daily_data(stock)

    today = timezone.now().date()
    for i in range(min(days_back, 5)):
        date = today - timedelta(days=i)
        if not is_trading_day(date):
            continue
        date_str = date.strftime('%Y-%m-%d')
        fetch_minute_data(stock, trade_date=date_str)
        time.sleep(1)  # 分钟数据请求间隔

    return daily_count


def fetch_all_active_stocks():
    """拉取所有活跃关注股票的数据"""
    stocks = Stock.objects.filter(is_active=True)
    results = []
    for stock in stocks:
        try:
            count = fetch_stock_all_data(stock)
            results.append({'code': stock.code, 'status': 'success', 'count': count})
        except Exception as e:
            logger.error(f"拉取 {stock.code} 数据失败: {e}")
            results.append({'code': stock.code, 'status': 'error', 'message': str(e)})
        time.sleep(2)  # 股票间请求间隔
    return results


def fetch_intraday_update():
    """盘中定时更新：拉取当日分钟数据"""
    if not is_trading_time():
        logger.debug("非交易时段，跳过盘中更新")
        return

    if not is_trading_day():
        logger.debug("非交易日，跳过盘中更新")
        return

    stocks = Stock.objects.filter(is_active=True)
    for stock in stocks:
        try:
            fetch_minute_data(stock)
        except Exception as e:
            logger.error(f"盘中更新 {stock.code} 失败: {e}")
        time.sleep(1)


def fetch_daily_summary():
    """收盘后汇总：拉取当日完整数据并计算"""
    if not is_trading_day():
        logger.debug("非交易日，跳过收盘汇总")
        return

    stocks = Stock.objects.filter(is_active=True)
    for stock in stocks:
        try:
            today_str = timezone.now().strftime('%Y%m%d')
            fetch_daily_data(stock, start_date=today_str, end_date=today_str)
            fetch_minute_data(stock)
        except Exception as e:
            logger.error(f"收盘汇总 {stock.code} 失败: {e}")
        time.sleep(1)


# ============================================================
# 股票搜索
# ============================================================

def _get_stock_list():
    """获取A股全量列表（带缓存）"""
    now = time.time()
    if _stock_list_cache['df'] is not None and now < _stock_list_cache['expires']:
        return _stock_list_cache['df']
    try:
        df = ak.stock_info_a_code_name()
        _stock_list_cache['df'] = df
        _stock_list_cache['expires'] = now + _STOCK_LIST_TTL
        logger.info(f"A股列表缓存刷新，共 {len(df)} 条")
        return df
    except Exception as e:
        logger.error(f"获取A股列表失败: {e}")
        if _stock_list_cache['df'] is not None:
            return _stock_list_cache['df']
        return pd.DataFrame(columns=['code', 'name'])


def search_stocks(keyword, limit=20):
    """
    按代码或名称模糊搜索股票

    Args:
        keyword: 搜索关键词
        limit: 最多返回条数

    Returns:
        list[dict]: [{'code': '000001', 'name': '平安银行'}, ...]
    """
    if not keyword or len(keyword.strip()) < 2:
        return []

    df = _get_stock_list()
    if df.empty:
        return []

    kw = keyword.strip()
    mask = df['name'].str.contains(kw, case=False, na=False) | \
           df['code'].str.contains(kw, case=False, na=False)
    matches = df[mask].head(limit)
    return matches.to_dict('records')
