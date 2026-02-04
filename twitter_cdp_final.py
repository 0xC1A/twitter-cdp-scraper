#!/usr/bin/env python3
"""
Twitter/X CDP 抓取工具 - 用户执行版
通过 Chrome DevTools Protocol 控制已登录的浏览器抓取推文

使用方法：
1. 启动 Chrome with remote debugging (见下方 START_CHROME 说明)
2. 在 Chrome 中登录 Twitter/X
3. 访问目标用户主页
4. 运行本脚本

作者: 0xC1A
日期: 2026-02-04
"""

import json
import requests
import time
import sys
from datetime import datetime
from pathlib import Path

# ============ 配置 ============
CHROME_PORT = 9222
OUTPUT_DIR = Path('twitter_cdp_exports')
MAX_SCROLLS = 100  # 最大滚动次数
SCROLL_DELAY = 2   # 每次滚动后等待时间(秒)
# =============================

def check_chrome_connection():
    """检查 Chrome DevTools 是否可用"""
    try:
        resp = requests.get(f'http://localhost:{CHROME_PORT}/json/version', timeout=5)
        if resp.status_code == 200:
            version = resp.json()
            return True, version.get('Browser', 'unknown')
    except:
        pass
    return False, None

def get_twitter_page():
    """获取 Twitter/X 页面的 WebSocket URL"""
    try:
        resp = requests.get(f'http://localhost:{CHROME_PORT}/json/list', timeout=10)
        pages = resp.json()
        
        for p in pages:
            url = p.get('url', '')
            # 查找 x.com 域名，排除 devtools 页面
            if ('x.com' in url or 'twitter.com' in url) and 'devtools' not in url:
                return {
                    'id': p['id'],
                    'url': url,
                    'ws_url': p['webSocketDebuggerUrl'],
                    'title': p.get('title', 'Unknown')
                }
    except Exception as e:
        print(f"❌ 获取页面列表失败: {e}")
    return None

def eval_js(ws_url, js_code, timeout=30):
    """通过 WebSocket 执行 JavaScript"""
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
        print(f"  ⚠️ JS 执行出错: {e}")
    return None

def expand_collapsed_tweets(ws_url):
    """点击所有 "Show more" 按钮展开折叠的推文"""
    js_code = """
    (function() {
        // 查找所有 "Show more" 按钮
        const buttons = document.querySelectorAll('button[role="button"]');
        let clicked = 0;
        
        buttons.forEach(btn => {
            const text = btn.innerText || btn.textContent || '';
            // 匹配 "Show more" 或中文 "显示更多"
            if (text.match(/show more|显示更多/i)) {
                btn.click();
                clicked++;
            }
        });
        
        // 也尝试通过 aria-label 查找
        const altButtons = document.querySelectorAll('[aria-label*="Show more"], [aria-label*="显示更多"]');
        altButtons.forEach(btn => {
            if (!btn.clicked) {
                btn.click();
                clicked++;
            }
        });
        
        return 'Clicked ' + clicked + ' "Show more" buttons';
    })()
    """
    result = eval_js(ws_url, js_code)
    if result:
        print(f"      {result}")
    time.sleep(1)  # 等待展开动画

