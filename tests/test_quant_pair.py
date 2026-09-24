#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 量化 · 配对交易回归：策略选择、两标的组合、当次行情推荐、网页/微信都挂在内容后面。"""
import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import build_site as bs          # noqa: E402
import panorama                  # noqa: E402
import quant_pair                # noqa: E402
import wechat_push as wp         # noqa: E402

STALE = ['628.69', '25,440.17', '4,776.44', '8 月 12 日', '杰克逊霍尔']


def _quotes(**pcts):
    return {'quotes': {k: {'name': quant_pair.NAMES.get(k, k), 'pct': v} for k, v in pcts.items()}}


class TestPairEngine(unittest.TestCase):
    def test_always_two_distinct_legs(self):
        rec = quant_pair.recommend('没有主题的一段话', {})
        self.assertNotEqual(rec['leg_a']['key'], rec['leg_b']['key'])
        self.assertEqual(rec['family'], '配对交易')
        self.assertIn('/', rec['pair_label'])

    def test_missing_quotes_do_not_invent_a_direction(self):
        rec = quant_pair.recommend('原油与布伦特', {})
        self.assertEqual(rec['action'], 'no_data')
        self.assertEqual(rec['stance'], '数据不足')
        self.assertNotIn('%', rec['signal'])
        blob = rec['recommendation'] + rec['signal'] + rec['why']
        for bad in STALE:
            self.assertNotIn(bad, blob)

    def test_theme_picks_the_pair_and_quote_picks_the_side(self):
        quotes = _quotes(HSTECH=0.2, HSI=0.1, WTI=2.4, BRENT=0.2, GOLD=0.1, USDCNH=0.0)
        oil = quant_pair.recommend('富途在讨论原油、WTI 与布伦特价差', quotes, hint='FUTU')
        self.assertEqual(oil['strategy_id'], 'oil_curve')
        self.assertEqual((oil['leg_a']['key'], oil['leg_b']['key']), ('WTI', 'BRENT'))
        self.assertEqual(oil['action'], 'short_a_long_b')
        self.assertIn('做空', oil['stance'])
        self.assertIn('做多', oil['stance'])

        weak = quant_pair.recommend('恒生科技相对恒指', _quotes(HSTECH=-1.6, HSI=0.4), hint='rotation')
        self.assertEqual(weak['strategy_id'], 'hk_growth_value')
        self.assertEqual(weak['action'], 'long_a_short_b')

    def test_small_spread_is_a_wait(self):
        rec = quant_pair.recommend('恒生科技', _quotes(HSTECH=0.05, HSI=0.04), hint='hk_growth_value')
        self.assertEqual(rec['action'], 'wait')
        self.assertEqual(rec['stance'], '观望')
        self.assertIn('不建配对仓', rec['recommendation'])

    def test_renders_name_the_strategy_the_pair_and_the_call(self):
        rec = quant_pair.recommend('美联储利率与黄金', _quotes(GOLD=1.2, USDCNH=-0.3), hint='fed')
        self.assertEqual(rec['strategy_id'], 'gold_fx')
        for blob in (quant_pair.render_web(rec), quant_pair.render_wechat(rec),
                     quant_pair.render_web(rec, compact=True),
                     quant_pair.render_wechat(rec, compact=True)):
            self.assertIn('AI 量化', blob)
            self.assertIn('标的组合', blob)
            self.assertIn(rec['strategy_name'], blob)
            self.assertIn('推荐', blob)
        self.assertIn('data-ai-quant="1"', quant_pair.render_web(rec))


