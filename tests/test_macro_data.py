#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_data.py 单元测试（离线 · 纯标准库 unittest，CI 用 `python3 -m unittest discover -s tests`）

覆盖 2026-09-16 修复的核心语义：微信推送 02 栏改为快讯数据驱动后，
「旧内容」必须在**数据层**就被挡住 —— 超窗、无日期、跨源转载重复，都不允许进入正文。
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import macro_data as md                                       # noqa: E402

NOW = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)

RSS_SAMPLE = '''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Google News</title>
  <item>
    <title><![CDATA[美联储 9 月议息维持利率不变 — 彭博社]]></title>
    <link>https://news.example.com/a1</link>
    <pubDate>Wed, 16 Sep 2026 08:00:00 GMT</pubDate>
    <description>决议声明删除进一步紧缩倾向。</description>
    <source>Bloomberg</source>
  </item>
  <item>
    <title>恒指收涨 182 点 南向资金连续三日净流入</title>
    <guid isPermaLink="true">https://news.example.com/a2</guid>
    <pubDate>Tue, 15 Sep 2026 09:30:00 GMT</pubDate>
  </item>
  <item><title><![CDATA[]]></title></item>
</channel></rss>'''


class TestParsers(unittest.TestCase):
    def test_parse_rss_title_link_date_publisher(self):
        rows = md.parse_rss(RSS_SAMPLE)
        self.assertEqual(len(rows), 2, '空标题条目应被丢弃')
        self.assertEqual(rows[0]['url'], 'https://news.example.com/a1')
        self.assertEqual(rows[0]['publisher'], 'Bloomberg')
        self.assertEqual(md.to_utc(rows[0]['published_raw']).strftime('%Y-%m-%d'), '2026-09-16')
        self.assertEqual(rows[1]['url'], 'https://news.example.com/a2', '无 link 时应回退 guid')
        self.assertEqual(rows[1]['summary'], '')

    def test_parse_rss_broken_input_is_safe(self):
        self.assertEqual(md.parse_rss(''), [])
        self.assertEqual(md.parse_rss('<rss><not closed'), [])

    def test_strip_gnews_title_suffix(self):
        t, p = md.split_gnews_title('恒指收涨 182 点 — 智通财经')
        self.assertEqual((t, p), ('恒指收涨 182 点', '智通财经'))
        self.assertEqual(md.split_gnews_title('无来源标题')[1], '')

    def test_to_utc_accepts_iso_and_bare_date(self):
        self.assertEqual(md.to_utc('2026-09-16T08:00:00+00:00').strftime('%Y-%m-%d %H:%M'),
                         '2026-09-16 08:00')
        self.assertEqual(md.to_utc('2026-09-15 07:58:00').strftime('%Y-%m-%d'), '2026-09-15')
        self.assertIsNone(md.to_utc('昨天'))
        self.assertIsNone(md.to_utc(''))

    def test_strip_jsonp_and_parse_em(self):
        payload = md.strip_jsonp('jQuery_macro({"result":{"cmsArticleWebOld":[{"title":"港股<em>通</em>净买入 412 亿",'
                                '"date":"2026-09-15 17:30:00","content":"高股息仍是主力","url":"http://x.y/z",'
                                '"mediaName":"东财"}]}});')
        rows = md.parse_em_search(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], '港股通净买入 412 亿')
        self.assertEqual(rows[0]['publisher'], '东财')


    def test_strip_html_keeps_words_whole(self):
        """行内高亮标签不得在中文标题里留下空格碎词。"""
        self.assertEqual(md.strip_html('港股<em>通</em>净买入 412 亿'), '港股通净买入 412 亿')
        self.assertEqual(md.strip_html('第一行<br/>第二行'), '第一行 第二行')
        self.assertEqual(md.strip_html('A &amp; B &#39;c&#39;'), "A & B 'c'")
        self.assertEqual(md.strip_html(''), '')


class TestClassify(unittest.TestCase):
    def test_imf_headline_goes_to_macro_not_commodities(self):
        """关键词加权回归：一条 IMF 新闻提到关税/航运时不能被大宗商品小节抢走。"""
        it = {'title': 'IMF 下调 2026 年全球经济增速预期至 3.1% 关税与地缘风险拖累贸易量',
              'snippet': '基金组织称关税壁垒与霍尔木兹航运风险是主要下行风险。'}
        cat, hits = md.classify(it)
        self.assertEqual(cat, 'macro')
        self.assertIn('imf', hits)

    def test_bank_target_needs_hk_context(self):
        ok = {'title': '星展银行上调恒指目标价至 31,500 点', 'snippet': ''}
        self.assertEqual(md.classify(ok)[0], 'bank_views')
        # 无恒指/港股语境的 A 股目标价不得混进港股小节
        no = {'title': '某券商上调宁德时代目标价', 'snippet': ''}
        self.assertNotEqual(md.classify(no)[0], 'bank_views')

    def test_unrelated_is_misc(self):
        self.assertEqual(md.classify({'title': '某新能源车企发布固态电池', 'snippet': ''})[0], 'misc')


