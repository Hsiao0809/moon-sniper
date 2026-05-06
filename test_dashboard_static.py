#!/usr/bin/env python3
"""Static regression checks for Moon Sniper dashboard UI."""
from pathlib import Path

HTML = Path('index.html').read_text(encoding='utf-8')


def assert_contains(text, needle, message):
    if needle not in text:
        raise AssertionError(message)


def assert_not_contains(text, needle, message):
    if needle in text:
        raise AssertionError(message)


def test_stats_bar_does_not_show_max_drawdown():
    assert_not_contains(HTML, 'statMaxDD', 'stats bar should not include max drawdown card')
    assert_not_contains(HTML, '最大回撤 (USDT)', 'stats bar should not display max drawdown')


def test_symbol_column_is_sticky():
    assert_contains(HTML, '.sticky-symbol', 'symbol column needs sticky CSS class')
    assert_contains(HTML, 'position: sticky', 'sticky symbol column must use position: sticky')
    assert_contains(HTML, 'class="sticky-symbol"', 'symbol header/cells must use sticky-symbol class')


def test_signal_headers_are_sortable():
    assert_contains(HTML, 'sortSignals(', 'headers should call sortSignals')
    assert_contains(HTML, 'data-sort=', 'sortable headers should declare data-sort keys')
    assert_contains(HTML, 'sortState', 'sorting state should be tracked')


def test_mobile_allows_page_scroll_and_pull_refresh():
    assert_contains(HTML, 'overflow-y: auto', 'page must allow vertical scrolling for mobile/pull refresh')
    assert_not_contains(HTML, 'html, body { height: 100%; overflow: hidden; }', 'global overflow hidden blocks mobile pull-to-refresh')
    assert_contains(HTML, '@media (max-width: 768px)', 'mobile CSS block should exist')
    assert_contains(HTML, '-webkit-overflow-scrolling: touch', 'mobile scrolling should be momentum/touch friendly')


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
    print('dashboard static checks passed')
