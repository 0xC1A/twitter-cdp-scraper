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
    scroll_times: int = 50             # 最大滚动次数
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
    
    def _scroll_page(self, ws_url: str, config: ExtractorConfig, step: int = 1):
        """
        滚动页面 - 使用小步长滚动避免虚拟滚动导致的数据丢失
        
        Args:
            step: 滚动步数，每次滚动一屏的一部分
        """
        # 计算滚动距离：视口高度的 70%，确保有重叠区域
        js_code = """
        (function() {
            const viewportHeight = window.innerHeight;
            const scrollDistance = Math.floor(viewportHeight * 0.7);
            const currentScroll = window.pageYOffset || document.documentElement.scrollTop;
            
            window.scrollTo({
                top: currentScroll + scrollDistance,
                behavior: 'smooth'
            });
            
            return {
                scrolled: scrollDistance,
                viewportHeight: viewportHeight,
                newPosition: currentScroll + scrollDistance,
                pageHeight: document.body.scrollHeight
            };
        })()
        """
        
        result = self._eval_js(ws_url, js_code)
        time.sleep(config.scroll_delay)
        return result
    
    def _get_scroll_info(self, ws_url: str) -> dict:
        """获取当前滚动信息"""
        js_code = """
        (function() {
            return {
                scrollTop: window.pageYOffset || document.documentElement.scrollTop,
                scrollHeight: document.body.scrollHeight,
                viewportHeight: window.innerHeight,
                scrollPercent: ((window.pageYOffset || document.documentElement.scrollTop) / 
                               (document.body.scrollHeight - window.innerHeight) * 100).toFixed(1)
            };
        })()
        """
        return self._eval_js(ws_url, js_code) or {}
    
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
            
            field_extractors.append(f"""
                // {field_name}
                try {{
                    const {field_name}El = article.querySelector('{selector}');
                    if ({field_name}El) {{
                        let text = '';
                        
                        // 对于 id/url/link 字段，优先获取 href
                        if ({str(prefer_href).lower()}) {{
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
        print(f"   滚动策略: 小步长滚动 + 即时提取（应对虚拟滚动）")
        print(f"   最大滚动次数: {config.scroll_times}")
        
        all_items = {}
        ws_url = page['ws_url']
        no_new_count = 0  # 连续没有新数据的次数
        prev_scroll_top = 0
        
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
        
        for i in range(config.scroll_times if config.scroll_enabled else 1):
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
            
            # 显示进度
            progress_bar = self._make_progress_bar(scroll_percent)
            all_duplicates = len(items) > 0 and new_count == 0  # 当前获取的所有推文都是重复的
            status_marker = "✓" if all_duplicates else " "
            print(f"   第 {i+1:2d} 轮 | {progress_bar} | "
                  f"+{new_count:3d} 新数据 | "
                  f"重复:{duplicate_count:2d} | "
                  f"总计:{len(all_items):4d} 条 [{status_marker}]")
            
            # 检查是否需要停止
            if not config.scroll_enabled:
                break
            
            # 判断条件：当前获取的所有推文都已经被抓取过（且确实获取到了推文）
            if len(items) > 0 and new_count == 0:
                no_new_count += 1
            else:
                no_new_count = 0
            
            # 使用多重检测判断是否真正完成
            done_check = self._check_if_really_done(
                ws_url, no_new_count, scroll_percent, prev_scroll_top, all_duplicates
            )
            
            if done_check['done']:
                print(f"   ✅ {done_check['reason']}")
                break
            
            # 小步长滚动
            prev_scroll_top = current_scroll_top
            self._scroll_page(ws_url, config, step=i+1)
        
        return list(all_items.values())
    
    def _check_if_really_done(self, ws_url: str, no_new_count: int, 
                               scroll_percent: float, prev_scroll_top: float,
                               all_duplicates_in_round: bool) -> dict:
        """
        多重检测判断是否真正到达底部
        
        Args:
            no_new_count: 连续N轮所有推文都是重复的次数
            all_duplicates_in_round: 当前轮次所有推文是否都是重复的
            
        Returns:
            {
                'done': bool,
                'reason': str
            }
        """
        # 条件1: 连续多次所有推文都是重复的 + 滚动位置不再变化
        if no_new_count >= 3 and all_duplicates_in_round:
            current_info = self._get_scroll_info(ws_url)
            current_scroll_top = current_info.get('scrollTop', 0)
            
            # 等待一小段时间再检查，看是否有新内容加载
            time.sleep(0.5)
            new_info = self._get_scroll_info(ws_url)
            new_scroll_top = new_info.get('scrollTop', 0)
            
            # 如果滚动位置基本不变，说明真的到底了
            if abs(new_scroll_top - current_scroll_top) < 10:
                # 再检查一次DOM中是否有加载指示器
                has_loader = self._eval_js(ws_url, """
                    (function() {
                        // 检查各种加载指示器
                        const loaders = document.querySelectorAll([
                            '[role="progressbar"]',
                            '.loading',
                            '[data-testid="loading"]',
                            'svg[class*="loading"]',
                            'div[class*="skeleton"]'
                        ].join(','));
                        return loaders.length > 0 && 
                               Array.from(loaders).some(l => l.offsetParent !== null);
                    })()
                """)
                
                if not has_loader:
                    return {'done': True, 'reason': f'连续{no_new_count}轮所有推文都是重复的且页面停止加载'}
        
        # 条件2: 滚动百分比很高 + 连续多次所有推文都是重复的
        if scroll_percent >= 95 and no_new_count >= 2 and all_duplicates_in_round:
            return {'done': True, 'reason': f'已滚动到{scroll_percent:.1f}%且连续{no_new_count}轮所有推文都是重复的'}
        
        # 条件3: 检查是否出现"没有更多推文"的提示
        end_marker = self._eval_js(ws_url, """
            (function() {
                // 检查各种可能的结束提示
                const markers = [
                    '没有更多推文',
                    'No more tweets',
                    'End of timeline',
                    '已显示所有推文',
                    'All tweets shown'
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
            data.sort(key=lambda x: x.get(config.sort_field, ''), 
                     reverse=config.sort_reverse)
        
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
            scroll_times=50,
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