class TestStalenessAndDedup(unittest.TestCase):
    def _item(self, title, days_ago=1, dated=True):
        d = NOW - timedelta(days=days_ago)
        return {'title': title, 'snippet': '', 'url': '',
                'published_date': d.strftime('%Y-%m-%d') if dated else None,
                'published_at': d.isoformat() if dated else None,
                'age_days': float(days_ago) if dated else None}

    def test_stale_and_undated_are_dropped(self):
        items = [self._item('今天的快讯', 0), self._item('八年前的旧闻', 3000),
                 self._item('没有日期', dated=False)]
        kept, dropped = md.filter_stale(items, max_age_days=7, now=NOW)
        self.assertEqual([i['title'] for i in kept], ['今天的快讯'])
        self.assertEqual(dropped, {'undated_dropped': 1, 'stale_dropped': 1})

    def test_future_dated_beyond_clock_is_dropped(self):
        """发布日期在将来（源侧时区/伪造数据）不应被当成头条。"""
        items = [{'title': '来自未来', 'published_date': (NOW + timedelta(days=5)).strftime('%Y-%m-%d'),
                  'age_days': -5.0}]
        kept, dropped = md.filter_stale(items, max_age_days=7, now=NOW)
        self.assertEqual(kept, [])
        self.assertEqual(dropped['stale_dropped'], 1)

    def test_dedup_collapses_publisher_suffix_versions(self):
        """同一稿件在 8 个源下标题可能带/不带「— 来源」后缀，必须只留一条。"""
        raw = [{'title': '恒指收涨 182 点 — 智通财经', 'url': 'u1', 'published_raw': '2026-09-16 08:00:00'},
               {'title': '恒指收涨 182 点', 'url': 'u2', 'published_raw': '2026-09-16 08:00:00'}]
        a = md.normalize(raw, 'GN_ZH_HK', now=NOW)
        b = md.normalize(raw, 'EM_SEARCH', now=NOW)
        self.assertEqual({i['title'] for i in a + b}, {'恒指收涨 182 点'},
                         '「标题 — 来源」后缀必须在入库时统一剥离')
        self.assertEqual({i['publisher'] for i in a if i['publisher']}, {'智通财经'})
        self.assertEqual(len(md.dedup(a + b)), 1, '同一稿件跨源只应保留一条')

    def test_rank_limits_and_sorts_per_category(self):
        items = [{**self._item('美联储 9 月议息维持利率不变 A', 3), 'snippet': 'FOMC 声明'},
                 {**self._item('美联储 9 月议息维持利率不变 B', 1), 'snippet': 'FOMC 声明'},
                 {**self._item('CPI 通胀回落', 2), 'snippet': ''},
                 {**self._item('无关新闻', 1), 'snippet': ''}]
        buckets, misc = md.rank(items, limit=2)
        self.assertEqual(len(buckets['fed']), 2)
        self.assertEqual(buckets['fed'][0]['title'], '美联储 9 月议息维持利率不变 B',
                         '关键词同分时更鲜的一条应排在前面（02 栏只取前 N 条，顺序即取舍）')
        self.assertEqual(len(misc), 1)


class TestBuildOffline(unittest.TestCase):
    def test_build_mock_output_contract(self):
        """--mock 回放必须满足推送端依赖的字段契约（wechat_push 直接读这些 key）。"""
        data = md.build(mock=True, quiet=True)
        self.assertEqual(data['mode'], 'mock')
        self.assertEqual(data['summary']['ok'], data['summary']['total'])
        self.assertGreater(data['summary']['kept_items'], 0)
        self.assertIn('macro', data['categories'])
        for key, blk in data['categories'].items():
            self.assertIn('label', blk)
            for it in blk['items']:
                self.assertRegex(it['published_date'], r'^20\d{2}-\d{2}-\d{2}$')
                self.assertLessEqual(it['age_days'], data['window']['max_age_days'])
                self.assertEqual(it['category'], key)
        self.assertIn('发布日期', data['notes'][0], 'notes 应说明时效口径（发布日期可解析才入库）')

    def test_window_shrinks_kept_items(self):
        """收紧时效窗口只会减少条目 —— 证明窗口参数真正作用于正文。"""
        wide = md.build(max_age_days=30, mock=True, quiet=True)['summary']['kept_items']
        tight = md.build(max_age_days=1, mock=True, quiet=True)
        self.assertLessEqual(tight['summary']['kept_items'], wide)
        for blk in tight['categories'].values():
            for it in blk['items']:
                self.assertLessEqual(it['age_days'], 1.0 + 1e-6)

    def test_text_report_mentions_empty_sections(self):
        data = {'summary': {'ok': 0, 'total': 8, 'raw_items': 0, 'unique_items': 0,
                            'kept_items': 0, 'stale_dropped': 0, 'undated_dropped': 0},
                'window': {'max_age_days': 7, 'since': '2026-09-09'},
                'categories': {c['key']: {'label': c['label'], 'items': []} for c in md.CATEGORIES},
                'sources': [{'id': 'GN_ZH_HK', 'ok': False, 'error': 'URLError: blocked'}]}
        txt = md.text_report(data)
        self.assertIn('窗口内无匹配快讯', txt)
        self.assertIn('GN_ZH_HK 失败', txt)


if __name__ == '__main__':
    unittest.main()