def extract_tweets_from_page(ws_url):
    """从当前页面提取所有推文数据"""
    
    # 先展开所有折叠的推文
    expand_collapsed_tweets(ws_url)
    
    js_code = """
    (function() {
        const tweets = [];
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        
        articles.forEach(article => {
            try {
                const tweet = {};
                
                // 推文 ID 和 URL
                const statusLink = article.querySelector('a[href*="/status/"]');
                if (statusLink) {
                    const href = statusLink.getAttribute('href');
                    const match = href.match(/\\/status\\/(\\d+)/);
                    if (match) {
                        tweet.id = match[1];
                        tweet.url = 'https://x.com' + href;
                    }
                }
                
                if (!tweet.id) return; // 跳过无效条目
                
                // 作者信息
                const userNameDiv = article.querySelector('div[data-testid="User-Name"]');
                if (userNameDiv) {
                    const userLink = userNameDiv.querySelector('a');
                    if (userLink) {
                        const href = userLink.getAttribute('href');
                        if (href) tweet.author = href.split('/')[1];
                    }
                    // 显示名称
                    const nameSpan = userNameDiv.querySelector('span span');
                    if (nameSpan) tweet.author_name = nameSpan.innerText;
                }
                
                // 推文内容 - 尝试多种方式获取完整文本
                let textContent = '';
                
                // 方法1: 通过 tweetText 数据属性
                const textDiv = article.querySelector('[data-testid="tweetText"]');
                if (textDiv) {
                    // 获取所有文本节点，包括被折叠的部分
                    textContent = textDiv.innerText || textDiv.textContent || '';
                    
                    // 如果内容被截断，尝试获取完整内容
                    // Twitter 有时会将完整文本放在 aria-label 中
                    if (textContent.length < 100 && textDiv.getAttribute('aria-label')) {
                        const ariaText = textDiv.getAttribute('aria-label');
                        if (ariaText.length > textContent.length) {
                            textContent = ariaText;
                        }
                    }
                }
                
                // 方法2: 尝试获取所有 span 中的文本（有时推文分散在多个 span 中）
                if (!textContent) {
                    const spans = article.querySelectorAll('span');
                    let combinedText = '';
                    spans.forEach(span => {
                        const txt = span.innerText || span.textContent;
                        if (txt && txt.length > 10 && !txt.includes('@')) {
                            combinedText += txt + ' ';
                        }
                    });
                    if (combinedText.length > 50) {
                        textContent = combinedText.trim();
                    }
                }
                
                tweet.text = textContent;
                
                // 发布时间
                const timeElem = article.querySelector('time');
                tweet.created_at = timeElem ? timeElem.getAttribute('datetime') : '';
                
                // 互动数据 (回复/转发/点赞)
                const actions = ['reply', 'retweet', 'like'];
                actions.forEach(action => {
                    const btn = article.querySelector(`[data-testid="${action}"]`);
                    if (btn) {
                        const ariaLabel = btn.getAttribute('aria-label') || '';
                        // 提取数字，处理 "5,231 likes" 格式
                        const match = ariaLabel.replace(/,/g, '').match(/(\\d+)/);
                        tweet[action + '_count'] = match ? parseInt(match[1]) : 0;
                    } else {
                        tweet[action + '_count'] = 0;
                    }
                });
                
                // 是否回复别人的推文
                const replyContext = article.querySelector('[data-testid="socialContext"]');
                tweet.is_reply = !!replyContext;
                if (replyContext) {
                    tweet.reply_to_text = replyContext.innerText;
                }
                
                // 媒体文件
                const photos = article.querySelectorAll('[data-testid="tweetPhoto"]');
                const videos = article.querySelectorAll('[data-testid="tweetVideo"]');
                tweet.media_count = photos.length + videos.length;
                tweet.has_media = tweet.media_count > 0;
                
                // 引用推文 (Quote Tweet)
                const quoted = article.querySelector('[data-testid="quotedTweet"]');
                if (quoted) {
                    const quotedText = quoted.querySelector('[data-testid="tweetText"]');
                    const quotedAuthor = quoted.querySelector('div[data-testid="User-Name"] span');
                    tweet.quoted_tweet = {
                        'text': quotedText ? quotedText.innerText.substring(0, 200) : '',
                        'author': quotedAuthor ? quotedAuthor.innerText : ''
                    };
                }
                
                tweets.push(tweet);
            } catch(e) {
                // 忽略单个推文提取错误
            }
        });
        
        return {
            'count': tweets.length,
            'tweets': tweets
        };
    })()
    """
    
    result = eval_js(ws_url, js_code)
    if result and isinstance(result, dict):
        return result.get('tweets', [])
    return []

def scroll_page_down(ws_url, times=1):
    """向下滚动页面"""
    for i in range(times):
        eval_js(ws_url, """
            window.scrollTo({
                top: document.body.scrollHeight,
                behavior: 'smooth'
            });
        """)
        time.sleep(SCROLL_DELAY)

