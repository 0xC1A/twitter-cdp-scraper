#!/usr/bin/env python3
"""
Twitter 推文导出工具
将已抓取的数据转换为多种格式
"""

import json
from pathlib import Path
from datetime import datetime

def load_tweets(username):
    """加载已抓取的推文数据"""
    data_dir = Path(f'twitter_archives/{username}')
    
    # 尝试加载合并后的文件
    all_tweets_file = data_dir / f'{username}_ALL_TWEETS.json'
    if all_tweets_file.exists():
        with open(all_tweets_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('tweets', [])
    
    # 尝试加载简单文件
    simple_file = data_dir / f'{username}_SIMPLE.json'
    if simple_file.exists():
        with open(simple_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('tweets', [])
    
    # 从分页文件合并
    tweets = []
    seen_ids = set()
    
    for page_file in sorted(data_dir.glob('page_*.json')):
        with open(page_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 找到 JSON 开始
            lines = content.split('\n')
            json_start = 0
            for i, line in enumerate(lines):
                if line.strip().startswith('[') or line.strip().startswith('{'):
                    json_start = i
                    break
            try:
                data = json.loads('\n'.join(lines[json_start:]))
                if isinstance(data, list):
                    page_tweets = data
                else:
                    page_tweets = data.get('tweets', [])
                
                for t in page_tweets:
                    if isinstance(t, dict):
                        tid = t.get('id')
                        if tid and tid not in seen_ids:
                            seen_ids.add(tid)
                            tweets.append(t)
            except:
                pass
    
    return tweets

def export_to_markdown(tweets, username, output_file):
    """导出为 Markdown 格式"""
    tweets.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# @{username} 的推文存档\n\n")
        f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # 统计
        total = len(tweets)
        original = sum(1 for t in tweets if not t.get('inReplyToStatusId'))
        replies = sum(1 for t in tweets if t.get('inReplyToStatusId'))
        with_media = sum(1 for t in tweets if t.get('media'))
        
        f.write(f"## 统计\n\n")
        f.write(f"- 总计: {total} 条\n")
        f.write(f"- 原创: {original} 条\n")
        f.write(f"- 回复: {replies} 条\n")
        f.write(f"- 带媒体: {with_media} 条\n\n")
        f.write("---\n\n")
        
        # 推文列表
        for t in tweets:
            date = t.get('createdAt', '')[:10] if t.get('createdAt') else '未知'
            text = t.get('text', '').strip()
            tweet_id = t.get('id', '')
            url = f"https://x.com/{username}/status/{tweet_id}"
            
            # 互动数据
            likes = t.get('likeCount', 0)
            replies_count = t.get('replyCount', 0)
            retweets = t.get('retweetCount', 0)
            
            # 标记
            is_reply = '💬' if t.get('inReplyToStatusId') else '📝'
            has_media = '📎' if t.get('media') else ''
            
            f.write(f"### {is_reply} {has_media} [{date}]({url})\n\n")
            
            # 推文内容
            for line in text.split('\n'):
                f.write(f"> {line}\n")
            
            f.write(f"\n")
            f.write(f"👍 {likes}  💬 {replies_count}  🔄 {retweets}\n\n")
            
            # 引用的推文
            if t.get('quotedTweet'):
                qt = t['quotedTweet']
                qt_author = qt.get('author', {}).get('username', 'unknown')
                qt_text = qt.get('text', '')[:100]
                f.write(f"> 💬 引用 [@{qt_author}](https://x.com/{qt_author}): {qt_text}...\n\n")
            
            f.write("---\n\n")
    
    print(f"✅ Markdown: {output_file}")

def export_to_csv(tweets, username, output_file):
    """导出为 CSV 格式"""
    import csv
    
    tweets.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'ID', 'Date', 'Text', 'URL', 'Is Reply', 
            'Likes', 'Replies', 'Retweets', 'Has Media'
        ])
        
        for t in tweets:
            writer.writerow([
                t.get('id', ''),
                t.get('createdAt', ''),
                t.get('text', '').replace('\n', ' '),
                f"https://x.com/{username}/status/{t.get('id', '')}",
                'Yes' if t.get('inReplyToStatusId') else 'No',
                t.get('likeCount', 0),
                t.get('replyCount', 0),
                t.get('retweetCount', 0),
                'Yes' if t.get('media') else 'No'
            ])
    
    print(f"✅ CSV: {output_file}")

def export_to_txt(tweets, username, output_file):
    """导出为纯文本格式"""
    tweets.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"@{username} 的推文存档\n")
        f.write(f"导出时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"总计: {len(tweets)} 条推文\n")
        f.write("=" * 60 + "\n\n")
        
        for i, t in enumerate(tweets, 1):
            date = t.get('createdAt', '')[:10] if t.get('createdAt') else '未知'
            text = t.get('text', '')
            url = f"https://x.com/{username}/status/{t.get('id', '')}"
            
            f.write(f"[{i}] {date}\n")
            f.write(f"{text}\n")
            f.write(f"链接: {url}\n")
            f.write(f"👍 {t.get('likeCount', 0)}  💬 {t.get('replyCount', 0)}\n")
            f.write("-" * 60 + "\n\n")
    
    print(f"✅ TXT: {output_file}")

def export_summary(tweets, username, output_file):
    """导出摘要统计"""
    from collections import Counter
    
    # 统计
    total = len(tweets)
    original = sum(1 for t in tweets if not t.get('inReplyToStatusId'))
    replies = sum(1 for t in tweets if t.get('inReplyToStatusId'))
    with_media = sum(1 for t in tweets if t.get('media'))
    
    total_likes = sum(t.get('likeCount', 0) for t in tweets)
    total_replies = sum(t.get('replyCount', 0) for t in tweets)
    total_retweets = sum(t.get('retweetCount', 0) for t in tweets)
    
    # 按月份统计
    months = Counter()
    for t in tweets:
        date = t.get('createdAt', '')
        if date:
            month = date[:7]  # YYYY-MM
            months[month] += 1
    
    # 热门推文
    top_liked = sorted(tweets, key=lambda x: x.get('likeCount', 0), reverse=True)[:5]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"# @{username} 推文统计报告\n\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 总体统计\n\n")
        f.write(f"- 总推文数: {total}\n")
        f.write(f"- 原创推文: {original}\n")
        f.write(f"- 回复: {replies}\n")
        f.write(f"- 带媒体: {with_media}\n")
        f.write(f"- 总点赞: {total_likes}\n")
        f.write(f"- 总回复: {total_replies}\n")
        f.write(f"- 总转发: {total_retweets}\n\n")
        
        f.write("## 按月分布\n\n")
        for month, count in sorted(months.items(), reverse=True):
            f.write(f"- {month}: {count} 条\n")
        
        f.write("\n## 热门推文 (Top 5)\n\n")
        for i, t in enumerate(top_liked, 1):
            text = t.get('text', '')[:80]
            likes = t.get('likeCount', 0)
            url = f"https://x.com/{username}/status/{t.get('id', '')}"
            f.write(f"{i}. 👍 {likes} - {text}...\n")
            f.write(f"   {url}\n\n")
    
    print(f"✅ 统计报告: {output_file}")

