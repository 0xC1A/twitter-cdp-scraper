#!/usr/bin/env python3
"""
CDP Spider - 通用网页抓取框架
基于 Chrome DevTools Protocol 的灵活数据提取工具

特点：
- 通过配置文件定义抓取逻辑
- 支持滚动加载、分页、点击展开
- 多种数据导出格式
- 内置常见网站预设配置

作者: 0xC1A
"""

import json
import requests
import time
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field


@dataclass
class ExtractorConfig:
    """数据提取配置"""
    name: str                          # 提取器名称
    url_pattern: str                   # URL 匹配模式
    
    # 选择器配置
    item_selector: str                 # 列表项选择器 (如: 'article[data-testid="tweet"]')
    field_selectors: Dict[str, str]    # 字段选择器 {字段名: CSS选择器}
    
    # 滚动/分页配置
    scroll_enabled: bool = True        # 是否启用滚动
    scroll_times: int = 50             # 最大滚动次数
    scroll_delay: float = 2.0          # 滚动间隔(秒)
    scroll_selector: Optional[str] = None  # 滚动容器选择器 (None则滚动整个页面)
    
    # 展开配置
    expand_selectors: List[str] = field(default_factory=list)  # 需要点击展开的元素
    expand_delay: float = 1.0          # 展开后等待时间
    
    # 数据处理
    field_processors: Dict[str, Callable] = field(default_factory=dict)  # 字段后处理器
    item_filter: Optional[Callable] = None  # 项目过滤函数
    
    # 导出配置
    id_field: str = 'id'               # 唯一标识字段
    sort_field: str = ''               # 排序字段
    sort_reverse: bool = True          # 倒序排序


