"""列表排序与分页（板块、ETF 雷达共用）。"""

from __future__ import annotations


def _sort_items(items, field, order):
    """数值字段排序；同值使用代码/名称兜底，保证分页结果稳定。"""
    present = [item for item in items if item.get(field) is not None]
    missing = [item for item in items if item.get(field) is None]

    def tie_key(item):
        return str(item.get('code') or item.get('name') or '')

    present.sort(key=tie_key)
    present.sort(key=lambda item: item[field], reverse=order == 'desc')
    missing.sort(key=tie_key)
    return present + missing


def _paginate(items, page, page_size):
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    start = (page - 1) * page_size
    return items[start:start + page_size], {
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
    }
