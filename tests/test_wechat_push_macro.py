#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信推送 02 栏（全球经济与财经动态）回归测试 —— 旧内容事故的长期防线

2026-09-16 核查结论：02 栏曾把 IMF 7 月 WEO、7 月 29 日 FOMC、8 月 12 日 CPI、
南向 7 月净买入 628.69 亿、各行恒指目标价等**新闻事实写死在源码 f-string 里**，
构建时原样重播，页脚却盖当天时间戳（「24h 内最新可读取内容」），因此长期无人发现。
本文件用断言锁死两件事：

  1. 正文里不得再出现任何写死的历史快讯文本 / 历史兜底行情数字；
  2. 快讯缺失时必须显式降级为「今日未获取」，而不是回填旧文。
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import macro_data as md                       # noqa: E402
import wechat_push as wp                      # noqa: E402

# 曾经写死在推送模板里的历史事实（任何一条重新出现 = 旧文案回归）
STALE_MARKERS = [
    '628.69',                                  # 南向 7 月净买入 628.69 亿港元
    'IMF 更新的《世界经济展望》',
    '9-3 维持联邦基金利率',
    '8 月 12 日',
    '五连阳冲击 26,000',
    '杰克逊霍尔',
    '25,440.17',                               # 写死的恒指点位兜底
    '跌 212.65 点',
    '4,776.44',
    '24h 内最新可读取内容',
]


def _render(env):
    """在指定数据文件环境下渲染单页推送（屏蔽各源日志）。"""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            html, _ts, _tsf = wp.build_single_wechat_html()
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    return html


def _no_data_env(tmpdir):
    """把行情/社区/舆情三类数据都指向不存在的文件，让渲染路径确定（不受本地残留 json 影响）。"""
    missing = os.path.join(tmpdir, 'missing.json')
    return {'MARKET_DATA': missing, 'COMMUNITY_DATA': missing, 'SENTIMENT_DATA': missing,
            'MACRO_DATA': missing}


class TestMacroSection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_no_hardcoded_history_anywhere(self):
        """快讯未获取时的渲染（最坏情况）也不得出现历史写死文案。"""
        html = _render(_no_data_env(self._tmp.name))
        for bad in STALE_MARKERS:
            self.assertNotIn(bad, html, f'推送正文重新出现写死的历史内容: {bad}')

    def test_missing_macro_degrades_with_explicit_notice(self):
        html = _render(_no_data_env(self._tmp.name))
        self.assertIn('宏观快讯 — 今日未获取', html)
        self.assertIn('macro_data.py', html, '降级提示要直接给出恢复命令')
        self.assertIn('不再回填历史叙事', html)
        self.assertIn('行情未获取', html, '行情缺失应直说，而不是显示兜底点位')

    def test_macro_items_are_rendered_with_publish_dates(self):
        data = md.build(mock=True, quiet=True)
        path = os.path.join(self._tmp.name, 'macro_data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        env = _no_data_env(self._tmp.name)
        env['MACRO_DATA'] = path
        html = _render(env)

        titles = [(blk.get('items') or [{}])[0].get('title')
                  for blk in data['categories'].values() if blk.get('items')]
        self.assertGreaterEqual(len(titles), 3, 'mock 回放应至少覆盖 3 个小节')
        for t in titles:
            self.assertIn(wp.re.sub(r'\s+', ' ', t)[:20], wp.re.sub(r'<[^>]+>', ' ', html),
                          f'当次抓到的快讯应渲染进 02 栏: {t}')
        plain = wp.re.sub(r'<[^>]+>', ' ', html)
        self.assertIn('时效窗口', plain)
        self.assertIn('不显示数据来源', plain, '对外沿用舆情层同一脱敏口径')
        self.assertTrue(re.search(r'\[\d{1,2} 月 \d{1,2} 日\]', plain),
                        '每条快讯应自带发布日期，读者才能自行判断时效')
        for bad in STALE_MARKERS:
            self.assertNotIn(bad, html)

    def test_03_overview_counts_are_derived_not_hardcoded(self):
        """社区多空家数必须由当次社区数据推导（此前写死「偏多 6 家」）。"""
        path = os.path.join(self._tmp.name, 'community_data.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'fetch_date': '2026-09-16', 'communities': [
                {'key': 'FUTU', 'id': '01', 'name': '甲', 'icon': '🐮', 'verdict_label': '偏多',
                 'verdict_class': 'bull', 'quote': 'q1', 'verdict': 'v1', 'meta': '综合站内 10 条讨论 · 最新读取 2026-09-16'},
                {'key': 'XUEQIU', 'id': '02', 'name': '乙', 'icon': '❄️', 'verdict_label': '偏空',
                 'verdict_class': 'bear', 'quote': 'q2', 'verdict': 'v2', 'meta': '综合站内 10 条讨论 · 最新读取 2026-09-16'},
                {'key': 'LAOHU', 'id': '03', 'name': '丙', 'icon': '🐯', 'verdict_label': '中性',
                 'verdict_class': 'neutral', 'quote': 'q3', 'verdict': 'v3', 'meta': '综合站内 10 条讨论 · 最新读取 2026-09-16'},
            ]}, f, ensure_ascii=False)
        env = _no_data_env(self._tmp.name)
        env['COMMUNITY_DATA'] = path
        html = wp.re.sub(r'<[^>]+>', ' ', _render(env))
        m = re.search(r'偏多 (\d+) 家 · <.*?>?偏空 (\d+) 家', html)
        self.assertIn('偏多 1 家', html)
        self.assertIn('偏空 1 家', html)
        self.assertIn('中性 1 家', html)
        self.assertIn('3 个境内外核心社区信号', html, '小节标题的源数应随实际社区数变化')
        self.assertNotIn('8 月初五连阳', html)


if __name__ == '__main__':
    unittest.main()
