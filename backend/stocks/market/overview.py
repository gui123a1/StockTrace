"""聚合入口：行情总览、指数走势与收盘后缓存预热。"""

from __future__ import annotations

import logging
import time

from ._cache import _now_str
from ._sources import get_source_health
from .etf import _fetch_etf_spot_df, get_etf_share_radar, get_national_team_etfs
from .flows import fetch_hsgt_flow, fetch_market_activity, fetch_market_fund_flow_hist
from .indices import fetch_index_trend, fetch_major_indices
from .sectors import _sector_payload, fetch_concept_fund_flow

logger = logging.getLogger(__name__)


def get_market_overview():
    """数据首页：指数 + 资金情绪摘要（不拉重型 ETF 全表）。"""
    indices = fetch_major_indices()
    hsgt = fetch_hsgt_flow()
    activity = fetch_market_activity()
    fund_hist = fetch_market_fund_flow_hist(days=30)
    concept_items = fetch_concept_fund_flow()
    concept = _sector_payload(concept_items, 'concept', page=1, page_size=8)

    north_net = 0.0
    north_has = False
    for row in hsgt:
        if row.get('direction') == '北向' and row.get('net_buy') is not None:
            north_net += row['net_buy']
            north_has = True

    return {
        'updated_at': _now_str(),
        'indices': indices,
        'fund': {
            'hsgt': hsgt,
            'northbound_net_buy': north_net if north_has else None,
            'activity': activity,
            'main_hist': fund_hist,
            'concept': concept,
        },
        'modules': [
            {
                'key': 'trend',
                'title': '全市场走势',
                'desc': '上证/深成/创业板/沪深300/科创50 归一化对比',
                'path': '/market/trend',
            },
            {
                'key': 'sectors',
                'title': '板块资金轮动',
                'desc': '行业与概念资金净流入/流出排行',
                'path': '/market/sectors',
            },
            {
                'key': 'institutions',
                'title': '机构持仓',
                'desc': '国内外机构持股变化、北向资金与个股机构明细',
                'path': '/market/institutions',
            },
            {
                'key': 'national-etf',
                'title': '国家队相关 ETF 观察',
                'desc': '宽基与政策相关 ETF 观察名单（非官方持仓）',
                'path': '/market/national-etf',
            },
            {
                'key': 'etf-radar',
                'title': 'ETF 份额雷达',
                'desc': '份额规模、主力净流入/流出与涨跌榜',
                'path': '/market/etf-radar',
            },
        ],
        'sources_health': get_source_health(),
    }


def get_market_trend():
    return {
        'updated_at': _now_str(),
        **fetch_index_trend(days=120),
    }


def warm_post_close_lagging():
    """
    收盘后降频预热：只刷新可能晚到的行情缓存。
    不写自选 SQLite，不拉已冻结的指数现价/涨跌家数/板块当日排名/机构季报。
    """
    started = time.time()
    logger.info("收盘后晚到数据预热开始")

    try:
        fetch_hsgt_flow(force=True)
    except Exception as e:
        logger.error(f"预热北向资金失败: {e}")
    time.sleep(0.8)

    try:
        fetch_market_fund_flow_hist(days=30, force=True)
    except Exception as e:
        logger.error(f"预热大盘资金历史失败: {e}")
    time.sleep(0.8)

    try:
        # force 一次 ETF 现货表，再重建两个派生缓存
        _fetch_etf_spot_df(force=True)
        get_national_team_etfs(force=True)
        get_etf_share_radar(force=True)
    except Exception as e:
        logger.error(f"预热 ETF 份额/雷达失败: {e}")

    logger.info(f"收盘后晚到数据预热结束，耗时 {time.time() - started:.1f}s")
