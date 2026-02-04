#!/usr/bin/env python3
"""
CDP Spider 使用示例 - 自定义抓取器
展示如何为任意网站编写抓取配置
"""

from cdp_spider import CDPSpider, ExtractorConfig
import re


def scrape_custom_site():
    """
    示例：抓取自定义网站
    只需配置选择器，无需写复杂代码
    """
    
    # 定义你的抓取配置
    config = ExtractorConfig(
        # 基本信息
        name="我的目标网站",
        url_pattern=r"example\.com/list",  # 匹配页面 URL
        
        # 列表项选择器 - 每个数据项的容器
        item_selector='.list-item',  # CSS 选择器
        
        # 字段选择器 - 从每个 item 中提取的字段
        field_selectors={
            'title': 'h2.title a',           # 标题
            'link': 'h2.title a',            # 链接 (会取 href 属性)
            'author': '.author-name',        # 作者
            'date': '.publish-time',         # 发布时间
            'views': '.view-count',          # 浏览量
            'content': '.summary',           # 内容摘要
        },
        
        # 滚动配置
        scroll_enabled=True,      # 启用滚动加载
        scroll_times=30,          # 最多滚动 30 次
        scroll_delay=2,           # 每次滚动间隔 2 秒
        
        # 展开配置 - 如果有"显示更多"按钮
        expand_selectors=[
            '.show-more-button',           # "显示更多" 按钮
            '[data-action="expand"]',      # 或者其他展开元素
        ],
        expand_delay=1.5,          # 展开后等待 1.5 秒
        
        # 数据处理
        id_field='link',           # 用链接作为唯一标识去重
        sort_field='date',         # 按日期排序
        sort_reverse=True,         # 倒序 (最新的在前)
    )
    
    # 创建 spider 并执行
    spider = CDPSpider(output_dir='my_exports')
    data = spider.crawl(config)
    
    if data:
        spider.save(data, 'custom_site', config)
        print(f"✅ 抓取完成! {len(data)} 条数据")
    
    return data


def scrape_twitter_advanced(username: str):
    """
    高级示例：Twitter 抓取，带自定义处理
    """
    
    # 定义字段后处理器
    def extract_tweet_id(url: str) -> str:
        """从 URL 提取推文 ID"""
        match = re.search(r'/status/(\d+)', url)
        return match.group(1) if match else url
    
    def parse_count(text: str) -> int:
        """解析计数文本 (如 "5,231 likes")"""
        match = re.search(r'(\d+)', text.replace(',', ''))
        return int(match.group(1)) if match else 0
    
    def clean_text(text: str) -> str:
        """清理推文文本"""
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text)
        # 移除 "Show more" 等按钮文字
        text = re.sub(r'Show more.*$', '', text)
        return text.strip()
    
    config = ExtractorConfig(
        name=f"Twitter @{username}",
        url_pattern=rf"x\.com/{username}",
        item_selector='article[data-testid="tweet"]',
        field_selectors={
            'id': 'a[href*="/status/"]',
            'text': '[data-testid="tweetText"]',
            'created_at': 'time',
            'author': 'div[data-testid="User-Name"] a',
            'likes': '[data-testid="like"]',
            'replies': '[data-testid="reply"]',
            'retweets': '[data-testid="retweet"]',
        },
        scroll_times=50,
        scroll_delay=2,
        expand_selectors=[
            'button:has-text("Show more")',
            '[aria-label*="Show more"]'
        ],
        # 字段后处理器
        field_processors={
            'id': extract_tweet_id,
            'text': clean_text,
            'likes': parse_count,
            'replies': parse_count,
            'retweets': parse_count,
        },
        id_field='id',
        sort_field='created_at',
    )
    
    spider = CDPSpider(output_dir='twitter_exports')
    data = spider.crawl(config)
    
    if data:
        spider.save(data, f'twitter_{username}', config)
    
    return data


def scrape_with_filter():
    """
    示例：带过滤条件的抓取
    只抓取符合特定条件的数据
    """
    
    # 只抓取点赞数 > 100 的推文
    def high_engagement_filter(item: dict) -> bool:
        likes = item.get('likes', 0)
        if isinstance(likes, str):
            likes = int(re.search(r'(\d+)', likes).group(1)) if re.search(r'(\d+)', likes) else 0
        return likes > 100
    
    config = ExtractorConfig(
        name="热门推文筛选",
        url_pattern=r"x\.com/lijigang",
        item_selector='article[data-testid="tweet"]',
        field_selectors={
            'text': '[data-testid="tweetText"]',
            'likes': '[data-testid="like"]',
            'time': 'time',
        },
        scroll_times=30,
        item_filter=high_engagement_filter,  # 应用过滤器
        id_field='text',
    )
    
    spider = CDPSpider()
    data = spider.crawl(config)
    
    print(f"\n✅ 过滤后: {len(data)} 条高互动推文")
    return data


def main():
    """运行示例"""
    import sys
    
    print("=" * 70)
    print("CDP Spider 使用示例")
    print("=" * 70)
    print("\n可用示例:")
    print("  1. twitter_advanced - 高级 Twitter 抓取")
    print("  2. with_filter      - 带过滤条件的抓取")
    print("  3. custom           - 自定义网站抓取模板")
    print()
    
    if len(sys.argv) < 2:
        print("使用方法: python3 examples.py <示例名称>")
        print("例如: python3 examples.py twitter_advanced")
        return
    
    example = sys.argv[1]
    
    if example == 'twitter_advanced':
        username = sys.argv[2] if len(sys.argv) > 2 else 'lijigang'
        scrape_twitter_advanced(username)
    
    elif example == 'with_filter':
        scrape_with_filter()
    
    elif example == 'custom':
        print("\n这是一个模板示例，请修改代码中的选择器为你目标网站的")
        print("然后取消注释下面的 scrape_custom_site() 调用")
        # scrape_custom_site()
    
    else:
        print(f"❌ 未知示例: {example}")


if __name__ == '__main__':
    main()
