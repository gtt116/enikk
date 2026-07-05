#!/usr/bin/env python3
"""
Smart Fetch - AI网页抓取优化工具
自动获取Markdown格式，节省80% Token
"""

import sys
import urllib.request
from html.parser import HTMLParser
import re


class HTMLToMarkdown(HTMLParser):
    """HTML转Markdown转换器"""

    def __init__(self):
        super().__init__()
        self.result = []
        self.in_script = False
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside'}

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.in_script = tag == 'script'
        elif tag in self.skip_tags:
            pass
        elif tag == 'h1':
            self.result.append('\n# ')
        elif tag == 'h2':
            self.result.append('\n## ')
        elif tag == 'h3':
            self.result.append('\n### ')
        elif tag == 'p':
            self.result.append('\n')
        elif tag == 'br':
            self.result.append('\n')
        elif tag == 'a':
            attrs_dict = dict(attrs)
            if 'href' in attrs_dict:
                self.result.append(f'[{attrs_dict.get("href", "")}](')
        elif tag == 'img':
            attrs_dict = dict(attrs)
            alt, src = attrs_dict.get('alt', ''), attrs_dict.get('src', '')
            if src:
                self.result.append(f'![{alt}]({src})')
        elif tag in ('ul', 'ol'):
            self.result.append('\n')
        elif tag == 'li':
            self.result.append('- ')
        elif tag in ('strong', 'b'):
            self.result.append('**')
        elif tag in ('em', 'i'):
            self.result.append('*')
        elif tag == 'code':
            self.result.append('`')
        elif tag == 'pre':
            self.result.append('\n```\n')

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False
        elif tag in self.skip_tags:
            pass
        elif tag in ('h1', 'h2', 'h3', 'h4', 'p', 'li'):
            self.result.append('\n')
        elif tag == 'a':
            self.result.append(')')
        elif tag in ('strong', 'b'):
            self.result.append('**')
        elif tag in ('em', 'i'):
            self.result.append('*')
        elif tag == 'code':
            self.result.append('`')
        elif tag == 'pre':
            self.result.append('\n```\n')

    def handle_data(self, data):
        if self.in_script:
            return
        text = data.strip()
        if text:
            self.result.append(text)

    def get_markdown(self):
        return ''.join(self.result)


def clean_markdown(md_text):
    # 1. 去除代码块 (```...``` 或 `...`)
    md_text = re.sub(r'```[\s\S]*?```', '', md_text)
    md_text = re.sub(r'`[^`\n]+`', '', md_text)

    # 2. 去除图片 ![alt](url)
    md_text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md_text)

    # 3. 去除链接，只保留链接文字 [text](url) -> text
    md_text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', md_text)

    # 4. 去除表格 (包含 | 的行)
    md_text = re.sub(r'^.*\|.*$', '', md_text, flags=re.MULTILINE)

    # 5. 去除 HTML 标签
    md_text = re.sub(r'<[^>]+>', '', md_text)

    # 6. 去除其他 Markdown 格式符号
    # 去除加粗/斜体/删除线 (***text***, **text**, *text*, ~~text~~)
    md_text = re.sub(r'(\*{1,3}|~{2})(.*?)\1', r'\2', md_text)
    # 去除引用符号 >
    md_text = re.sub(r'^>\s?', '', md_text, flags=re.MULTILINE)
    # 去除无序列表符号 (-, *, +)
    md_text = re.sub(r'^[\s]*[-*+]\s', '', md_text, flags=re.MULTILINE)
    # 去除有序列表符号 (1. 2.)
    md_text = re.sub(r'^[\s]*\d+\.\s', '', md_text, flags=re.MULTILINE)

    # 7. 清理多余的空行 (将3个及以上连续换行符替换为2个)
    md_text = re.sub(r'\n{3,}', '\n\n', md_text)

    pattern_non_cn = re.compile(r'[^\u4e00-\u9fa5]{20,}')
    pattern_url = re.compile(r'https?://|javascript:;')
    filtered_lines = [
        line for line in md_text.split('\n')
        if not pattern_non_cn.search(line) and not pattern_url.search(line)
    ]

    return re.sub(r'(?:\r\n|\n){2,}', '\n', '\n'.join(filtered_lines).strip())


def smart_fetch(url, max_chars=5000):
    """智能抓取：优先Markdown，自动转换HTML"""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        'Accept-Encoding': 'identity',
        "Connection": "keep-alive"
    }

    try:
        req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=30) as response:
            content_type = response.headers.get('Content-Type', '').lower()
            content = response.read().decode('utf-8', errors='ignore')

            # 情况1：直接返回Markdown
            if 'markdown' in content_type:
                print(f"✅ Markdown格式，Token已优化", file=sys.stderr)
                return clean_markdown(content)[:max_chars]

            # 情况2：纯文本
            if 'text/plain' in content_type:
                return content[:max_chars]

            # 情况3：HTML，需要转换
            print(f"  HTML转Markdown中...", file=sys.stderr)
            converter = HTMLToMarkdown()

            # 提取body内容
            body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
            body_content = body_match.group(1) if body_match else content

            converter.feed(body_content)
            markdown = converter.get_markdown()
            # markdown = re.sub(r'\n{3,}', '\n\n', markdown)

            return clean_markdown(markdown)[:max_chars]

    except Exception as e:
        return f"❌ 抓取失败: {str(e)}"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 smart_fetch.py <URL> [最大字符数]")
        sys.exit(1)

    url = sys.argv[1]
    max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    print(smart_fetch(url, max_chars))