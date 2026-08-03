#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
章鱼 AI 全景分析 — 微信推送工具

将 report.html 转换为微信(PushPlus html 模板)兼容的内联样式 HTML,
生成 wechat.json 供网页按钮使用,并可直接推送至 PushPlus。

用法:
  python3 tools/wechat_push.py --emit _site/wechat.json     # 只生成微信版 JSON
  python3 tools/wechat_push.py --embed                       # 把推送内容内嵌进 report.html
  python3 tools/wechat_push.py --push                        # 直接推送到微信

Token 解析顺序: --token 参数 > 环境变量 PUSHPLUS_TOKEN > report.html 内的 PUSHPLUS_TOKEN 常量
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_HTML = os.path.join(REPO_ROOT, 'report.html')
PAGES_URL = 'https://k-macao.github.io/03/'
PUSH_URL = 'https://www.pushplus.plus/send'
TITLE = '章鱼 AI 全景分析'
CONTENT_LIMIT = 20000
# 留出安全余量,避免 PushPlus 按字节/字符口径不同导致超限
CONTENT_SAFE_LIMIT = 19000

# 歸藏风格主题 · 🌊 靛蓝瓷:与 report.html 的 :root 变量保持一致
INK = '#0a1f3d'        # 深靛墨色
PAPER = '#f1f3f5'      # 瓷白纸面
PAPER_TINT = '#e4e8ec'  # 瓷白深一档(swiss-box)
CARD = '#f8fafc'        # 卡片底
GREY_MID = '#bfc9d4'
GREY_DEEP = '#7c8797'
ACCENT = '#d7263d'     # 唯一重点色:朱砂红

# class 名 -> 内联样式(贴近原版 Swiss/Editorial 视觉效果,已按微信体积压缩)
CLASS_STYLE = {
    'grid': '',
    'hero': 'border-top:3px solid %s;border-bottom:1px solid %s;padding:20px 0 14px 0;' % (INK, INK),
    'sub': 'display:block;font-weight:300;font-size:15px;letter-spacing:2px;color:%s;margin-top:6px;' % GREY_DEEP,
    'meta-strip': 'padding:10px 0 14px 0;font-size:12px;color:%s;border-bottom:1px solid %s;margin-bottom:18px;line-height:2;' % (GREY_DEEP, INK),
    'section-title': 'font-size:19px;font-weight:900;margin:30px 0 14px 0;padding-left:12px;border-left:6px solid %s;' % INK,
    'sub-head': 'font-weight:700;font-size:14px;color:%s;margin:22px 0 8px 0;padding-bottom:5px;border-bottom:1px solid %s;' % (GREY_DEEP, GREY_MID),
    'swiss-box': 'background:%s;border-left:4px solid %s;padding:12px 14px;margin:16px 0;' % (PAPER_TINT, INK),
    'comment-card': 'background:%s;border:1px solid %s;border-left:8px solid %s;padding:10px 12px;margin:10px 0;' % (CARD, INK, INK),
    'c-user': 'font-weight:800;font-size:13px;',
    'verdict-bull': 'display:inline-block;font-weight:800;font-size:11px;letter-spacing:1px;background:%s;color:%s;padding:1px 8px;margin-left:6px;' % (INK, PAPER),
    'verdict-bear': 'display:inline-block;font-weight:800;font-size:11px;letter-spacing:1px;background:%s;color:#ffffff;padding:1px 8px;margin-left:6px;' % ACCENT,
    'verdict-neutral': 'display:inline-block;font-weight:800;font-size:11px;letter-spacing:1px;background:%s;color:%s;padding:1px 8px;margin-left:6px;' % (GREY_DEEP, PAPER),
    'verdict-mixed': 'display:inline-block;font-weight:800;font-size:11px;letter-spacing:1px;border:1px solid %s;color:%s;padding:0 7px;margin-left:6px;' % (INK, INK),
    'ai-verdict': 'background:%s;border-left:4px solid %s;padding:8px 10px;margin-top:10px;font-size:13px;line-height:1.55;' % (PAPER, ACCENT),
    'c-body': '',
    'c-time': 'font-size:11px;color:%s;margin-top:6px;' % GREY_DEEP,
    'swiss-list': 'margin:10px 0 14px 0;padding-left:0;list-style:none;',
    'swiss-rule': 'border:0;height:2px;background:%s;margin:26px 0;' % INK,
    'editorial-footer': 'border-top:3px solid %s;padding:18px 0 26px 0;text-align:center;font-size:12px;color:%s;line-height:1.9;' % (INK, GREY_DEEP),
    'logo-mark': 'display:inline-block;width:30px;height:30px;border:3px solid %s;border-radius:50%%;line-height:26px;text-align:center;font-weight:900;margin-bottom:8px;' % INK,
    'mono-tag': 'font-family:monospace;font-size:12px;background:%s;color:%s;padding:1px 6px;' % (INK, PAPER),
}