def main():
    import sys
    
    username = sys.argv[1] if len(sys.argv) > 1 else 'lijigang'
    username = username.lstrip('@')
    
    print("=" * 60)
    print(f"Twitter 推文导出工具 - @{username}")
    print("=" * 60)
    
    # 加载推文
    print(f"\n📂 加载推文数据...")
    tweets = load_tweets(username)
    
    if not tweets:
        print(f"❌ 未找到 @{username} 的推文数据")
        print(f"请确保 twitter_archives/{username}/ 目录存在数据文件")
        return
    
    print(f"✓ 加载了 {len(tweets)} 条推文")
    
    # 创建输出目录
    output_dir = Path(f'twitter_exports/{username}')
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # 导出各种格式
    print(f"\n📝 导出中...")
    export_to_markdown(tweets, username, output_dir / f'{username}_{timestamp}.md')
    export_to_csv(tweets, username, output_dir / f'{username}_{timestamp}.csv')
    export_to_txt(tweets, username, output_dir / f'{username}_{timestamp}.txt')
    export_summary(tweets, username, output_dir / f'{username}_{timestamp}_summary.md')
    
    print(f"\n✅ 全部导出完成!")
    print(f"📁 输出目录: {output_dir}/")
    
    # 显示预览
    print(f"\n📝 最新 5 条推文:")
    tweets.sort(key=lambda x: x.get('createdAt', ''), reverse=True)
    for t in tweets[:5]:
        date = t.get('createdAt', '')[:10] if t.get('createdAt') else '未知'
        text = t.get('text', '')[:50]
        reply_mark = '💬' if t.get('inReplyToStatusId') else '📝'
        print(f"  {reply_mark} [{date}] {text}...")

if __name__ == '__main__':
    main()
