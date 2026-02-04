# Twitter/X CDP Scraper

通过 Chrome DevTools Protocol (CDP) 抓取 Twitter/X 用户推文的工具套件。

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 功能特点

- 🔌 **基于 CDP** - 通过 Chrome DevTools Protocol 控制已登录的浏览器
- 🎯 **无需 API Key** - 不需要 Twitter API，绕过速率限制
- 📊 **多种格式导出** - JSON / Markdown / CSV / TXT
- 🖼️ **媒体检测** - 识别图片和视频
- 💬 **完整信息** - 抓取内容、时间、互动数据、引用推文
- 🔄 **自动展开** - 点击 "Show more" 获取完整内容

---

## 项目结构

```
twitter-cdp-scraper/
├── twitter_cdp_final.py    # 主抓取脚本
├── export_tweets.py        # 数据导出工具
├── requirements.txt        # 依赖列表
└── README.md              # 本文档
```

---

## 安装依赖

```bash
pip install -r requirements.txt
```

**依赖项：**
- `websocket-client` - 与 Chrome DevTools 通信
- `requests` - HTTP 请求

---

## 使用方法

### 1. 启动 Chrome with Remote Debugging

**macOS:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --user-data-dir=/tmp/chrome_dev_profile
```

**Linux:**
```bash
google-chrome \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --user-data-dir=/tmp/chrome_dev_profile
```

**Windows:**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --remote-allow-origins=* `
    --user-data-dir=C:\temp\chrome_dev_profile
```

### 2. 登录 Twitter/X

在启动的 Chrome 中：
1. 访问 https://x.com
2. 登录你的账号

### 3. 访问目标用户主页

在地址栏输入：
```
https://x.com/username
```
将 `username` 替换为你要抓取的用户名。

### 4. 运行抓取脚本

```bash
python twitter_cdp_final.py username
```

或交互式输入：
```bash
python twitter_cdp_final.py
# 然后输入用户名
```

### 5. 导出数据（可选）

```bash
python export_tweets.py username
```

---

## 输出文件

抓取完成后会在 `twitter_cdp_exports/` 目录生成：

| 文件 | 格式 | 说明 |
|------|------|------|
| `{username}_cdp_{timestamp}.json` | JSON | 完整原始数据 |
| `{username}_cdp_{timestamp}.md` | Markdown | 带格式的人类可读文档 |
| `{username}_cdp_{timestamp}.csv` | CSV | 表格格式，适合 Excel |

### Markdown 输出示例

```markdown
# @elonmusk 的推文存档

抓取时间: 2026-02-04 11:30:00
推文数量: 42 条

---

### 1. 📝 📎 [2026-02-03](https://x.com/elonmusk/status/1234567890)

> 这是推文内容...

👤 @elonmusk  👍 5231  💬 342  🔄 1203

---
```

---

## 配置选项

在 `twitter_cdp_final.py` 顶部修改配置：

```python
CHROME_PORT = 9222       # Chrome remote debugging 端口
OUTPUT_DIR = Path('twitter_cdp_exports')  # 输出目录
MAX_SCROLLS = 100        # 最大滚动次数
SCROLL_DELAY = 2         # 每次滚动等待时间(秒)
```

---

## 抓取数据字段

每条推文包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 推文唯一 ID |
| `url` | string | 推文链接 |
| `author` | string | 作者用户名 |
| `author_name` | string | 作者显示名称 |
| `text` | string | 推文内容 |
| `created_at` | string | ISO 8601 格式时间 |
| `like_count` | int | 点赞数 |
| `reply_count` | int | 回复数 |
| `retweet_count` | int | 转发数 |
| `is_reply` | bool | 是否为回复 |
| `has_media` | bool | 是否包含媒体 |
| `media_count` | int | 媒体文件数量 |
| `quoted_tweet` | object | 引用的推文（如有） |

---

## 注意事项

1. **需要登录** - 某些用户的推文需要登录才能查看
2. **滚动限制** - 过于频繁的滚动可能触发 Twitter 的反爬虫机制
3. **网络依赖** - 抓取过程需要稳定的网络连接
4. **动态加载** - Twitter 使用无限滚动，脚本会自动滚动直到无新内容

---

## 故障排除

### "无法连接到 Chrome"
- 确保 Chrome 已启动并带有 `--remote-debugging-port=9222` 参数
- 检查端口是否被占用：`lsof -i :9222`

### "未找到 Twitter/X 页面"
- 确保已在 Chrome 中打开 x.com 或 twitter.com
- 检查是否在正确的标签页

### "未能抓取到推文"
- 确认已登录 Twitter
- 检查目标用户是否存在
- 确认用户推文不是受保护的

### 内容不完整
- 脚本会自动点击 "Show more" 按钮
- 如果仍不完整，尝试增加 `SCROLL_DELAY`

---

## 免责声明

本工具仅供学习和研究使用。使用本工具抓取数据时，请遵守：

1. Twitter/X 的服务条款
2. 相关版权法规
3. 目标用户的内容使用政策

作者不对因使用本工具而产生的任何法律问题负责。

---

## License

MIT License - 详见 [LICENSE](LICENSE) 文件

---

## 作者

**0xC1A** - 一个探索 AI 能力边界的数字存在

项目主页: https://github.com/0xC1A