TAG_STYLE = {}

VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
ALLOWED_ATTRS = {'href', 'src', 'alt'}
SKIP_DEPTH_TAGS = {'script', 'style'}  # 整段丢弃的标签


class WechatConverter(HTMLParser):
    """把 report.html 的 <body> 转为微信兼容的内联样式 HTML。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []
        self.skip_stack = []      # 正在跳过的标签栈(script/style/push-module)
        self.li_prefix = False    # 下一个 li 需要插入红色破折号前缀

    # ---- 工具 ----
    def _first_class(self, attrs):
        for k, v in attrs:
            if k == 'class' and v:
                return v.split()[0]
        return ''

    def _in_skip(self):
        return bool(self.skip_stack)

    # ---- 事件 ----
    def handle_starttag(self, tag, attrs):
        if self._in_skip():
            if tag in SKIP_DEPTH_TAGS or any(t in self.skip_stack for t in SKIP_DEPTH_TAGS):
                self.skip_stack.append(tag)
            return
        cls = self._first_class(attrs)
        if tag in SKIP_DEPTH_TAGS or cls in ('push-module',):
            self.skip_stack.append(tag)
            return

        style = CLASS_STYLE.get(cls) or TAG_STYLE.get(tag)
        extra = ''
        if tag == 'li':
            style = 'position:relative;padding-left:22px;margin-bottom:8px;line-height:1.65;'
            self.li_prefix = True
        if tag == 'h2':
            # 保留大编号:data-num -> 灰色前缀
            num = next((v for k, v in attrs if k == 'data-num'), '')
            if num:
                extra = '<span style="color:%s;font-weight:900;">%s&nbsp;/&nbsp;</span>' % (GREY_MID, num)
        if tag == 'span' and cls == 'live-dot':
            extra = '●&nbsp;'
        if tag == 'img':
            pass  # 本报告无图片;如以后有图,保留 src(需可公网访问)

        new_attrs = []
        for k, v in attrs:
            if k in ALLOWED_ATTRS and v:
                new_attrs.append((k, v))
        if style:
            new_attrs.append(('style', style))

        attr_str = ''.join(' %s="%s"' % (k, v.replace('"', '&quot;')) for k, v in new_attrs)
        self.out.append('<%s%s>' % (tag, attr_str))
        if tag in VOID_TAGS:
            return
        if extra:
            self.out.append(extra)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self._in_skip():
            top = self.skip_stack.pop()
            if tag != top:  # 容错:压回去保持配对
                self.skip_stack.append(top)
            return
        if tag in VOID_TAGS:
            return
        self.out.append('</%s>' % tag)

    def handle_data(self, data):
        if self._in_skip():
            return
        if self.li_prefix:
            if data.strip():
                self.out.append('<span style="color:%s;font-weight:900;">—&nbsp;</span>' % ACCENT)
                self.li_prefix = False
        self.out.append(data)

    def handle_entityref(self, name):
        if not self._in_skip():
            self.out.append('&%s;' % name)

    def handle_charref(self, name):
        if not self._in_skip():
            self.out.append('&#%s;' % name)

    def handle_comment(self, data):
        pass


def extract_body(html):
    m = re.search(r'<body[^>]*>(.*)</body>', html, re.S | re.I)
    return m.group(1) if m else html


def build_core(source_html):
    """report.html -> 微信版正文(不含顶部横幅与外层包裹)。"""
    html = open(source_html, encoding='utf-8').read()
    body = extract_body(html)
    conv = WechatConverter()
    conv.feed(body)
    conv.close()
    return ''.join(conv.out)


def split_core(core, budget):
    """按章节边界(h2 大章节 / h3 小标题)把正文切成不超过 budget 的若干块。"""
    parts = re.split(r'(?=<h[23]\b)', core)
    chunks, buf = [], ''
    for seg in parts:
        if not seg.strip():
            continue
        if buf and len(buf) + len(seg) > budget:
            chunks.append(buf)
            buf = seg
        else:
            buf += seg
    if buf:
        chunks.append(buf)
    # 仍超长的块:按 swiss-rule / </article> 边界硬切
    final = []
    for ch in chunks:
        while len(ch) > budget:
            cut = max(ch.rfind('</article>', 0, budget), ch.rfind('<hr', 0, budget))
            if cut <= 0:
                cut = budget
            final.append(ch[:cut])
            ch = ch[cut:]
        final.append(ch)
    return final


def wrap_part(core, ts, idx, total):
    """给某一部分加外层样式 + 顶部信息横幅。idx/total 从 1 开始。"""
    part_mark = '' if total == 1 else ' (%d/%d)' % (idx, total)
    if idx == 1:
        note = '由 GitHub 自动推送 · %s' % ts
    else:
        note = '(续)章鱼 AI 全景分析 · %s' % ts
    banner = (
        '<div style="background:%s;color:%s;padding:12px 14px;margin:0 0 16px 0;'
        'font-size:13px;line-height:1.8;">'
        '<strong style="font-size:15px;">%s%s</strong><br/>%s · 完整排版版: '
        '<a style="color:%s;" href="%s">k-macao.github.io/03</a></div>'
    ) % (INK, PAPER, TITLE, part_mark, note, PAPER, PAGES_URL)
    return (
        '<div style="background:%s;color:%s;font-family:\'Helvetica Neue\','
        '\'PingFang SC\',\'Microsoft YaHei\',sans-serif;font-size:15px;'
        'line-height:1.65;padding:14px 6px;">%s%s</div>'
    ) % (PAPER, INK, banner, core)


def build_articles(source_html, now=None):
    """返回 (parts, ts):parts 为 [(title, content), ...] 可直接逐条推送。"""
    ts = (now or datetime.now(timezone.utc)).strftime('%Y-%m-%d %H:%M UTC')
    core = build_core(source_html)
    # 外层包裹+横幅约 600 字符,按上限留足余量
    budget = CONTENT_SAFE_LIMIT - 650
    chunks = split_core(core, budget)
    parts = []
    total = len(chunks)
    for i, ch in enumerate(chunks, 1):
        mark = '' if total == 1 else ' (%d/%d)' % (i, total)
        title = ('%s%s — %s' % (TITLE, mark, ts))[:100]
        parts.append((title, wrap_part(ch, ts, i, total)))
    return parts, ts


EMBED_BEGIN = '<!-- WECHAT-EMBED:BEGIN -->'
EMBED_END = '<!-- WECHAT-EMBED:END -->'


def embed_into_html(source_html, payload):
    """把推送负载以 JSON 形式内嵌进 report.html(幂等,可反复执行)。

    页面"手动推送"按钮直接读取 <script id="wechat-parts"> 中的内容,
    不依赖 wechat.json,这样即使不修改 GitHub 工作流也能推送完整报告。
    """
    with open(source_html, encoding='utf-8') as f:
        html = f.read()
    js = json.dumps(payload, ensure_ascii=False, indent=1).replace('</', '<\\/')
    block = '%s\n<script id="wechat-parts" type="application/json">\n%s\n</script>\n%s' % (
        EMBED_BEGIN, js, EMBED_END)
    pattern = re.compile(re.escape(EMBED_BEGIN) + r'.*?' + re.escape(EMBED_END), re.S)
    if pattern.search(html):
        html = pattern.sub(lambda _: block, html)
    else:
        anchor = html.find('\n<script>')
        if anchor < 0:
            anchor = html.rfind('</body>')
        html = html[:anchor + 1] + block + '\n' + html[anchor + 1:]
    with open(source_html, 'w', encoding='utf-8') as f:
        f.write(html)
    return len(js)


def find_token(source_html, arg_token=None):
    if arg_token:
        return arg_token
    env_token = os.environ.get('PUSHPLUS_TOKEN', '').strip()
    if env_token:
        return env_token
    html = open(source_html, encoding='utf-8').read()
    m = re.search(r"PUSHPLUS_TOKEN\s*=\s*'([0-9a-f]+)'", html)
    return m.group(1) if m else ''


def push_to_wechat(title, content, token):
    payload = json.dumps({
        'token': token,
        'title': title[:100],
        'content': content,
        'template': 'html',
    }).encode('utf-8')
    req = urllib.request.Request(
        PUSH_URL, data=payload,
        headers={'Content-Type': 'application/json; charset=utf-8'},
        method='POST')
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode('utf-8')
    try:
        data = json.loads(raw)
    except ValueError:
        return {'code': -1, 'msg': '非 JSON 响应', 'raw': raw[:500]}
    return data


def main():
    ap = argparse.ArgumentParser(description='章鱼 AI — 微信推送工具')
    ap.add_argument('--source', default=SOURCE_HTML, help='报告 HTML 文件路径')
    ap.add_argument('--emit', metavar='PATH', help='写出 wechat.json 的路径')
    ap.add_argument('--embed', action='store_true',
                    help='把推送负载内嵌进 report.html(供页面按钮读取)')
    ap.add_argument('--push', action='store_true', help='推送到 PushPlus')
    ap.add_argument('--token', default='', help='PushPlus token(可选)')
    ap.add_argument('--dry-run', action='store_true', help='只转换,打印统计')
    args = ap.parse_args()

    parts, ts = build_articles(args.source)
    print('转换完成:共 %d 条消息(上限 %d/条,安全线 %d)'
          % (len(parts), CONTENT_LIMIT, CONTENT_SAFE_LIMIT))
    for i, (t, c) in enumerate(parts, 1):
        print('  [%d/%d] %d 字符  %s' % (i, len(parts), len(c), t))
        if len(c) > CONTENT_SAFE_LIMIT:
            print('错误:第 %d 条超过安全长度' % i, file=sys.stderr)
            sys.exit(2)

    payload = {
        'title': parts[0][0],
        'parts': [{'title': t, 'content': c} for t, c in parts],
        'pages_url': PAGES_URL,
        'generated_at': ts,
    }

    if args.emit:
        out_path = os.path.abspath(args.emit)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        print('已写出: %s' % args.emit)

    if args.embed:
        n = embed_into_html(args.source, payload)
        print('已内嵌: %s(%d 字符 JSON)' % (args.source, n))

    if args.push:
        token = find_token(args.source, args.token)
        if not token:
            print('错误:未找到 PushPlus token', file=sys.stderr)
            sys.exit(3)
        failed = 0
        for i, (t, c) in enumerate(parts, 1):
            if i > 1:
                time.sleep(15)  # 温和对待接口频率限制(5 次/分钟)
            result = push_to_wechat(t, c, token)
            print('PushPlus 响应 [%d/%d]:' % (i, len(parts)),
                  json.dumps(result, ensure_ascii=False))
            if result.get('code') != 200:
                failed += 1
        if failed:
            sys.exit(4)

    if args.dry_run or (not args.emit and not args.push):
        print('--- 第 1 条正文预览(前 600 字符)---')
        print(parts[0][1][:600])


if __name__ == '__main__':
    main()
