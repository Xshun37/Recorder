# PKU 教学网 (Blackboard Learn) 资源抓取方案

## 整体架构

```
Cookie 认证 -> 课程列表 -> 内容页递归 -> 文件提取 -> 下载 + RIS 导入 Zotero
```

## 1. 认证 — Cookie 手动注入

不用 Selenium，浏览器登录后复制关键 Cookies 写入 `.env`：

| Cookie | 域名 | 作用 |
|--------|------|------|
| `JSESSIONID` | `course.pku.edu.cn` | Blackboard session |
| `s_session_id` | `course.pku.edu.cn` | Blackboard 辅助 session |
| `JWTUser` | `.pku.edu.cn` | PKU SSO JWT 跨域令牌 |

**获取方法**：Edge F12 → 应用程序 → Cookie → 分别从 `course.pku.edu.cn` 和 `.pku.edu.cn` 复制值。

```python
# auth.py 核心逻辑
session = requests.Session()
session.verify = False  # PKU 校内证书
session.cookies.set("JSESSIONID", value, domain="course.pku.edu.cn")
session.cookies.set("s_session_id", value, domain="course.pku.edu.cn")
session.cookies.set("JWTUser", value, domain=".pku.edu.cn")  # 注意跨域

# 验证：GET portal 页面，若 302 重定向到 sso/login 则 cookie 过期
```

## 2. 课程列表 — 解析 Portal HTML

从门户页提取所有课程的 `course_id` 和名称。

```python
# 课程列表 URL
COURSE_LIST_URL = "https://course.pku.edu.cn/webapps/portal/execute/tabs/tabAction?tab_tab_group_id=_1_1"

# HTML 中的课程链接格式
# href="/webapps/blackboard/execute/launcher?type=Course&id=PkId{key=_95474_1,...}"

# course_id 正则
re.search(r"PkId\{key=_(\d+_\d+)", url)
```

## 3. 内容递归 — 三层结构

```
课程主页 (courseMain)
  └─ 内容区 (listContent.jsp?content_id=XXX)
       ├─ 子文件夹 (listContent.jsp?content_id=YYY)
       │    ├─ 文件 (bbcswebdav)
       │    └─ ...
       └─ 文件 (bbcswebdav)
```

```python
# Step A: 进入课程主页，从左侧导航提取 listContent.jsp 链接
course_url = f"https://course.pku.edu.cn/webapps/blackboard/execute/courseMain?course_id=_{course_id}"
soup.select("a[href*='listContent.jsp']")

# Step B: 进入每个内容区，递归遍历
# 文件夹：listContent.jsp 链接（不同 content_id）
# 文件：href 包含 'bbcswebdav'
content_url = f"https://course.pku.edu.cn/webapps/blackboard/content/listContent.jsp?course_id=_{id}&content_id=_{cid}&mode=reset"
soup.select("a[href*='bbcswebdav']")
```

## 4. 文件下载

```python
# bbcswebdav 链接示例
# /bbcswebdav/pid-1586946-dt-content-rid-11888848_1/xid-11888848_1

# Content-Type 可能是 application/pdf 或
# application/vnd.openxmlformats-officedocument.wordprocessingml.document

resp = session.get(file_url, timeout=120, stream=True)
with open(path, "wb") as f:
    for chunk in resp.iter_content(8192):
        f.write(chunk)
```

## 5. 去重策略

| 层级 | 方法 |
|------|------|
| URL 级别 | 同门课内 `seen_urls` set，同一 bbcswebdav 链接只保留一次 |
| 文件名级别 | `seen_names` set，同一课程内同名文件只保留一次 |
| 跨运行 | `downloads/.seen.txt` 记录已下载标题，再次运行自动跳过 |

## 6. 输出 — RIS 导入 Zotero

```ris
TY  - GEN
TI  - 课件-01
UR  - https://course.pku.edu.cn/bbcswebdav/...
KW  - PKU教学网
KW  - 物理化学 (B)(25-26学年第2学期)
N1  - 来源: PKU 教学网 ... | 文件夹: 教学大纲/教学内容
L1  - file:///F:/文献/pku-downloader/downloads/.../课件-01.pdf
ER  -
```

RIS 文件拖入 Zotero 窗口，条目+标签+PDF 关联一键导入。

## 7. 关键经验

| 教训 | 说明 |
|------|------|
| 不要猜 URL | 先 `curl` 页面看实际 HTML 结构，再写解析器 |
| cookie 多域 | PKU 用了 `course.pku.edu.cn` + `.pku.edu.cn` 跨域 token |
| SSL 问题 | `session.verify = False` 解决校内自签名证书 |
| 500 错误 | `listContent.jsp?content_id=_ALL_` 不可用，必须用具体的 content_id |
| Python 3.9 兼容 | 不支持 `X \| None` 类型标注，不支持 `list[Type]` |
| GBK 终端 | emoji 在 Windows GBK 终端崩溃，用纯 ASCII |

## 8. 复用到其他 Blackboard 站点

1. `auth.py` — 改 `COOKIES` 字典和验证 URL
2. `scraper.py` — 改 `_parse_course_list`、`_get_course_content_links` 的选择器
3. `zotero_sync.py` — 通用模块，基本不用改

核心依赖：`requests` + `beautifulsoup4` + `lxml`，无需浏览器。