class CDPSpider:
    """CDP 抓取框架主类"""
    
    def __init__(self, chrome_port: int = 9222, output_dir: str = 'spider_exports'):
        self.chrome_port = chrome_port
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
    def _check_chrome(self) -> tuple[bool, str]:
        """检查 Chrome DevTools 连接"""
        try:
            resp = requests.get(f'http://localhost:{self.chrome_port}/json/version', timeout=5)
            if resp.status_code == 200:
                return True, resp.json().get('Browser', 'unknown')
        except:
            pass
        return False, ''
    
    def _get_page(self, url_pattern: str) -> Optional[Dict]:
        """获取匹配的页面"""
        try:
            resp = requests.get(f'http://localhost:{self.chrome_port}/json/list', timeout=10)
            pages = resp.json()
            
            for p in pages:
                page_url = p.get('url', '')
                if re.search(url_pattern, page_url) and 'devtools' not in page_url:
                    return {
                        'id': p['id'],
                        'url': page_url,
                        'ws_url': p['webSocketDebuggerUrl'],
                        'title': p.get('title', 'Unknown')
                    }
        except Exception as e:
            print(f"❌ 获取页面列表失败: {e}")
        return None
    
    def _eval_js(self, ws_url: str, js_code: str, timeout: int = 30) -> Any:
        """执行 JavaScript"""
        try:
            import websocket
            ws = websocket.create_connection(ws_url, timeout=timeout)
            ws.send(json.dumps({
                'id': 1,
                'method': 'Runtime.evaluate',
                'params': {
                    'expression': js_code,
                    'returnByValue': True,
                    'awaitPromise': True
                }
            }))
            result = ws.recv()
            ws.close()
            
            data = json.loads(result)
            if 'result' in data and 'result' in data['result']:
                return data['result']['result'].get('value')
        except Exception as e:
            print(f"  ⚠️ JS 执行错误: {e}")
        return None
    
    def _expand_items(self, ws_url: str, config: ExtractorConfig):
        """点击展开所有折叠项 - 仅展开长文本，不跳转页面"""
        for selector in config.expand_selectors:
            # 多次尝试，直到没有新的可展开项
            for attempt in range(3):
                js_code = f"""
                (function() {{
                    // 只在当前页面（时间线）执行，不在推文详情页执行
                    if (window.location.pathname.includes('/status/')) {{
                        return -1; // 标记为在错误页面
                    }}
                    
                    const items = document.querySelectorAll('{selector}');
                    let clicked = 0;
                    items.forEach(item => {{
                        // 严格检查：可见、未被点击过、且文本精确匹配
                        if (item && item.offsetParent !== null && !item.getAttribute('data-expanded')) {{
                            const text = (item.innerText || item.textContent || '').trim().toLowerCase();
                            const ariaLabel = (item.getAttribute('aria-label') || '').toLowerCase();
                            
                            // 只点击真正的 "Show more" 按钮
                            const isShowMore = text === 'show more' || 
                                              ariaLabel === 'show more' ||
                                              item.getAttribute('data-testid') === 'tweet-text-show-more-link';
                            
                            if (isShowMore) {{
                                item.setAttribute('data-expanded', 'true');
                                item.click();
                                clicked++;
                            }}
                        }}
                    }});
                    return clicked;
                }})()
                """
                result = self._eval_js(ws_url, js_code)
                
                if result == -1:
                    print(f"      ⚠️ 检测到在推文详情页，跳过展开操作")
                    return
                
                clicked = int(result) if isinstance(result, (int, float)) else 0
                if clicked > 0:
                    print(f"      展开 {clicked} 个折叠项 (尝试 {attempt + 1})")
                    time.sleep(config.expand_delay)
                else:
                    break
    
    def _scroll_page(self, ws_url: str, config: ExtractorConfig):
        """滚动页面"""
        if config.scroll_selector:
            # 滚动特定容器
            js_code = f"""
                document.querySelector('{config.scroll_selector}').scrollTop = 
                document.querySelector('{config.scroll_selector}').scrollHeight;
            """
        else:
            # 滚动整个页面
            js_code = "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'});"
        
        self._eval_js(ws_url, js_code)
        time.sleep(config.scroll_delay)
    
    def _extract_items(self, ws_url: str, config: ExtractorConfig) -> List[Dict]:
        """提取当前页面的所有项目"""
        # 先展开折叠项
        if config.expand_selectors:
            self._expand_items(ws_url, config)
        
        # 构建提取 JS
        field_extractors = []
        for field_name, selector in config.field_selectors.items():
            field_extractors.append(f"""
                // {field_name}
                try {{
                    const {field_name}El = article.querySelector('{selector}');
                    if ({field_name}El) {{
                        // 优先使用 innerText 获取渲染后的文本（包含展开后的内容）
                        let text = {field_name}El.innerText || {field_name}El.textContent || '';
                        // 也尝试从 href 获取链接
                        if (!text && {field_name}El.getAttribute('href')) {{
                            text = {field_name}El.getAttribute('href');
                        }}
                        // 也尝试 aria-label
                        if (!text && {field_name}El.getAttribute('aria-label')) {{
                            text = {field_name}El.getAttribute('aria-label');
                        }}
                        item['{field_name}'] = text.trim();
                    }}
                }} catch(e) {{}}
            """)
        
        js_code = f"""
        (function() {{
            const items = [];
            const articles = document.querySelectorAll('{config.item_selector}');
            
            articles.forEach((article, index) => {{
                try {{
                    const item = {{_index: index}};
                    {''.join(field_extractors)}
                    items.push(item);
                }} catch(e) {{}}
            }});
            
            return items;
        }})()
        """
        
        result = self._eval_js(ws_url, js_code)
        return result if isinstance(result, list) else []
    
    def crawl(self, config: ExtractorConfig) -> List[Dict]:
        """
        执行抓取
        
        Args:
            config: 提取器配置
            
        Returns:
            抓取的数据列表
        """
        print("=" * 70)
        print(f"🕷️  CDP Spider - {config.name}")
        print("=" * 70)
        
        # 检查 Chrome
        print("\n📡 连接 Chrome...")
        connected, browser = self._check_chrome()
        if not connected:
            print("❌ 无法连接到 Chrome")
            print(f"\n请先启动 Chrome:")
            print(f"  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\")
            print(f"      --remote-debugging-port={self.chrome_port} \\")
            print(f"      --remote-allow-origins='*' \\")
            print(f"      --user-data-dir=/tmp/chrome_dev_profile")
            return []
        print(f"✅ 已连接 ({browser})")
        
        # 查找目标页面
        print(f"\n📄 查找页面: {config.url_pattern}")
        page = self._get_page(config.url_pattern)
        if not page:
            print("❌ 未找到匹配的页面")
            print("请在 Chrome 中打开目标页面")
            return []
        print(f"✅ 找到页面: {page['title'][:50]}")
        
        # 开始抓取
        print(f"\n🔍 开始抓取...")
        if config.scroll_enabled:
            print(f"   滚动模式: 最多 {config.scroll_times} 次")
        
        all_items = {}
        ws_url = page['ws_url']
        
        for i in range(config.scroll_times if config.scroll_enabled else 1):
            # 提取数据
            items = self._extract_items(ws_url, config)
            
            new_count = 0
            for item in items:
                item_id = item.get(config.id_field) or item.get('_index')
                if item_id and item_id not in all_items:
                    # 应用字段处理器
                    for field, processor in config.field_processors.items():
                        if field in item:
                            item[field] = processor(item[field])
                    
                    # 应用过滤器
                    if config.item_filter is None or config.item_filter(item):
                        all_items[item_id] = item
                        new_count += 1
            
            if i % 5 == 0 or new_count > 0:
                print(f"   第 {i+1} 轮: +{new_count} 条新数据, 总计: {len(all_items)} 条")
            
            # 检查是否需要继续
            if not config.scroll_enabled:
                break
                
            if new_count == 0 and i > 5:
                print(f"   ✅ 没有新数据了，停止")
                break
            
            # 滚动
            self._scroll_page(ws_url, config)
        
        return list(all_items.values())
    
    def save(self, data: List[Dict], name: str, config: ExtractorConfig = None):
        """保存数据到多种格式"""
        if not data:
            print("❌ 没有数据可保存")
            return
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"{name}_{timestamp}"
        
        # 排序
        if config and config.sort_field:
            data.sort(key=lambda x: x.get(config.sort_field, ''), 
                     reverse=config.sort_reverse)
        
        # JSON
        json_file = self.output_dir / f"{base_name}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump({
                'source': name,
                'crawled_at': datetime.now().isoformat(),
                'count': len(data),
                'data': data
            }, f, ensure_ascii=False, indent=2)
        
        # CSV
        if data and isinstance(data[0], dict):
            import csv
            csv_file = self.output_dir / f"{base_name}.csv"
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
        
        # Markdown
        md_file = self.output_dir / f"{base_name}.md"
        with open(md_file, 'w', encoding='utf-8') as f:
            f.write(f"# {name} 数据\n\n")
            f.write(f"抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"数据条数: {len(data)}\n\n")
            f.write("---\n\n")
            
            for i, item in enumerate(data[:100], 1):  # 只显示前100条
                f.write(f"### {i}. {item.get('title', item.get('text', 'Item'))[:50]}\n\n")
                for key, value in item.items():
                    if not key.startswith('_'):
                        f.write(f"- **{key}**: {value}\n")
                f.write("\n---\n\n")
        
        print(f"\n✅ 已保存:")
        print(f"   📄 JSON: {json_file}")
        print(f"   📊 CSV: {csv_file}")
        print(f"   📝 Markdown: {md_file}")


# ============ 预设配置 ============

class Presets:
    """常用网站预设配置"""
    
    @staticmethod
    def twitter(username: str) -> ExtractorConfig:
        """Twitter/X 推文抓取"""
        
        def extract_full_text(element_html: str) -> str:
            """提取完整推文文本，处理展开后的长文本"""
            # 这个处理器会在 JS 执行后通过 innerText 获取
            # 但如果还有问题，可以在这里做后处理
            return element_html.strip()
        
        return ExtractorConfig(
            name=f"Twitter @{username}",
            url_pattern=rf"x\.com/{username}",
            item_selector='article[data-testid="tweet"]',
            field_selectors={
                'id': 'a[href*="/status/"]',
                'text': '[data-testid="tweetText"]',  # 展开后会自动包含完整文本
                'time': 'time',
                'author': 'div[data-testid="User-Name"] a',
                'likes': '[data-testid="like"]',
                'replies': '[data-testid="reply"]',
                'retweets': '[data-testid="retweet"]'
            },
            scroll_times=50,
            scroll_delay=2.5,  # 稍微增加滚动间隔
            expand_selectors=[
                '[data-testid="tweet-text-show-more-link"]',  # Twitter 官方的长文本展开按钮
            ],
            expand_delay=1.5,  # 增加展开后等待时间
            field_processors={
                'id': lambda x: re.search(r'/status/(\d+)', str(x)).group(1) if re.search(r'/status/(\d+)', str(x)) else x,
                'likes': lambda x: int(re.search(r'(\d+)', str(x).replace(',', '')).group(1)) if re.search(r'(\d+)', str(x)) else 0,
                'replies': lambda x: int(re.search(r'(\d+)', str(x).replace(',', '')).group(1)) if re.search(r'(\d+)', str(x)) else 0,
                'retweets': lambda x: int(re.search(r'(\d+)', str(x).replace(',', '')).group(1)) if re.search(r'(\d+)', str(x)) else 0,
            },
            sort_field='time'
        )
    
    @staticmethod
    def zhihu_answers() -> ExtractorConfig:
        """知乎回答抓取"""
        return ExtractorConfig(
            name="知乎回答",
            url_pattern=r"zhihu\.com/question/\d+",
            item_selector='.AnswerCard, .ContentItem.AnswerItem',
            field_selectors={
                'author': '.AuthorInfo-name',
                'content': '.RichContent-inner',
                'votes': '.VoteButton--up',
                'comments': '.ContentItem-action:has(.CommentIcon)'
            },
            scroll_times=30,
            expand_selectors=['.ContentItem-more', '.RichContent-inner--collapsed']
        )
    
    @staticmethod
    def douban_reviews() -> ExtractorConfig:
        """豆瓣影评/书评抓取"""
        return ExtractorConfig(
            name="豆瓣评论",
            url_pattern=r"douban\.com/subject/\d+/reviews",
            item_selector='.review-item',
            field_selectors={
                'title': '.main-bd h2 a',
                'author': '.main-hd .name',
                'rating': '.main-title-rating',
                'content': '.short-content',
                'votes': '.action-btn.up span'
            },
            scroll_times=20
        )
    
    @staticmethod
    def github_issues() -> ExtractorConfig:
        """GitHub Issues 抓取"""
        return ExtractorConfig(
            name="GitHub Issues",
            url_pattern=r"github\.com/[^/]+/[^/]+/issues",
            item_selector='[data-testid="issue-row"]',
            field_selectors={
                'title': 'a[data-testid="issue-title"]',
                'number': 'span[title]',
                'status': '[data-testid="issue-row-status"]',
                'author': '[data-testid="issue-row-author"]'
            },
            scroll_enabled=False  # GitHub 用分页，不用滚动
        )


# ============ 使用示例 ============

def main():
    """演示如何使用框架"""
    import sys
    
    # 检查参数
    if len(sys.argv) < 2:
        print("使用方法:")
        print(f"  python3 {sys.argv[0]} <preset> [options]")
        print("")
        print("可用预设:")
        print("  twitter <username>  - 抓取 Twitter 推文")
        print("  zhihu               - 抓取知乎回答")
        print("  douban              - 抓取豆瓣评论")
        print("  github              - 抓取 GitHub Issues")
        print("")
        print("示例:")
        print(f"  python3 {sys.argv[0]} twitter elonmusk")
        return
    
    preset = sys.argv[1]
    spider = CDPSpider()
    
    # 根据预设创建配置
    if preset == 'twitter':
        username = sys.argv[2] if len(sys.argv) > 2 else input("输入 Twitter 用户名: ")
        config = Presets.twitter(username)
    elif preset == 'zhihu':
        config = Presets.zhihu_answers()
    elif preset == 'douban':
        config = Presets.douban_reviews()
    elif preset == 'github':
        config = Presets.github_issues()
    else:
        print(f"❌ 未知预设: {preset}")
        return
    
    # 执行抓取
    data = spider.crawl(config)
    
    if data:
        spider.save(data, preset, config)
        print(f"\n🎉 完成! 共抓取 {len(data)} 条数据")
    else:
        print("\n❌ 抓取失败")


if __name__ == '__main__':
    main()