def scrape_tweets(username, max_scrolls=MAX_SCROLLS):
    """
    主抓取函数
    
    Args:
        username: Twitter 用户名 (不含 @)
        max_scrolls: 最大滚动次数
    """
    print("=" * 70)
    print(f"🐦 Twitter CDP 抓取工具")
    print(f"   目标用户: @{username}")
    print("=" * 70)
    
    # 步骤 1: 检查 Chrome 连接
    print("\n📡 步骤 1: 检查 Chrome DevTools 连接...")
    connected, browser_version = check_chrome_connection()
    
    if not connected:
        print("❌ 无法连接到 Chrome")
        print("\n请按以下步骤操作:\n")
        print("1️⃣  关闭所有 Chrome 窗口")
        print("2️⃣  在终端运行以下命令启动 Chrome:\n")
        print(f"""
/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
    --remote-debugging-port={CHROME_PORT} \\
    --remote-allow-origins='*' \\
    --user-data-dir=/tmp/chrome_dev_profile
""")
        print("3️⃣  在 Chrome 中登录 Twitter/X")
        print(f"4️⃣  访问 https://x.com/{username}")
        print("5️⃣  重新运行本脚本\n")
        return []
    
    print(f"✅ 已连接到 Chrome ({browser_version})")
    
    # 步骤 2: 查找 Twitter 页面
    print("\n📄 步骤 2: 查找 Twitter 页面...")
    page_info = get_twitter_page()
    
    if not page_info:
        print("❌ 未找到 Twitter/X 页面")
        print(f"\n请在 Chrome 中访问: https://x.com/{username}")
        return []
    
    print(f"✅ 找到页面: {page_info['title']}")
    print(f"   URL: {page_info['url'][:60]}...")
    
    ws_url = page_info['ws_url']
    
    # 步骤 3: 开始抓取
    print(f"\n🔍 步骤 3: 开始抓取推文...")
    print(f"   最大滚动次数: {max_scrolls}")
    print(f"   每次滚动等待: {SCROLL_DELAY}秒")
    print()
    
    all_tweets = {}  # 用字典去重
    no_new_count = 0  # 连续无新数据的次数
    
    for scroll_num in range(max_scrolls):
        # 提取当前页面的推文
        tweets = extract_tweets_from_page(ws_url)
        
        new_count = 0
        for t in tweets:
            tid = t.get('id')
            if tid and tid not in all_tweets:
                all_tweets[tid] = t
                new_count += 1
        
        total = len(all_tweets)
        
        # 每 5 次滚动或发现新数据时显示进度
        if scroll_num % 5 == 0 or new_count > 0:
            print(f"   滚动 {scroll_num:3d}/{max_scrolls}: +{new_count:2d} 条新推文 | 总计: {total} 条")
        
        # 检查是否还有更多内容
        if new_count == 0:
            no_new_count += 1
            if no_new_count >= 3:  # 连续 3 次无新数据
                print(f"\n✅ 没有更多推文了，停止抓取")
                break
        else:
            no_new_count = 0
        
        # 向下滚动
        scroll_page_down(ws_url, times=1)
    
    return list(all_tweets.values())