class TestAttachedAfterContent(unittest.TestCase):
    def test_each_community_card_gets_a_block(self):
        communities = [
            {'id': '01', 'key': 'FUTU', 'icon': '🐮', 'name': '富途牛牛社区',
             'verdict_label': '偏多', 'verdict_class': 'bull',
             'quote': '讨论原油与布伦特', 'verdict': '观望', 'meta': '最新读取 2026-09-24'},
            {'id': '02', 'key': 'WALLSTREETCN', 'icon': '🌐', 'name': '华尔街见闻社区',
             'verdict_label': '中性', 'verdict_class': 'neutral',
             'quote': '美联储利率与黄金', 'verdict': '防守', 'meta': '最新读取 2026-09-24'},
        ]
        html = bs.build_community_html(communities, market=_quotes(WTI=1.5, BRENT=0.2, GOLD=0.8, USDCNH=-0.2))
        self.assertEqual(html.count('class="ai-quant"'), 2)
        self.assertIn('两油价差配对', html)
        self.assertIn('黄金与离岸流动性配对', html)
        self.assertIn('标的组合', html)

    def test_panorama_force_cards_carry_the_block(self):
        market = {'fetch_date': '2026-09-17', 'quotes': {
            'HSI': {'name': '恒生指数', 'last': 26000, 'prev_close': 25700, 'pct': 1.2, 'as_of': '2026-09-17'},
            'HSTECH': {'name': '恒生科技指数', 'pct': 2.4, 'as_of': '2026-09-17'},
            'SPX': {'name': '标普 500', 'pct': 0.4, 'as_of': '2026-09-16'},
            'NDQ': {'name': '纳斯达克', 'pct': 0.8, 'as_of': '2026-09-16'},
            'DJI': {'name': '道琼斯', 'pct': 0.2, 'as_of': '2026-09-16'},
            'WTI': {'name': 'WTI 原油', 'pct': 1.5, 'as_of': '2026-09-16'},
            'BRENT': {'name': '布伦特原油', 'pct': 0.4, 'as_of': '2026-09-16'},
        }}
        d = panorama.scan(market=market)
        self.assertTrue(d['forces'])
        self.assertTrue(all(f.get('ai_quant') for f in d['forces']))
        self.assertEqual(len(d['forces'][0]['ai_quant']['pair_label'].split(' / ')), 2)
        web = panorama.render_web(d)
        wx = panorama.render_wechat(d)
        self.assertGreaterEqual(web.count('AI 量化'), len(d['forces']))
        self.assertGreaterEqual(wx.count('AI 量化'), len(d['forces']))
        for bad in STALE:
            self.assertNotIn(bad, web)
            self.assertNotIn(bad, wx)

    def test_macro_items_and_quote_marker_get_a_block(self):
        import macro_data as md
        data = md.build(mock=True, quiet=True)
        html = bs.build_macro_html(data, market=_quotes(WTI=1.2, BRENT=0.1, HSI=-0.4, HSCE=0.2))
        self.assertGreaterEqual(html.count('AI 量化'), 3)
        self.assertIn('标的组合', html)
        for bad in STALE:
            self.assertNotIn(bad, html)
        tpl = '<div><!-- AI_QUANT:QUOTES --></div><!-- AI_QUANT:VERDICT -->'
        filled = bs.fill_ai_quant_markers(tpl, market=_quotes(HSI=0.2, HSCE=-0.8))
        self.assertNotIn('AI_QUANT:', filled)
        self.assertGreaterEqual(filled.count('AI 量化'), 2)

    def test_wechat_fallback_puts_one_block_on_every_community(self):
        missing = os.path.join(REPO_ROOT, 'tests', 'fixtures', 'no-such-quant.json')
        saved = {}
        keys = ('MARKET_DATA', 'COMMUNITY_DATA', 'SENTIMENT_DATA', 'MACRO_DATA', 'MACRO_AUTO_FETCH')
        for k in keys:
            saved[k] = os.environ.get(k)
        os.environ.update({k: missing for k in keys[:4]})
        os.environ['MACRO_AUTO_FETCH'] = '0'
        try:
            html, _ts, _tsf = wp.build_single_wechat_html()
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertGreaterEqual(html.count('AI 量化'), 14, '14 个社区卡片各自要有一块 AI 量化')
        self.assertIn('标的组合', html)
        self.assertIn('配对交易', html)
        self.assertLess(len(html), 95000)
        for bad in STALE:
            self.assertNotIn(bad, html)


if __name__ == '__main__':
    unittest.main()
