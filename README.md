# CDP Spider - 通用网页抓取框架

基于 Chrome DevTools Protocol 的灵活数据提取工具。只需配置选择器，无需编写复杂代码即可抓取任何网站。

## 🚀 快速开始

### 1. 启动 Chrome（带 Remote Debugging）

```bash
# 关闭所有 Chrome 窗口后执行
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --remote-allow-origins='*' \
    --user-data-dir=/tmp/chrome_dev_profile
```

### 2. 在 Chrome 中打开目标页面

- 登录目标网站（如 Twitter、知乎）
- 访问要抓取的页面（如用户主页）

### 3. 运行抓取脚本

```bash
# 使用预设配置
python3 cdp_spider.py twitter lijigang

# 或使用示例脚本
python3 cdp_spider_examples.py twitter_advanced lijigang
```

## 📦 文件说明

| 文件 | 说明 |
|------|------|
| `cdp_spider.py` | 框架主文件，包含核心类和预设 |
| `cdp_spider_examples.py` | 使用示例，展示如何自定义 |
| `twitter_cdp_final.py` | 原始的 Twitter 专用脚本 |

## 🔧 自定义抓取器

### 最简单的方式：修改配置

```python
from cdp_spider import CDPSpider, ExtractorConfig

# 创建配置
config = ExtractorConfig(
    name="我的网站",
    url_pattern=r"example\.com/list",
    item_selector='.item',  # 列表项选择器
    field_selectors={
        'title': 'h2 a',      # 字段名: CSS选择器
        'author': '.author',
        'date': '.time',
    },
    scroll_times=20,         # 滚动次数
)

# 执行抓取
spider = CDPSpider()
data = spider.crawl(config)
spider.save(data, 'mydata')
```

### 完整配置选项

```python
ExtractorConfig(
    # 基本信息
    name="抓取任务名称",
    url_pattern=r"正则匹配URL",
    
    # 选择器（核心）
    item_selector='.item',           # 每个数据项的容器
    field_selectors={
        'title': 'h2',
        'link': 'a',                  # 自动提取 href
        'text': '.content',           # 提取 innerText
    },
    
    # 滚动配置
    scroll_enabled=True,             # 是否滚动
    scroll_times=50,                 # 最大滚动次数
    scroll_delay=2.0,                # 滚动间隔(秒)
    scroll_selector=None,            # 滚动容器(None=整页)
    
    # 展开配置
    expand_selectors=[               # 点击展开的元素
        '.show-more',
        'button:has-text("Show")',
    ],
    expand_delay=1.0,                # 展开等待时间
    
    # 数据处理
    field_processors={               # 字段后处理
        'id': lambda x: extract_id(x),
        'count': lambda x: int(x),
    },
    item_filter=lambda item: True,   # 项目过滤函数
    
    # 输出配置
    id_field='id',                   # 去重字段
    sort_field='date',               # 排序字段
    sort_reverse=True,               # 倒序
)
```

## 🎯 内置预设

### Twitter/X
```bash
python3 cdp_spider.py twitter <用户名>
# 例如:
python3 cdp_spider.py twitter elonmusk
```

### 知乎回答
```bash
python3 cdp_spider.py zhihu
# 需要在 Chrome 中打开知乎问题页面
```

### 豆瓣评论
```bash
python3 cdp_spider.py douban
# 需要在 Chrome 中打开豆瓣电影/书籍评论页
```

### GitHub Issues
```bash
python3 cdp_spider.py github
# 需要在 Chrome 中打开 GitHub Issues 页
```

## 📝 高级用法

### 带过滤的抓取

```python
# 只抓取高赞推文
def filter_hot(item):
    return item.get('likes', 0) > 100

config = ExtractorConfig(
    # ... 基础配置
    item_filter=filter_hot,
)
```

### 字段后处理

```python
def extract_id(url):
    import re
    match = re.search(r'/status/(\d+)', url)
    return match.group(1) if match else url

def parse_count(text):
    # "5,231 likes" -> 5231
    return int(text.replace(',', '').split()[0])

config = ExtractorConfig(
    # ... 基础配置
    field_processors={
        'id': extract_id,
        'likes': parse_count,
    },
)
```

## 📂 输出文件

抓取完成后会生成三个文件：

| 格式 | 用途 |
|------|------|
| `.json` | 完整数据，程序处理 |
| `.csv` | 表格格式，Excel 打开 |
| `.md` | 阅读友好，Markdown |

默认保存在 `spider_exports/` 目录。

## 🔍 调试技巧

### 1. 检查选择器

在 Chrome DevTools Console 中测试：

```javascript
// 测试 item_selector
document.querySelectorAll('article[data-testid="tweet"]').length

// 测试 field_selector
document.querySelector('article [data-testid="tweetText"]').innerText
```

### 2. 查看抓取过程

脚本会输出进度：
```
第 1 轮: +20 条新数据, 总计: 20 条
第 6 轮: +15 条新数据, 总计: 35 条
第 11 轮: +0 条新数据, 总计: 35 条
✅ 没有新数据了，停止
```

### 3. 常见问题

| 问题 | 解决 |
|------|------|
| "无法连接到 Chrome" | 检查是否启动了 `--remote-debugging-port=9222` |
| "未找到匹配的页面" | 确保在 Chrome 中打开了目标页面 |
| 抓取数据为空 | 检查选择器是否正确，在 DevTools 中测试 |
| 数据重复 | 确认 `id_field` 设置正确，能唯一标识每条数据 |

## 🛠️ 扩展框架

### 添加新预设

在 `cdp_spider.py` 的 `Presets` 类中添加：

```python
@staticmethod
def my_site() -> ExtractorConfig:
    return ExtractorConfig(
        name="我的网站",
        url_pattern=r"mysite\.com",
        item_selector='.item',
        field_selectors={...},
    )
```

然后在 `main()` 中添加：

```python
elif preset == 'mysite':
    config = Presets.my_site()
```

## 📚 依赖

```bash
pip3 install websocket-client
```

## 📝 作者

- 框架设计: 0xC1A
- 基于: Chrome DevTools Protocol
