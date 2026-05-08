#!/usr/bin/env python3
"""Static regression checks for Moon Sniper dashboard UI."""
import json
from html.parser import HTMLParser
from pathlib import Path

HTML = Path('index.html').read_text(encoding='utf-8')
SIGNALS = json.loads(Path('signals.json').read_text(encoding='utf-8'))
SWING_SIGNALS = json.loads(Path('swing_signals.json').read_text(encoding='utf-8'))
SCALP_SIGNALS = json.loads(Path('scalp_signals.json').read_text(encoding='utf-8'))


class DashboardHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.signal_bodies_inside_table = {}
        self.signals_empty_inside_wrap = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append((tag, attrs))

        if tag == 'tbody' and attrs.get('id') in ('signalsBodySwing', 'signalsBodyScalp'):
            body_id = attrs.get('id')
            self.signal_bodies_inside_table[body_id] = any(parent_tag == 'table' for parent_tag, _ in self.stack)

        if tag == 'div' and attrs.get('id') in ('signalsEmptySwing', 'signalsEmptyScalp'):
            empty_id = attrs.get('id')
            self.signals_empty_inside_wrap[empty_id] = any(
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


def test_signal_bodies_stay_inside_tables():
    parser = DashboardHtmlParser()
    parser.feed(HTML)
    for body_id in ('signalsBodySwing', 'signalsBodyScalp'):
        assert parser.signal_bodies_inside_table.get(body_id), f'{body_id} tbody must remain inside its table'
    for empty_id in ('signalsEmptySwing', 'signalsEmptyScalp'):
        assert parser.signals_empty_inside_wrap.get(empty_id), f'{empty_id} should remain inside the table wrapper'


def test_legacy_waiting_message_is_not_visible():
    assert_contains(HTML, '#tab-signals > .emoji,\n  #tab-signals > .emoji + div', 'legacy waiting block must stay hidden if it remains in markup')
    assert_contains(HTML, 'display: none !important', 'legacy waiting block hide rule must be forceful')
    assert_contains(HTML, '還沒有 Swing 訊號', 'empty-state text should not claim the first scan is pending')
    assert_contains(HTML, '還沒有 Scalp 訊號', 'empty-state text should not claim the first scan is pending')


def test_committed_signals_data_has_completed_scan_shape():
    assert SIGNALS.get('total_scanned', 0) > 0, 'signals.json should represent a completed scan, not a first-run placeholder'
    assert isinstance(SIGNALS.get('signals'), list), 'signals.json should include a signals list'


def test_dual_track_signals_json_files_exist_and_parse():
    assert SWING_SIGNALS.get('mode') == 'swing', 'swing_signals.json should identify swing mode'
    assert SCALP_SIGNALS.get('mode') == 'scalp', 'scalp_signals.json should identify scalp mode'
    assert isinstance(SWING_SIGNALS.get('signals'), list), 'swing_signals.json should include a signals list'
    assert isinstance(SCALP_SIGNALS.get('signals'), list), 'scalp_signals.json should include a signals list'
    assert SWING_SIGNALS.get('scanned_at'), 'swing_signals.json should include scanned_at'
    assert SCALP_SIGNALS.get('scanned_at'), 'scalp_signals.json should include scanned_at'


def test_scanner_uses_url_encoding_for_non_ascii_symbols():
    scanner = Path('scanner.py').read_text(encoding='utf-8')
    assert 'from urllib.parse import urlencode' in scanner, 'scanner must URL-encode query params for non-ASCII symbols'
    assert '.isascii()' not in scanner, 'scanner must not exclude Chinese/MEME symbols by character set'


def test_scanner_uses_enough_kline_history_for_filters():
    scanner = Path('scanner.py').read_text(encoding='utf-8')
    assert 'limit=96' in scanner, 'scanner needs >=72 1h klines for 3-day swing consolidation and ADX period=14'


def test_scanner_excludes_modern_stablecoins():
    scanner = Path('scanner.py').read_text(encoding='utf-8')
    for stable in ('RLUSD', 'USD1', 'BFUSD', 'XUSD'):
        assert stable in scanner, f'{stable} should be excluded as stablecoin-like quote asset noise'


def test_scanner_adjusts_partial_kline_volume():
    scanner = Path('scanner.py').read_text(encoding='utf-8')
    assert 'elapsed_frac' in scanner, 'volume ratio should adjust unfinished current kline volume by elapsed time'
    assert 'latest_vol = latest_vol / elapsed_frac' in scanner, 'partial kline volume should be projected to full interval'


def test_scanner_separates_display_candidates_from_trade_eligibility():
    scanner = Path('scanner.py').read_text(encoding='utf-8')
    assert 'filter_reasons' in scanner, 'scanner should explain why a candidate is not trade-eligible'
    assert 'trade_eligible' in scanner, 'scanner should separate display candidates from trade eligibility'
    assert 'dashboard 應顯示候選池' in scanner, 'hard filters should not hide all dashboard candidates'


def test_paper_trading_can_be_paused_and_requires_trade_eligible():
    config = json.loads(Path('config.json').read_text(encoding='utf-8'))
    trader = Path('paper_trader.py').read_text(encoding='utf-8')
    assert config.get('paper_trading', {}).get('enabled') is False, 'paper trading should be paused until project review completes'
    assert 'paper_trading_enabled' in trader, 'paper trader should persist pause status in stats'
    assert 's.get("trade_eligible", False)' in trader, 'paper trader must only trade explicitly eligible signals'


def test_dashboard_shows_total_account_and_reserve():
    assert_contains(HTML, '帳戶總資金 (USDT)', 'stats bar should label total account capital, not allocated-only equity')
    assert_contains(HTML, 'statReserveEquity', 'stats bar should show reserve capital separately')
    assert_contains(HTML, 'const reserveEquity = Math.max(accountBalance - allocatedInitial, 0);', 'reserve should be computed from 300U account minus allocated pools')
    assert_not_contains(HTML, 'totalEquity += pools.swing.pool_equity', 'total account display must not omit reserve by summing pools only')
    assert_not_contains(HTML, 'totalEquity = (swingEquity + scalpEquity) || 300', 'live unrealized updater must not overwrite total capital with allocated pools only')
    assert_contains(HTML, 'const accountEquity = tradesCache?.stats?.total_equity || tradesCache?.stats?.account_balance || 300;', 'live unrealized updater should preserve total account equity including reserve')


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
