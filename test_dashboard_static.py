#!/usr/bin/env python3
"""Static regression checks for Moon Sniper dashboard UI."""
import json
from html.parser import HTMLParser
from pathlib import Path

HTML = Path('index.html').read_text(encoding='utf-8')
SIGNALS = json.loads(Path('signals.json').read_text(encoding='utf-8'))


class DashboardHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.signals_body_inside_table = False
        self.signals_table_depth = None
        self.signals_empty_inside_wrap = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append((tag, attrs))

        if tag == 'tbody' and attrs.get('id') == 'signalsBody':
            self.signals_body_inside_table = any(parent_tag == 'table' for parent_tag, _ in self.stack)
            for idx in range(len(self.stack) - 1, -1, -1):
                if self.stack[idx][0] == 'table':
                    self.signals_table_depth = idx
                    break

        if tag == 'div' and attrs.get('id') == 'signalsEmpty':
            self.signals_empty_inside_wrap = any(
                parent_tag == 'div' and 'table-wrap' in parent_attrs.get('class', '').split()
                for parent_tag, parent_attrs in self.stack
            )

    def handle_endtag(self, tag):
        while self.stack:
            open_tag, _ = self.stack.pop()
            if open_tag == tag:
                break


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
    assert_contains(HTML, 'left: 0', 'sticky symbol column must pin to the left edge')
    assert_contains(HTML, 'class="sticky-symbol"', 'symbol header/cells must use sticky-symbol class')
    assert_not_contains(HTML, 'overflow: hidden;\n    border: 1px solid var(--border);', 'table overflow hidden can break sticky columns on mobile')


def test_signal_headers_are_sortable():
    assert_contains(HTML, 'sortSignals(', 'headers should call sortSignals')
    assert_contains(HTML, 'data-sort=', 'sortable headers should declare data-sort keys')
    assert_contains(HTML, 'sortState', 'sorting state should be tracked')


def test_signals_tbody_stays_inside_table():
    parser = DashboardHtmlParser()
    parser.feed(HTML)
    assert parser.signals_body_inside_table, 'signalsBody tbody must remain inside its table'
    assert parser.signals_empty_inside_wrap, 'signalsEmpty should remain inside the table wrapper'


def test_legacy_waiting_message_is_not_visible():
    assert_contains(HTML, '#tab-signals > .emoji,\n  #tab-signals > .emoji + div', 'legacy waiting block must stay hidden if it remains in markup')
    assert_contains(HTML, 'display: none !important', 'legacy waiting block hide rule must be forceful')
    assert_contains(HTML, "empty.textContent = 'No current signals.';", 'empty-state text should not claim the first scan is pending')


def test_committed_signals_data_has_completed_scan_shape():
    assert SIGNALS.get('total_scanned', 0) > 0, 'signals.json should represent a completed scan, not a first-run placeholder'
    assert isinstance(SIGNALS.get('signals'), list), 'signals.json should include a signals list'


def test_mobile_allows_page_scroll_and_pull_refresh():
    assert_contains(HTML, 'overflow-y: auto', 'page must allow vertical scrolling for mobile/pull refresh')
    assert_not_contains(HTML, 'html, body { height: 100%; overflow: hidden; }', 'global overflow hidden blocks mobile pull-to-refresh')
    assert_contains(HTML, '@media (max-width: 768px)', 'mobile CSS block should exist')
    assert_contains(HTML, '-webkit-overflow-scrolling: touch', 'mobile scrolling should be momentum/touch friendly')


def test_trade_cards_are_compact():
    assert_contains(HTML, 'padding: 8px 10px;', 'trade cards should use compact padding')
    assert_contains(HTML, '.trade-item .trade-symbol {\n    font-weight: 700;\n    font-size: 14px;', 'trade symbol font should be compact')
    assert_contains(HTML, 'font-size:15px;font-weight:700', 'trade PnL font should be smaller than before')
    assert_contains(HTML, 'trade-meta-grid', 'trade card details should use compact grid layout')


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
    print('dashboard static checks passed')
