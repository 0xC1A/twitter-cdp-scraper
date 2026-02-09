#!/usr/bin/env python3
"""
CDP Spider - 通用网页抓取框架
基于 Chrome DevTools Protocol 的灵活数据提取工具

特点：
- 通过配置文件定义抓取逻辑
- 支持滚动加载、分页、点击展开
- 智能滚动策略应对虚拟滚动（如 Twitter/X）
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
    scroll_times: int = 0              # 最大滚动次数 (0表示不限)
    scroll_delay: float = 2.0          # 滚动间隔(秒)
    scroll_selector: Optional[str] = None  # 滚动容器选择器 (None则滚动整个页面)

    # 展开配置
    expand_selectors: List[str] = field(default_factory=list)  # 需要点击展开的元素
    expand_delay: float = 1.0          # 展开后等待时间

    # 媒体下载配置
    download_media: bool = False       # 是否下载媒体文件

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
        """点击展开所有折叠项 - 仅展开主推文的长文本，避免点击引用推文导致跳转"""
        for selector in config.expand_selectors:
            for attempt in range(5):  # 增加尝试次数
                js_code = f"""
                (function() {{
                    // 检查是否在时间线页面
                    if (window.location.pathname.includes('/status/')) {{
                        return {{status: 'wrong_page', msg: '在推文详情页'}};
                    }}

                    let clicked = 0;

                    // 方法1: 通过 data-testid 查找
                    const items1 = document.querySelectorAll('[data-testid="tweet-text-show-more-link"]');

                    // 方法2: 通过文本内容查找所有包含 "Show more" 的 span/button
                    // 主推文的 show more 通常是 tweetText 区域内的 span
                    const allArticles = document.querySelectorAll('article[data-testid="tweet"]');

                    // 优先使用方法1
                    items1.forEach(item => {{
                        if (!item || item.offsetParent === null || item.getAttribute('data-expanded')) {{
                            return;
                        }}

                        // 检查是否在主推文内（不是引用推文）
                        // 引用推文通常在一个嵌套的 article 或特定容器内
                        const isQuoteTweet = item.closest('div[role="link"]') !== null ||
                                            item.closest('[data-testid="quotedTweet"]') !== null ||
                                            item.closest('article') !== item.closest('article[data-testid="tweet"]');

                        if (isQuoteTweet) {{
                            return;
                        }}

                        item.setAttribute('data-expanded', 'true');
                        item.click();
                        clicked++;
                    }});

                    // 如果方法1没点到，尝试方法2：在每个 article 内查找 show more
                    if (clicked === 0) {{
                        allArticles.forEach(article => {{
                            // 只处理主推文的 tweetText 区域
                            const tweetText = article.querySelector('[data-testid="tweetText"]');
                            if (!tweetText) return;

                            // 在 tweetText 内查找 show more 按钮
                            // 它可能是一个 span 或 button，包含 "Show more" 文本
                            const allElements = tweetText.querySelectorAll('span, button');

                            allElements.forEach(el => {{
                                if (el.getAttribute('data-expanded')) return;

                                const text = (el.innerText || el.textContent || '').trim();
                                const ariaLabel = (el.getAttribute('aria-label') || '').trim();

                                // 匹配 Show more（不区分大小写）
                                if (text.toLowerCase() === 'show more' ||
                                    ariaLabel.toLowerCase() === 'show more' ||
                                    text.toLowerCase().includes('show more')) {{

                                    el.setAttribute('data-expanded', 'true');
                                    el.click();
                                    clicked++;
                                }}
                            }});
                        }});
                    }}

                    return {{status: 'success', clicked: clicked}};
                }})()
                """
                result = self._eval_js(ws_url, js_code)

                if isinstance(result, dict):
                    if result.get('status') == 'wrong_page':
                        print(f"      ⚠️ 检测到在推文详情页，停止展开")
                        return
                    clicked = result.get('clicked', 0)
                else:
                    clicked = int(result) if isinstance(result, (int, float)) else 0

                if clicked > 0:
                    print(f"      展开 {clicked} 个主推文折叠项 (尝试 {attempt + 1})")
                    time.sleep(config.expand_delay)
                else:
                    break

    def _scroll_page(self, ws_url: str, config: ExtractorConfig, step: int = 1) -> dict:
        """
        滚动页面 - 使用小步长滚动避免虚拟滚动导致的数据丢失
        返回详细的滚动信息，包括是否真正滚动了（用于检测底部）

        Args:
            step: 滚动步数，每次滚动一屏的一部分

        Returns:
            {
                'scrolled': 请求的滚动距离,
                'actualScrolled': 实际滚动距离,
                'viewportHeight': 视口高度,
                'newPosition': 新滚动位置,
                'pageHeight': 页面总高度,
                'hitBottom': 是否碰到底部（实际滚动 < 请求滚动的50%）,
                'scrollPercent': 滚动百分比
            }
        """
        js_code = """
        (function() {
            const viewportHeight = window.innerHeight;
            const scrollDistance = Math.floor(viewportHeight * 0.7);
            const beforeScroll = window.pageYOffset || document.documentElement.scrollTop;
            const pageHeight = document.body.scrollHeight;
            const maxScroll = pageHeight - viewportHeight;

            window.scrollTo({
                top: beforeScroll + scrollDistance,
                behavior: 'smooth'
            });

            // 等待滚动动画开始
            return new Promise((resolve) => {
                setTimeout(() => {
                    const afterScroll = window.pageYOffset || document.documentElement.scrollTop;
                    const actualScrolled = afterScroll - beforeScroll;
                    const scrollPercent = maxScroll > 0 ? (afterScroll / maxScroll * 100).toFixed(1) : 100;

                    // 如果实际滚动距离小于请求距离的50%，认为碰到了底部
                    const hitBottom = actualScrolled < scrollDistance * 0.5 || afterScroll >= maxScroll - 10;

                    resolve({
                        scrolled: scrollDistance,
                        actualScrolled: actualScrolled,
                        viewportHeight: viewportHeight,
                        newPosition: afterScroll,
                        pageHeight: pageHeight,
                        hitBottom: hitBottom,
                        scrollPercent: parseFloat(scrollPercent)
                    });
                }, 300); // 给滚动动画一点时间
            });
        })()
        """

        result = self._eval_js(ws_url, js_code)
        time.sleep(config.scroll_delay)
        return result or {}

    def _get_scroll_info(self, ws_url: str) -> dict:
        """获取当前滚动信息"""
        js_code = """
        (function() {
            const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
            const scrollHeight = document.body.scrollHeight;
            const viewportHeight = window.innerHeight;
            const maxScroll = Math.max(1, scrollHeight - viewportHeight);

            return {
                scrollTop: scrollTop,
                scrollHeight: scrollHeight,
                viewportHeight: viewportHeight,
                scrollPercent: ((scrollTop / maxScroll) * 100).toFixed(1)
            };
        })()
        """
        return self._eval_js(ws_url, js_code) or {}

    def _get_top_visible_item_id(self, ws_url: str, config: ExtractorConfig) -> Optional[str]:
        """
        获取视口中最顶部可见的推文ID
        用于检测是否真的在向前滚动
        """
        js_code = f"""
        (function() {{
            const articles = document.querySelectorAll('{config.item_selector}');
            const viewportTop = window.pageYOffset || document.documentElement.scrollTop;
            const viewportHeight = window.innerHeight;

            for (const article of articles) {{
                const rect = article.getBoundingClientRect();
                const articleTop = rect.top + viewportTop;
                const idEl = article.querySelector('{config.id_field}') ||
                            article.querySelector('a[href*="/status/"]');

                // 找到第一个在视口内或刚好在视口上方的推文
                if (articleTop >= viewportTop - 100 &&
                    articleTop <= viewportTop + viewportHeight * 0.5) {{
                    let id = '';
                    if (idEl) {{
                        id = idEl.getAttribute('href') || idEl.innerText || '';
                    }}
                    if (!id) {{
                        // 备用：使用索引
                        id = 'idx_' + Array.from(articles).indexOf(article);
                    }}
                    return {{
                        id: id.trim(),
                        position: articleTop
                    }};
                }}
            }}
            return null;
        }})()
        """
        return self._eval_js(ws_url, js_code)

    def _get_all_visible_item_ids(self, ws_url: str, config: ExtractorConfig) -> List[str]:
        """
        获取当前DOM中所有可见的推文ID列表
        用于判断是否所有可见推文都已被抓取

        Returns:
            可见推文ID列表（按在DOM中的顺序）
        """
        js_code = f"""
        (function() {{
            const articles = document.querySelectorAll('{config.item_selector}');
            const viewportTop = window.pageYOffset || document.documentElement.scrollTop;
            const viewportHeight = window.innerHeight;
            const ids = [];

            articles.forEach((article, index) => {{
                const rect = article.getBoundingClientRect();
                const articleTop = rect.top + viewportTop;
                const articleBottom = articleTop + rect.height;

                // 检查推文是否在视口内（或部分可见）
                const isVisible = (articleTop < viewportTop + viewportHeight + 100) &&
                                  (articleBottom > viewportTop - 100);

                if (isVisible) {{
                    // 尝试获取ID
                    let id = '';
                    const idEl = article.querySelector('{config.id_field}') ||
                                article.querySelector('a[href*="/status/"]');
                    if (idEl) {{
                        id = idEl.getAttribute('href') || idEl.innerText || '';
                    }}
                    if (!id) {{
                        id = 'idx_' + index;
                    }}
                    ids.push(id.trim());
                }}
            }});

            return ids;
        }})()
        """
        result = self._eval_js(ws_url, js_code)
        return result if isinstance(result, list) else []

    def _check_all_visible_items_crawled(self, ws_url: str, config: ExtractorConfig,
                                          crawled_ids: set) -> dict:
        """
        检查当前DOM中所有可见推文是否都已被抓取

        Args:
            crawled_ids: 已抓取的推文ID集合

        Returns:
            {
                'all_crawled': bool,  # 所有可见推文是否都已抓取
                'visible_count': int,  # 可见推文数量
                'crawled_count': int,  # 已抓取的可见推文数量
                'uncrawled_ids': list  # 未抓取的可见推文ID
            }
        """
        visible_ids = self._get_all_visible_item_ids(ws_url, config)

        if not visible_ids:
            return {
                'all_crawled': False,
                'visible_count': 0,
                'crawled_count': 0,
                'uncrawled_ids': []
            }

        # 处理ID格式（提取推文ID）
        def extract_id(id_str: str) -> str:
            if '/status/' in id_str:
                match = re.search(r'/status/(\d+)', id_str)
                if match:
                    return match.group(1)
            return id_str

        visible_ids_clean = {extract_id(vid) for vid in visible_ids}
        crawled_ids_clean = {extract_id(cid) for cid in crawled_ids}

        uncrawled = visible_ids_clean - crawled_ids_clean

        return {
            'all_crawled': len(uncrawled) == 0,
            'visible_count': len(visible_ids_clean),
            'crawled_count': len(visible_ids_clean) - len(uncrawled),
            'uncrawled_ids': list(uncrawled)
        }

    def _extract_items(self, ws_url: str, config: ExtractorConfig, download_media: bool = False, media_dir: Path = None) -> List[Dict]:
        """提取当前页面的所有项目"""
        # 先展开折叠项
        if config.expand_selectors:
            self._expand_items(ws_url, config)

        # 构建提取 JS
        field_extractors = []
        for field_name, selector in config.field_selectors.items():
            # 跳过媒体字段，我们单独处理
            if field_name in ['image_urls', 'video_urls']:
                continue

            # 判断是否需要优先获取 href（如 id 字段或选择器包含链接相关）
            prefer_href = field_name in ['id', 'url', 'link'] or 'href' in selector
            
            # 对 time 字段特殊处理：优先获取 datetime 属性
            is_time_field = field_name == 'time' or selector == 'time'

            field_extractors.append(f"""
                // {field_name}
                try {{
                    const {field_name}El = article.querySelector('{selector}');
                    if ({field_name}El) {{
                        let text = '';
                        
                        // 对于 time 元素，优先获取 datetime 属性（精确时间）
                        if ({str(is_time_field).lower()}) {{
                            text = {field_name}El.getAttribute('datetime') || 
                                   {field_name}El.getAttribute('title') || 
                                   {field_name}El.innerText || 
                                   {field_name}El.textContent || '';
                        }} else if ({str(prefer_href).lower()}) {{
                            // 对于 id/url/link 字段，优先获取 href
                            text = {field_name}El.getAttribute('href') || '';
                            if (!text) {{
                                text = {field_name}El.innerText || {field_name}El.textContent || '';
                            }}
                        }} else {{
                            // 其他字段优先使用 innerText
                            text = {field_name}El.innerText || {field_name}El.textContent || '';
                            if (!text) {{
                                text = {field_name}El.getAttribute('href') || '';
                            }}
                        }}

                        // 也尝试 aria-label
                        if (!text) {{
                            text = {field_name}El.getAttribute('aria-label') || '';
                        }}

                        item['{field_name}'] = text.trim();
                    }}
                }} catch(e) {{}}
            """)

        # 添加媒体提取代码
        media_extractor = """
            // 提取图片 URL
            try {
                const images = article.querySelectorAll('[data-testid="tweetPhoto"] img');
                const imageUrls = Array.from(images).map(img => img.src).filter(Boolean);
                if (imageUrls.length > 0) {
                    item['image_urls'] = imageUrls.join(',');
                    item['image_count'] = imageUrls.length;
                }
            } catch(e) {}

            // 提取视频标记
            try {
                const video = article.querySelector('[data-testid="videoPlayer"], [data-testid="videoComponent"]');
                if (video) {
                    item['has_video'] = true;
                }
            } catch(e) {}
        """

        js_code = f"""
        (function() {{
            const items = [];
            const articles = document.querySelectorAll('{config.item_selector}');

            articles.forEach((article, index) => {{
                try {{
                    const item = {{_index: index}};
                    {''.join(field_extractors)}
                    {media_extractor}
                    items.push(item);
                }} catch(e) {{}}
            }});

            return items;
        }})()
        """

        result = self._eval_js(ws_url, js_code)
        items = result if isinstance(result, list) else []

        # 如果启用了媒体下载，同时下载图片
        if download_media and media_dir:
            for item in items:
                image_urls = item.get('image_urls', '')
                if image_urls:
                    urls = [u.strip() for u in image_urls.split(',') if u.strip()]
                    downloaded = []

                    for url in urls:
                        tweet_id = str(item.get('id', 'unknown'))[:20]
                        filename = f"{tweet_id}_{url.split('/')[-1].split('?')[0]}"
                        if '.' not in filename:
                            filename += '.jpg'

                        save_path = media_dir / filename

                        if self._download_via_chrome(ws_url, url, save_path):
                            downloaded.append(filename)

                    if downloaded:
                        item['downloaded_images'] = ','.join(downloaded)

        return items

    def crawl(self, config: ExtractorConfig) -> List[Dict]:
        """
        执行抓取 - 使用智能滚动策略应对虚拟滚动

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
        scroll_limit_str = f"{config.scroll_times}" if config.scroll_times > 0 else "不限"
        print(f"   滚动策略: 小步长滚动 + 即时提取（应对虚拟滚动）")
        print(f"   最大滚动次数: {scroll_limit_str}")

        all_items = {}
        ws_url = page['ws_url']
        no_new_count = 0  # 连续没有新数据的次数
        prev_scroll_top = 0
        prev_scroll_height = 0  # 上一次的页面高度
        min_scroll_rounds = 10  # 最少滚动次数（防止长推文误判）
        last_top_item_id = None  # 上一次视口顶部的推文ID
        stuck_count = 0  # 视口顶部推文未变化的次数
        
        # 确认模式：检测到结束信号后，继续滚动 confirm_rounds 次确认
        confirm_mode = False  # 是否进入确认模式
        confirm_rounds = 10   # 确认模式需要滚动的次数
        confirm_remaining = 0 # 确认模式剩余次数
        confirm_trigger_reason = "" # 触发确认模式的原因
        
        # 媒体下载配置
        download_media = getattr(config, 'download_media', False)
        media_dir = None
        if download_media:
            media_dir = self.output_dir / f"media_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            media_dir.mkdir(exist_ok=True)
            print(f"   媒体下载: 启用 -> {media_dir}")

        # 重置滚动位置到顶部（确保从第一条推文开始抓取）
        print("\n📍 重置滚动位置到顶部...")
        self._eval_js(ws_url, "window.scrollTo({top: 0, behavior: 'instant'});")
        time.sleep(1)  # 等待虚拟滚动重新渲染
        print("   ✅ 已回到顶部，开始抓取\n")

        # 确定最大滚动次数（0表示不限，使用一个很大的数）
        max_scroll_times = config.scroll_times if config.scroll_times > 0 else 10000
        
        for i in range(max_scroll_times if config.scroll_enabled else 1):
            # 提取数据（在滚动前也提取一次，确保第一屏的数据）
            items = self._extract_items(ws_url, config, download_media, media_dir)

            new_count = 0
            duplicate_count = 0
            for item in items:
                item_id = item.get(config.id_field) or item.get('_index')
                if item_id:
                    if item_id not in all_items:
                        # 应用字段处理器
                        for field, processor in config.field_processors.items():
                            if field in item:
                                item[field] = processor(item[field])

                        # 应用过滤器
                        if config.item_filter is None or config.item_filter(item):
                            all_items[item_id] = item
                            new_count += 1
                    else:
                        duplicate_count += 1

            # 获取滚动信息
            scroll_info = self._get_scroll_info(ws_url)
            scroll_percent = float(scroll_info.get('scrollPercent', 0))
            current_scroll_top = scroll_info.get('scrollTop', 0)
            current_scroll_height = scroll_info.get('scrollHeight', 0)

            # 检测页面高度是否增长（有新内容加载）
            height_grew = current_scroll_height > prev_scroll_height

            # 获取视口顶部推文ID，检测是否卡住
            top_item = self._get_top_visible_item_id(ws_url, config)
            top_item_id = top_item.get('id') if top_item else None

            if top_item_id == last_top_item_id:
                stuck_count += 1
            else:
                stuck_count = 0
                last_top_item_id = top_item_id

            # 检查当前DOM中所有可见推文是否都已被抓取
            crawled_ids_set = set(all_items.keys())
            visible_check = self._check_all_visible_items_crawled(ws_url, config, crawled_ids_set)
            all_visible_crawled = visible_check.get('all_crawled', False)
            visible_uncrawled = visible_check.get('uncrawled_ids', [])

            # 显示进度
            progress_bar = self._make_progress_bar(scroll_percent)
            all_duplicates = len(items) > 0 and new_count == 0  # 当前获取的所有推文都是重复的
            status_marker = "↑" if height_grew else ("✓" if all_duplicates else " ")
            height_indicator = f"H+{current_scroll_height - prev_scroll_height:,}" if height_grew else ""
            stuck_indicator = f" (stuck:{stuck_count})" if stuck_count > 0 else ""
            visible_indicator = f" V:{visible_check['crawled_count']}/{visible_check['visible_count']}" if visible_check['visible_count'] > 0 else ""
            print(f"   第 {i+1:2d} 轮 | {progress_bar} | "
                  f"+{new_count:3d} 新数据 | "
                  f"重复:{duplicate_count:2d} | "
                  f"总计:{len(all_items):4d} 条 [{status_marker}] {height_indicator}{stuck_indicator}{visible_indicator}")

            # 调试信息：如果有未抓取的可见推文
            if visible_uncrawled and i > 5:
                print(f"      ⚠️ 发现 {len(visible_uncrawled)} 条可见但未抓取的推文")

            # 检查是否需要停止
            if not config.scroll_enabled:
                break

            # 判断条件：当前获取的所有推文都已经被抓取过（且确实获取到了推文）
            if len(items) > 0 and new_count == 0:
                no_new_count += 1
            else:
                no_new_count = 0
                # 有新数据时，如果之前在确认模式，退出确认模式
                if confirm_mode:
                    print(f"      📢 确认模式中断：发现 {new_count} 条新数据")
                    confirm_mode = False
                    confirm_remaining = 0

            # 执行滚动，获取滚动结果
            scroll_result = self._scroll_page(ws_url, config, step=i+1)
            hit_bottom = scroll_result.get('hitBottom', False)
            actual_scrolled = scroll_result.get('actualScrolled', 0)

            # 检查是否满足结束信号
            done_check = self._check_if_really_done(
                ws_url=ws_url,
                no_new_count=no_new_count,
                scroll_percent=scroll_percent,
                prev_scroll_top=prev_scroll_top,
                all_duplicates_in_round=all_duplicates,
                current_round=i+1,
                min_rounds=min_scroll_rounds,
                height_grew=height_grew,
                current_height=current_scroll_height,
                stuck_count=stuck_count,
                all_visible_crawled=all_visible_crawled,
                hit_bottom=hit_bottom,
                actual_scrolled=actual_scrolled,
                visible_count=visible_check.get('visible_count', 0)
            )

            # 确认模式逻辑
            if done_check['done']:
                confidence = done_check.get('confidence', 'low')
                
                if confidence == 'high':
                    # 强信号直接结束
                    print(f"   ✅ {done_check['reason']}")
                    break
                elif not confirm_mode:
                    # 中等/弱信号，进入确认模式
                    confirm_mode = True
                    confirm_remaining = confirm_rounds
                    confirm_trigger_reason = done_check['reason']
                    print(f"   ⚠️  {done_check['reason']}")
                    print(f"      进入确认模式：继续滚动 {confirm_rounds} 次确认...")
                # 如果已经在确认模式，继续确认流程
            
            # 确认模式计数
            if confirm_mode:
                if new_count == 0:
                    confirm_remaining -= 1
                    print(f"      确认中... 剩余 {confirm_remaining} 次")
                    if confirm_remaining <= 0:
                        print(f"   ✅ 确认完成：{confirm_trigger_reason}")
                        break
                # 如果有新数据，上面已经退出确认模式了

            # 更新状态，准备下一轮
            prev_scroll_top = current_scroll_top
            prev_scroll_height = current_scroll_height

        return list(all_items.values())

    def _check_if_really_done(self, ws_url: str, no_new_count: int,
                               scroll_percent: float, prev_scroll_top: float,
                               all_duplicates_in_round: bool,
                               current_round: int = 0,
                               min_rounds: int = 10,
                               height_grew: bool = False,
                               current_height: int = 0,
                               stuck_count: int = 0,
                               all_visible_crawled: bool = False,
                               hit_bottom: bool = False,
                               actual_scrolled: int = 0,
                               visible_count: int = 0) -> dict:
        """
        多重条件联合判定是否真正到达底部

        核心逻辑：必须满足【必要条件】+ 【多个充分条件】才结束

        必要条件（必须满足）：
        - 达到最小滚动次数 (current_round >= min_rounds)

        结束信号（多条件组合判定）：
        - 强信号：hitBottom + all_visible_crawled + 滚动百分比高
        - 中信号：连续多轮无新数据 + all_visible_crawled + 页面高度稳定
        - 弱信号：连续多轮无新数据 + 滚动百分比很高 + 无加载指示器

        Args:
            visible_count: 当前可见推文数量（用于判断虚拟滚动是否卸载了太多内容）

        Returns:
            {'done': bool, 'reason': str, 'confidence': 'high'|'medium'|'low'}
        """

        # === 必要条件检查 ===
        if current_round < min_rounds:
            return {'done': False, 'reason': f'未达到最小滚动次数 ({current_round}/{min_rounds})', 'confidence': 'none'}

        # 如果可见推文数量很少（虚拟滚动卸载了大部分内容），要更谨慎
        too_few_visible = visible_count <= 2 and current_round < min_rounds + 5

        # === 收集各种信号 ===
        signals = {
            'no_new_for_3_rounds': no_new_count >= 3,
            'no_new_for_2_rounds': no_new_count >= 2,
            'all_duplicates': all_duplicates_in_round,
            'height_stable': not height_grew,
            'all_visible_crawled': all_visible_crawled,
            'hit_bottom': hit_bottom,
            'high_scroll_percent': scroll_percent >= 85,
            'very_high_scroll_percent': scroll_percent >= 95,
            'stuck': stuck_count >= 2,
            'too_few_visible': too_few_visible,
            'small_scroll': actual_scrolled < 100
        }

        # === 强信号判定：几乎可以确定到底 ===
        # 必须同时满足：到底 + 所有可见已抓取 + (滚动百分比高 或 滚不动)
        if signals['hit_bottom'] and signals['all_visible_crawled']:
            if signals['high_scroll_percent'] or signals['small_scroll']:
                return {
                    'done': True,
                    'reason': f'强信号：滚动到底部(滚动{actual_scrolled}px, {scroll_percent:.1f}%)且所有可见推文已抓取({visible_count}条)',
                    'confidence': 'high'
                }

        # === 中信号判定：比较确定到底 ===
        # 必须同时满足：连续3轮无新 + 所有可见已抓取 + 页面高度稳定 + 不是太少可见
        if signals['no_new_for_3_rounds'] and signals['all_visible_crawled'] and signals['height_stable']:
            if not signals['too_few_visible']:
                return {
                    'done': True,
                    'reason': f'中信号：连续3轮无新数据，所有可见推文已抓取({visible_count}条)，页面稳定',
                    'confidence': 'medium'
                }

        # === 弱信号判定：可能到底 ===
        # 需要多个条件组合，且不能有反向信号
        weak_score = 0
        weak_conditions = [
            signals['no_new_for_2_rounds'],
            signals['all_duplicates'],
            signals['height_stable'],
            signals['high_scroll_percent'],
            signals['stuck'],
            signals['all_visible_crawled']
        ]
        weak_score = sum(weak_conditions)

        # 弱信号需要至少5个条件（以前是4个，现在提高阈值因为会进入确认模式）
        if weak_score >= 5 and not signals['too_few_visible']:
            # 额外检查：是否有加载指示器
            is_loading = self._eval_js(ws_url, """
                (function() {
                    const loaders = document.querySelectorAll([
                        '[role="progressbar"]',
                        '.loading',
                        '[data-testid="loading"]',
                        'svg[class*="loading"]',
                        'div[class*="skeleton"]'
                    ].join(','));
                    return Array.from(loaders).some(l => {
                        const rect = l.getBoundingClientRect();
                        return rect.top >= 0 && rect.top <= window.innerHeight;
                    });
                })()
            """) or False

            if not is_loading:
                return {
                    'done': True,
                    'reason': f'弱信号：满足{weak_score}/6个结束条件，无加载指示器',
                    'confidence': 'low'
                }

        # === 文本结束标记检测 ===
        end_marker = self._eval_js(ws_url, """
            (function() {
                const markers = [
                    '没有更多推文', 'No more tweets', 'End of timeline',
                    '已显示所有推文', 'All tweets shown', 'That\'s all for now',
                    'Nothing more to see', 'You\'re all caught up'
                ];
                const allText = document.body.innerText || '';
                return markers.some(m => allText.includes(m));
            })()
        """)

        if end_marker and signals['no_new_for_2_rounds']:
            return {
                'done': True,
                'reason': '检测到"没有更多推文"文本提示',
                'confidence': 'high'
            }

        # === 返回未完成的详细原因 ===
        true_signals = [k for k, v in signals.items() if v and k != 'too_few_visible']

        return {
            'done': False,
            'reason': f'条件不满足（真信号:{len(true_signals)}/9, 弱评分:{weak_score}/6）',
            'confidence': 'none'
        }

    def _make_progress_bar(self, percent: float, width: int = 20) -> str:
        """创建进度条"""
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f"[{bar}] {percent:5.1f}%"
        # 在前 min_rounds 轮，即使只看到重复内容也不停止
        # 这解决了"长推文展开后占据整个视口"的问题
        if current_round < min_rounds:
            return {'done': False, 'reason': f'未达到最小滚动次数 ({current_round}/{min_rounds})'}

        # === 视口顶部推文卡住检测 ===
        # 如果连续多轮视口顶部的推文都是同一个，说明我们可能卡在一个很长的推文里
        # 但如果页面高度还在增长，说明推文下方有新内容，不要停止
        if stuck_count >= 3 and not height_grew:
            # 尝试强制滚动到下一个推文
            forced_scroll = self._eval_js(ws_url, """
                (function() {
                    const articles = document.querySelectorAll('article[data-testid="tweet"]');
                    const viewportTop = window.pageYOffset || document.documentElement.scrollTop;

                    for (let i = 0; i < articles.length; i++) {
                        const rect = articles[i].getBoundingClientRect();
                        const articleTop = rect.top + viewportTop;

                        // 找到第一个完全在视口下方的推文，滚动到它
                        if (articleTop > viewportTop + window.innerHeight * 0.3) {
                            window.scrollTo({
                                top: articleTop,
                                behavior: 'smooth'
                            });
                            return {scrolled: true, target: i};
                        }
                    }
                    return {scrolled: false};
                })()
            """) or {}

            if forced_scroll.get('scrolled'):
                return {'done': False, 'reason': f'尝试强制滚动到下一个推文'}

        # === 页面高度还在增长 ===
        # 如果页面总高度还在增加，说明有新内容在加载，不要停止
        if height_grew:
            return {'done': False, 'reason': '页面高度仍在增长，继续滚动'}

        # === 检测是否在加载中 ===
        is_loading = self._eval_js(ws_url, """
            (function() {
                // 检查各种加载指示器
                const loaders = document.querySelectorAll([
                    '[role="progressbar"]',
                    '.loading',
                    '[data-testid="loading"]',
                    'svg[class*="loading"]',
                    'div[class*="skeleton"]',
                    '[data-testid="trend"]'
                ].join(','));
                const hasVisibleLoader = Array.from(loaders).some(l => {
                    const rect = l.getBoundingClientRect();
                    return rect.top >= 0 && rect.top <= window.innerHeight;
                });

                // 检查是否有"加载更多"按钮
                const loadMoreBtns = document.querySelectorAll('span, button');
                let hasLoadMore = false;
                for (const btn of loadMoreBtns) {
                    const text = (btn.innerText || '').toLowerCase();
                    if (text.includes('load more') || text.includes('加载更多') ||
                        text.includes('show more replies') || text.includes('显示更多回复')) {
                        hasLoadMore = true;
                        break;
                    }
                }

                return {isLoading: hasVisibleLoader, hasLoadMore: hasLoadMore};
            })()
        """) or {}

        if is_loading.get('isLoading'):
            return {'done': False, 'reason': '检测到加载指示器'}

        if is_loading.get('hasLoadMore'):
            return {'done': False, 'reason': '检测到"加载更多"按钮'}

        # === 条件1: 连续多次所有推文都是重复的 + 页面高度稳定 ===
        # 注意：需要在达到最小滚动次数后才判断
        if no_new_count >= 3 and all_duplicates_in_round and not height_grew:
            # 再次检查滚动位置是否变化（等待一小段时间）
            time.sleep(0.5)
            new_info = self._get_scroll_info(ws_url)
            new_scroll_top = new_info.get('scrollTop', 0)

            # 如果滚动位置还在变化，说明正在滚动长推文内部
            if abs(new_scroll_top - prev_scroll_top) > 50:
                return {'done': False, 'reason': '滚动位置仍在变化，可能正在长推文内部滚动'}

            return {'done': True, 'reason': f'连续{no_new_count}轮无新数据且页面高度稳定'}

        # === 条件2: 滚动百分比很高 + 连续多次所有推文都是重复的 ===
        if scroll_percent >= 95 and no_new_count >= 2 and all_duplicates_in_round and not height_grew:
            return {'done': True, 'reason': f'已滚动到{scroll_percent:.1f}%且连续{no_new_count}轮无新数据'}

        # === 条件3: 滚动到底部 + 所有可见推文都已抓取 + 滚不动 ===
        # 这是最强的完成信号：页面滚不动了，且所有可见内容都已抓取
        if hit_bottom and all_visible_crawled and actual_scrolled < 100:
            return {'done': True, 'reason': f'滚动到底部且所有可见推文已抓取（实际滚动{actual_scrolled}px）'}

        # === 条件4: 滚动到底部 + 连续多轮无新数据 ===
        if hit_bottom and no_new_count >= 2 and all_duplicates_in_round:
            return {'done': True, 'reason': f'滚动到底部且连续{no_new_count}轮无新数据'}

        # === 条件5: 所有可见推文都已抓取 + 页面高度稳定 + 连续多轮无新数据 ===
        if all_visible_crawled and not height_grew and no_new_count >= 2:
            return {'done': True, 'reason': f'所有可见推文已抓取（{visible_check["visible_count"] if "visible_check" in dir() else "N"}条）且页面稳定'}

        # === 条件6: 检查是否出现"没有更多推文"的提示 ===
        end_marker = self._eval_js(ws_url, """
            (function() {
                const markers = [
                    '没有更多推文', 'No more tweets', 'End of timeline',
                    '已显示所有推文', 'All tweets shown', 'That\'s all for now'
                ];
                const allText = document.body.innerText || '';
                return markers.some(m => allText.includes(m));
            })()
        """)

        if end_marker:
            return {'done': True, 'reason': '检测到"没有更多推文"提示'}

        return {'done': False, 'reason': ''}

    def _make_progress_bar(self, percent: float, width: int = 20) -> str:
        """创建进度条"""
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f"[{bar}] {percent:5.1f}%"
        """创建进度条"""
        filled = int(width * percent / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f"[{bar}] {percent:5.1f}%"

    def _download_via_chrome(self, ws_url: str, url: str, save_path: Path) -> bool:
        """
        通过 Chrome 下载文件（复用当前页面的 Cookie 和认证）

        Args:
            ws_url: WebSocket 调试 URL
            url: 要下载的文件 URL
            save_path: 保存路径

        Returns:
            是否下载成功
        """
        try:
            import base64
            import websocket

            # 使用 Chrome 的 Fetch 或 Network 域来获取资源
            # 方法：通过 Network.loadNetworkResource 或执行 JS 获取 blob
            js_code = f"""
            (async function() {{
                try {{
                    const response = await fetch('{url}', {{
                        credentials: 'include',
                        headers: {{
                            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
                        }}
                    }});
                    if (response.ok) {{
                        const blob = await response.blob();
                        const reader = new FileReader();
                        return new Promise((resolve) => {{
                            reader.onloadend = () => resolve(reader.result);
                            reader.readAsDataURL(blob);
                        }});
                    }}
                    return null;
                }} catch(e) {{
                    return null;
                }}
            }})()
            """

            result = self._eval_js(ws_url, js_code, timeout=60)

            if result and result.startswith('data:'):
                # 解码 base64 数据
                base64_data = result.split(',')[1]
                binary_data = base64.b64decode(base64_data)

                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, 'wb') as f:
                    f.write(binary_data)
                return True

        except Exception as e:
            print(f"      ⚠️ 下载失败 {url}: {e}")

        return False

    def download_media(self, data: List[Dict], media_field: str = 'image_urls',
                       output_subdir: str = 'media') -> Dict[str, int]:
        """
        下载推文中包含的媒体文件

        Args:
            data: 抓取的数据列表
            media_field: 包含媒体URL的字段名
            output_subdir: 媒体文件保存子目录

        Returns:
            下载统计信息 {'success': x, 'failed': y}
        """
        print(f"\n📥 开始下载媒体文件...")

        media_dir = self.output_dir / output_subdir
        media_dir.mkdir(exist_ok=True)

        stats = {'success': 0, 'failed': 0}

        for item in data:
            urls_str = item.get(media_field, '')
            if not urls_str:
                continue

            # 处理可能的多URL（逗号分隔）
            urls = [u.strip() for u in str(urls_str).split(',') if u.strip()]

            for url in urls:
                # 从 URL 提取文件名
                from urllib.parse import urlparse
                parsed = urlparse(url)
                filename = parsed.path.split('/')[-1] or 'unknown'

                # 如果没有扩展名，添加 .jpg
                if '.' not in filename:
                    filename += '.jpg'

                # 添加推文ID前缀，避免重名
                tweet_id = str(item.get('id', 'unknown'))[:20]
                filename = f"{tweet_id}_{filename}"

                save_path = media_dir / filename

                # 如果文件已存在，跳过
                if save_path.exists():
                    print(f"      ⏭️ 已存在: {filename}")
                    stats['success'] += 1
                    continue

                print(f"      下载: {filename}")

                # 尝试通过 Chrome 下载
                # 注意：这里需要 ws_url，但数据已经提取完了
                # 所以需要修改逻辑，或者在提取时同时下载
                # 简化方案：直接 requests 下载，添加 headers
                try:
                    import requests
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                        'Referer': 'https://x.com/'
                    }
                    resp = requests.get(url, headers=headers, timeout=30)
                    if resp.status_code == 200:
                        with open(save_path, 'wb') as f:
                            f.write(resp.content)
                        stats['success'] += 1
                    else:
                        stats['failed'] += 1
                        print(f"      ❌ HTTP {resp.status_code}")
                except Exception as e:
                    stats['failed'] += 1
                    print(f"      ❌ 错误: {e}")

        print(f"\n📊 下载完成: {stats['success']} 成功, {stats['failed']} 失败")
        print(f"   保存位置: {media_dir}")

        return stats

    def save(self, data: List[Dict], name: str, config: ExtractorConfig = None):
        """
        保存数据到多种格式
        流程: 1. 保存原始JSON 2. 从JSON生成CSV 3. 从JSON生成Markdown
        """
        if not data:
            print("❌ 没有数据可保存")
            return

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f"{name}_{timestamp}"

        # 排序
        if config and config.sort_field:
            from datetime import datetime as dt
            
            def get_sort_key(item):
                value = item.get(config.sort_field, '')
                if not value:
                    return ''
                
                # 尝试解析 ISO 8601 时间格式 (2024-02-06T15:30:00.000Z)
                if isinstance(value, str):
                    # 尝试多种时间格式
                    time_formats = [
                        '%Y-%m-%dT%H:%M:%S.%fZ',
                        '%Y-%m-%dT%H:%M:%SZ',
                        '%Y-%m-%dT%H:%M:%S.%f%z',
                        '%Y-%m-%dT%H:%M:%S%z',
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%d'
                    ]
                    for fmt in time_formats:
                        try:
                            parsed = dt.strptime(value, fmt)
                            # 返回时间戳用于排序
                            return parsed.timestamp()
                        except ValueError:
                            continue
                
                # 如果无法解析为时间，按原值字符串排序
                return str(value)
            
            data.sort(key=get_sort_key, reverse=config.sort_reverse)

        # ===== 1. 保存原始 JSON（最权威的数据源） =====
        json_file = self.output_dir / f"{base_name}.json"
        json_content = {
            'source': name,
            'crawled_at': datetime.now().isoformat(),
            'count': len(data),
            'data': data
        }
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(json_content, f, ensure_ascii=False, indent=2)

        # ===== 2. 从 JSON 生成 CSV（简化格式） =====
        csv_file = self.output_dir / f"{base_name}.csv"
        self._generate_csv_from_json(json_content, csv_file, config)

        # ===== 3. 从 JSON 生成 Markdown（可读格式） =====
        md_file = self.output_dir / f"{base_name}.md"
        self._generate_md_from_json(json_content, md_file, name)

        print(f"\n✅ 已保存:")
        print(f"   📄 JSON (原始数据): {json_file}")
        print(f"   📊 CSV (表格视图): {csv_file}")
        print(f"   📝 Markdown (可读格式): {md_file}")

        return json_file, csv_file, md_file

    def _generate_csv_from_json(self, json_content: Dict, csv_file: Path, config: ExtractorConfig = None):
        """从 JSON 内容生成 CSV 文件"""
        data = json_content.get('data', [])
        if not data:
            return

        import csv

        # 定义 CSV 要包含的字段（优先使用配置，否则使用数据中所有字段）
        if config and config.field_selectors:
            # 只包含配置中定义的字段 + 媒体相关字段
            base_fields = list(config.field_selectors.keys())
            media_fields = ['image_count', 'has_video', 'image_urls']
            fieldnames = [f for f in (base_fields + media_fields) if f in data[0] or f in media_fields]
        else:
            # 使用数据中所有字段，但排除内部字段
            fieldnames = [k for k in data[0].keys() if not k.startswith('_')]

        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()

            for item in data:
                # 创建 CSV 行，处理长文本截断
                row = {}
                for field in fieldnames:
                    value = item.get(field, '')
                    # 文本字段截断，避免 CSV 过长
                    if field in ['text', 'content'] and isinstance(value, str) and len(value) > 500:
                        value = value[:497] + '...'
                    row[field] = value
                writer.writerow(row)

    def _generate_md_from_json(self, json_content: Dict, md_file: Path, name: str):
        """从 JSON 内容生成 Markdown 文件"""
        data = json_content.get('data', [])
        meta = {
            'source': json_content.get('source', name),
            'crawled_at': json_content.get('crawled_at', ''),
            'count': json_content.get('count', 0)
        }

        with open(md_file, 'w', encoding='utf-8') as f:
            # 标题和元信息
            f.write(f"# {meta['source']} 数据\n\n")
            f.write(f"- **抓取时间**: {meta['crawled_at'][:19].replace('T', ' ')}\n")
            f.write(f"- **数据条数**: {meta['count']}\n")
            f.write(f"- **原始数据**: 见同名 `.json` 文件\n\n")
            f.write("---\n\n")

            # 只展示前 100 条
            display_count = min(len(data), 100)
            for i, item in enumerate(data[:display_count], 1):
                # 标题：优先使用 text 字段前 50 字
                title_text = item.get('text', item.get('title', '无标题'))[:50]
                if len(item.get('text', '')) > 50:
                    title_text += '...'

                f.write(f"### {i}. {title_text}\n\n")

                # 内容字段
                if 'text' in item:
                    f.write(f"**内容**:\n```\n{item['text']}\n```\n\n")

                # 其他字段表格
                other_fields = {k: v for k, v in item.items()
                               if not k.startswith('_') and k != 'text' and v}
                if other_fields:
                    f.write("| 字段 | 内容 |\n|------|------|\n")
                    for key, value in list(other_fields.items())[:10]:  # 最多显示10个字段
                        value_str = str(value)[:100]  # 截断长内容
                        if len(str(value)) > 100:
                            value_str += '...'
                        f.write(f"| {key} | {value_str} |\n")
                    f.write("\n")

                f.write("---\n\n")

            if len(data) > 100:
                f.write(f"\n> 共 {len(data)} 条数据，此处仅展示前 100 条。完整数据请查看 JSON 文件。\n")


# ============ 预设配置 ============

class Presets:
    """常用网站预设配置"""

    @staticmethod
    def twitter(username: str, download_media: bool = False) -> ExtractorConfig:
        """Twitter/X 推文抓取"""

        def extract_full_text(element_html: str) -> str:
            """提取完整推文文本，处理展开后的长文本"""
            return element_html.strip()

        return ExtractorConfig(
            name=f"Twitter @{username}",
            url_pattern=rf"x\.com/{username}",
            item_selector='article[data-testid="tweet"]',
            field_selectors={
                'id': 'a[href*="/status/"]',
                'text': '[data-testid="tweetText"]',
                'time': 'time',
                'author': 'div[data-testid="User-Name"] a',
                'likes': '[data-testid="like"]',
                'replies': '[data-testid="reply"]',
                'retweets': '[data-testid="retweet"]'
            },
            scroll_delay=2.5,
            expand_selectors=[
                '[data-testid="tweet-text-show-more-link"]',
            ],
            expand_delay=1.5,
            download_media=download_media,
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
            }
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
        # 使用用户名作为文件名前缀
        preset = username
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