def save_results(username, tweets):
    """保存抓取结果到多种格式"""
    if not tweets:
        print("❌ 没有数据可保存")
        return None
    
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 按时间排序
    tweets.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    # 统计数据
    stats = {
        'total': len(tweets),
        'original': sum(1 for t in tweets if not t.get('is_reply')),
        'replies': sum(1 for t in tweets if t.get('is_reply')),
        'with_media': sum(1 for t in tweets if t.get('has_media')),
        'total_likes': sum(t.get('like_count', 0) for t in tweets)
    }
    
    print(f"\n📊 统计结果:")
    print(f"   总计推文: {stats['total']} 条")
    print(f"   原创推文: {stats['original']} 条")
    print(f"   回复: {stats['replies']} 条")
    print(f"   带媒体: {stats['with_media']} 条")
    print(f"   总点赞: {stats['total_likes']}")
    
    # 1. 保存完整 JSON
    json_file = OUTPUT_DIR / f'{username}_cdp_{timestamp}.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'username': username,
            'scraped_at': datetime.now().isoformat(),
            'stats': stats,
            'tweets': tweets
        }, f, ensure_ascii=False, indent=2)
    
    # 2. 保存 Markdown
    md_file = OUTPUT_DIR / f'{username}_cdp_{timestamp}.md'
    with open(md_file, 'w', encoding='utf-8') as f:
        f.write(f"# @{username} 的推文存档\n\n")
        f.write(f"抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"推文数量: {stats['total']} 条\n\n")
        f.write(f"- 原创: {stats['original']} 条\n")
        f.write(f"- 回复: {stats['replies']} 条\n")
        f.write(f"- 带媒体: {stats['with_media']} 条\n\n")
        f.write("---\n\n")
        
        for i, t in enumerate(tweets, 1):
            date = t.get('created_at', '')[:10] if t.get('created_at') else '未知'
            text = t.get('text', '').strip()
            url = t.get('url', '')
            author = t.get('author', username)
            
            # 标记
            is_reply = t.get('is_reply', False)
            has_media = t.get('has_media', False)
            mark = '💬' if is_reply else '📝'
            media_mark = '📎' if has_media else ''
            
            f.write(f"### {i}. {mark} {media_mark} [{date}]({url})\n\n")
            
            # 推文内容
            for line in text.split('\n'):
                f.write(f"> {line}\n")
            
            f.write(f"\n")
            f.write(f"👤 @{author}  ")
            f.write(f"👍 {t.get('like_count', 0)}  ")
            f.write(f"💬 {t.get('reply_count', 0)}  ")
            f.write(f"🔄 {t.get('retweet_count', 0)}\n\n")
            
            # 引用推文
            if t.get('quoted_tweet'):
                qt = t['quoted_tweet']
                f.write(f"> 💬 引用 @{qt.get('author', 'unknown')}: {qt.get('text', '')[:100]}...\n\n")
            
            f.write("---\n\n")
    
    # 3. 保存 CSV
    csv_file = OUTPUT_DIR / f'{username}_cdp_{timestamp}.csv'
    import csv
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['序号', '日期', '作者', '内容', 'URL', '是否回复', '点赞', '回复', '转发', '媒体'])
        for i, t in enumerate(tweets, 1):
            writer.writerow([
                i,
                t.get('created_at', ''),
                t.get('author', ''),
                t.get('text', '').replace('\n', ' '),
                t.get('url', ''),
                '是' if t.get('is_reply') else '否',
                t.get('like_count', 0),
                t.get('reply_count', 0),
                t.get('retweet_count', 0),
                '是' if t.get('has_media') else '否'
            ])
    
    print(f"\n✅ 文件已保存:")
    print(f"   📄 JSON: {json_file}")
    print(f"   📝 Markdown: {md_file}")
    print(f"   📊 CSV: {csv_file}")
    
    return json_file

def main():
    """主函数"""
    # 获取用户名
    if len(sys.argv) > 1:
        username = sys.argv[1].lstrip('@')
    else:
        username = input("请输入 Twitter 用户名 (不含 @): ").strip().lstrip('@')
    
    if not username:
        print("❌ 用户名不能为空")
        return
    
    # 检查依赖
    try:
        import websocket
    except ImportError:
        print("📦 安装依赖: websocket-client...")
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', 'websocket-client', '-q'])
        print("✅ 依赖安装完成，请重新运行脚本\n")
        return
    
    # 执行抓取
    tweets = scrape_tweets(username)
    
    if tweets:
        save_results(username, tweets)
        
        # 显示最新 5 条
        print(f"\n📝 最新 5 条推文:")
        for t in tweets[:5]:
            date = t.get('created_at', '')[:10] if t.get('created_at') else '未知'
            text = t.get('text', '')[:60].replace('\n', ' ')
            mark = '💬' if t.get('is_reply') else '📝'
            print(f"   {mark} [{date}] {text}...")
        
        print(f"\n🎉 完成! 数据保存在: {OUTPUT_DIR}/")
    else:
        print("\n❌ 未能抓取到推文")
        print("\n可能的原因:")
        print("   1. Chrome 未开启 remote debugging")
        print("   2. 未在 Chrome 中登录 Twitter")
        print("   3. 目标用户不存在或推文受保护")

if __name__ == '__main__':
    main()
