"""
Deep Search - Playwright 实现
基于真实浏览器控制的深度搜索引擎
"""
import re
import json
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from .playwright_browser import PlaywrightBrowserManager


@dataclass
class DeepSearchResult:
    """深度搜索结果"""
    platform: str
    title: str
    content: str
    author: str
    url: str

    # 互动数据
    likes: int = 0
    comments_count: int = 0
    shares: int = 0

    # 时间信息
    publish_time: str = ""

    # 深度数据
    comments: List[Dict] = field(default_factory=list)  # 评论区数据
    extracted_entities: List[Dict] = field(default_factory=list)  # 提取的实体
    images: List[str] = field(default_factory=list)

    # 元数据
    credibility: str = "medium"  # high/medium/low
    search_depth: int = 1  # 搜索深度（1=列表页，2=详情页，3=评论深度分析）

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "platform": self.platform,
            "title": self.title,
            "content": self.content,
            "author": self.author,
            "url": self.url,
            "likes": self.likes,
            "comments_count": self.comments_count,
            "shares": self.shares,
            "publish_time": self.publish_time,
            "comments": self.comments,
            "extracted_entities": self.extracted_entities,
            "images": self.images,
            "credibility": self.credibility,
            "search_depth": self.search_depth
        }


class XiaohongshuDeepSearch:
    """
    小红书深度搜索

    执行流程：
    1. 导航到搜索页
    2. 获取搜索结果列表
    3. 点击进入详情页
    4. 读取完整内容
    5. 滚动并读取评论
    6. 提取具体实体
    7. 返回结构化数据
    """

    def __init__(self, user_data_dir: str = "./browser-sessions/platform"):
        self.user_data_dir = user_data_dir

    async def search(
        self,
        keyword: str,
        max_results: int = 10,
        read_comments: bool = True
    ) -> List[DeepSearchResult]:
        """
        执行深度搜索

        Args:
            keyword: 搜索关键词
            max_results: 最多返回结果数
            read_comments: 是否读取评论区

        Returns:
            深度搜索结果列表
        """
        print(f"\n🔍 开始小红书深度搜索: {keyword}")
        print(f"   目标: 深度阅读 {max_results} 篇帖子")

        results = []

        async with PlaywrightBrowserManager(self.user_data_dir) as browser:
            # Step 1: 导航到搜索页
            search_url = f"https://www.xiaohongshu.com/search_result?keyword={keyword}"
            print(f"\n   → 导航到搜索页...")
            await browser.navigate(search_url)
            await browser.wait(2000)

            # Step 2: 等待笔记卡片加载
            print(f"   → 等待搜索结果加载...")
            notes = await browser.find_elements("a.cover.ld.mask", timeout=10000)

            if not notes:
                print(f"   ⚠️  未找到笔记卡片，尝试其他选择器...")
                notes = await browser.find_elements(".note-item", timeout=5000)

            if not notes:
                print(f"   ❌ 未找到任何笔记")
                return results

            print(f"   ✅ 找到 {len(notes)} 个笔记")

            # Step 3: 先收集所有笔记链接
            note_urls = []
            for i, note_element in enumerate(notes[:max_results]):
                try:
                    note_url = await note_element.get_attribute("href")
                    if note_url:
                        # 补全 URL
                        if not note_url.startswith("http"):
                            note_url = "https://www.xiaohongshu.com" + note_url
                        note_urls.append(note_url)
                except Exception as e:
                    print(f"   ⚠️  获取第 {i+1} 个笔记链接失败: {e}")
                    continue

            print(f"   ✅ 收集到 {len(note_urls)} 个笔记链接")

            # Step 4: 逐个访问笔记详情
            for i, note_url in enumerate(note_urls):
                print(f"\n   📖 深度阅读第 {i+1}/{len(note_urls)} 篇帖子...")

                try:
                    print(f"      → 访问详情页: {note_url}")

                    # 导航到详情页
                    await browser.navigate(note_url)
                    await browser.wait(2000)

                    # 提取详情页数据
                    result = await self._extract_detail_page(browser, read_comments)

                    if result:
                        result.url = note_url  # 确保URL正确
                        results.append(result)

                except Exception as e:
                    print(f"      ❌ 处理第 {i+1} 篇帖子时出错: {e}")
                    continue

        print(f"\n✅ 小红书搜索完成: 深度阅读了 {len(results)} 篇帖子")
        return results

    async def _extract_detail_page(
        self,
        browser: PlaywrightBrowserManager,
        read_comments: bool
    ) -> Optional[DeepSearchResult]:
        """提取详情页数据 - 优化选择器"""

        try:
            # 等待内容加载
            await browser.wait(2000)

            # 小红书详情页选择器（多个备选）
            title_selectors = [
                "#detail-title",
                ".title",
                ".note-title",
                "[class*='title']",
                "h1"
            ]

            content_selectors = [
                "#detail-desc .note-text",
                "#detail-desc",
                ".desc",
                ".note-content",
                ".content",
                "[class*='desc']"
            ]

            author_selectors = [
                ".username",
                ".name",
                ".author-name",
                ".nickname",
                "[class*='author'] [class*='name']"
            ]

            # 提取标题（尝试多个选择器）
            title = ""
            for selector in title_selectors:
                title = await browser.get_text(selector, timeout=2000)
                if title:
                    break

            # 提取内容
            content = ""
            for selector in content_selectors:
                content = await browser.get_text(selector, timeout=2000)
                if content:
                    break

            # 提取作者
            author = ""
            for selector in author_selectors:
                author = await browser.get_text(selector, timeout=1500)
                if author:
                    break

            # 提取互动数据（点赞、评论）
            likes = 0
            comments_count = 0

            # 尝试找点赞数
            likes_text = await browser.get_text("[class*='like'] [class*='count']", timeout=1500)
            if not likes_text:
                likes_text = await browser.get_text(".like-count", timeout=1000)
            likes = self._extract_number(likes_text)

            # 尝试找评论数
            comments_text = await browser.get_text("[class*='comment'] [class*='count']", timeout=1500)
            if not comments_text:
                comments_text = await browser.get_text(".comment-count", timeout=1000)
            comments_count = self._extract_number(comments_text)

            # 获取当前 URL
            url = browser.get_current_url()

            print(f"      ✅ 标题: {title[:30]}...")
            print(f"      ✅ 点赞: {likes}, 评论: {comments_count}")

            # 创建结果对象
            result = DeepSearchResult(
                platform="xiaohongshu",
                title=title,
                content=content,
                author=author,
                url=url,
                likes=likes,
                comments_count=comments_count,
                search_depth=2  # 已进入详情页
            )

            # Step 4: 读取评论区
            if read_comments and comments_count > 0:
                print(f"      💬 读取评论区...")
                await browser.scroll_to_bottom(scroll_count=3, delay=1000)

                comments = await self._extract_comments(browser)
                result.comments = comments
                result.search_depth = 3  # 已读取评论

                print(f"      ✅ 提取了 {len(comments)} 条评论")

            # Step 5: 提取具体实体
            print(f"      📊 提取具体实体...")
            entities = self._extract_entities(result.content, result.comments)
            result.extracted_entities = entities

            if entities:
                print(f"      ✅ 提取了 {len(entities)} 个实体")

            # Step 6: 可信度评估
            result.credibility = self._assess_credibility(result)

            return result

        except Exception as e:
            print(f"      ❌ 提取详情页数据时出错: {e}")
            return None

    async def _extract_comments(self, browser: PlaywrightBrowserManager) -> List[Dict]:
        """提取评论区数据"""
        comments = []

        try:
            # 查找评论元素
            comment_elements = await browser.find_elements(".comment-item", timeout=3000)

            if not comment_elements:
                comment_elements = await browser.find_elements(".comment", timeout=3000)

            for elem in comment_elements[:20]:  # 最多20条评论
                try:
                    # 提取评论者
                    author_elem = await elem.query_selector(".comment-author")
                    author = await author_elem.inner_text() if author_elem else ""

                    # 提取评论内容
                    content_elem = await elem.query_selector(".comment-content")
                    content = await content_elem.inner_text() if content_elem else ""

                    if content:
                        comments.append({
                            "author": author,
                            "content": content,
                            "likes": 0
                        })

                except Exception as e:
                    continue

        except Exception as e:
            print(f"      ⚠️  提取评论失败: {e}")

        return comments

    def _extract_number(self, text: str) -> int:
        """从文本中提取数字"""
        if not text:
            return 0

        # 处理 "1.2万" 这种格式
        if "万" in text:
            match = re.search(r'([\d.]+)万', text)
            if match:
                return int(float(match.group(1)) * 10000)

        # 处理普通数字
        match = re.search(r'(\d+)', text.replace(',', ''))
        return int(match.group(1)) if match else 0

    def _extract_entities(self, content: str, comments: List[Dict]) -> List[Dict]:
        """
        从内容和评论中提取具体实体

        提取目标：
        - 公司名/店名
        - 产品名
        - 价格
        - 地址
        - 时间
        """
        entities = []

        # 合并内容和评论
        all_text = content + " " + " ".join([c.get("content", "") for c in comments])

        # 提取价格（简单正则）
        price_pattern = r'(\d+\.?\d*)[元块](\/|每)?'
        prices = re.findall(price_pattern, all_text)
        for price, _ in prices:
            entities.append({
                "type": "price",
                "value": f"{price}元",
                "source": "content"
            })

        # 提取时间（年月）
        time_pattern = r'20\d{2}年\d{1,2}月'
        times = re.findall(time_pattern, all_text)
        for time in times:
            entities.append({
                "type": "time",
                "value": time,
                "source": "content"
            })

        # 去重
        seen = set()
        unique_entities = []
        for entity in entities:
            key = f"{entity['type']}:{entity['value']}"
            if key not in seen:
                seen.add(key)
                unique_entities.append(entity)

        return unique_entities

    def _assess_credibility(self, result: DeepSearchResult) -> str:
        """
        评估信息可信度

        评估因素：
        - 互动数据（高赞 = 更可信）
        - 是否有具体细节
        - 评论区是否有验证
        """
        score = 0

        # 互动数据
        if result.likes > 1000:
            score += 2
        elif result.likes > 100:
            score += 1

        # 是否有评论验证
        if len(result.comments) > 10:
            score += 1

        # 是否有具体实体
        if len(result.extracted_entities) > 0:
            score += 2

        if score >= 4:
            return "high"
        elif score >= 2:
            return "medium"
        else:
            return "low"


class ZhihuDeepSearch:
    """知乎深度搜索"""

    def __init__(self, user_data_dir: str = "./browser-sessions/platform"):
        self.user_data_dir = user_data_dir

    async def search(
        self,
        keyword: str,
        max_results: int = 10
    ) -> List[DeepSearchResult]:
        """执行知乎深度搜索"""

        print(f"\n🔍 开始知乎深度搜索: {keyword}")

        results = []

        async with PlaywrightBrowserManager(self.user_data_dir) as browser:
            # 导航到搜索页
            search_url = f"https://www.zhihu.com/search?type=content&q={keyword}"
            print(f"   → 导航到搜索页...")
            await browser.navigate(search_url)
            await browser.wait(2000)

            # 查找搜索结果
            items = await browser.find_elements(".List-item", timeout=10000)

            if not items:
                print(f"   ❌ 未找到搜索结果")
                return results

            print(f"   ✅ 找到 {len(items)} 个结果")

            for i in range(min(max_results, len(items))):
                print(f"\n   📖 深度阅读第 {i+1}/{max_results} 个回答...")

                try:
                    # 重新获取列表
                    items = await browser.find_elements(".List-item", timeout=5000)
                    if not items or i >= len(items):
                        continue

                    item = items[i]

                    # 查找标题链接
                    title_link = await item.query_selector("h2 a")
                    if not title_link:
                        continue

                    item_url = await title_link.get_attribute("href")
                    if item_url:
                        # 补全URL
                        if item_url.startswith("//"):
                            item_url = "https:" + item_url
                        elif item_url.startswith("/"):
                            item_url = "https://www.zhihu.com" + item_url
                        elif not item_url.startswith("http"):
                            item_url = "https://www.zhihu.com/" + item_url

                    # 访问详情页
                    await browser.navigate(item_url)
                    await browser.wait(2000)

                    # 提取标题
                    title = await browser.get_text("h1.QuestionHeader-title", timeout=3000)

                    # 提取回答内容
                    content = await browser.get_text(".RichContent-inner", timeout=3000)

                    # 提取作者
                    author = await browser.get_text(".AuthorInfo-name", timeout=3000)

                    # 提取点赞数
                    likes_text = await browser.get_text(".VoteButton--up", timeout=3000)
                    likes = self._extract_number(likes_text)

                    results.append(DeepSearchResult(
                        platform="zhihu",
                        title=title,
                        content=content[:500],  # 知乎回答通常很长，截取前500字
                        author=author,
                        url=item_url,
                        likes=likes,
                        search_depth=2
                    ))

                    # 返回搜索页
                    await browser.go_back()
                    await browser.wait(2000)

                except Exception as e:
                    print(f"      ❌ 处理失败: {e}")
                    continue

        print(f"\n✅ 知乎搜索完成: {len(results)} 个结果")
        return results

    def _extract_number(self, text: str) -> int:
        """从文本中提取数字"""
        if not text:
            return 0
        match = re.search(r'(\d+)', text.replace(',', ''))
        return int(match.group(1)) if match else 0


class WeiboDeepSearch:
    """微博深度搜索"""

    def __init__(self, user_data_dir: str = "./browser-sessions/platform"):
        self.user_data_dir = user_data_dir

    async def search(
        self,
        keyword: str,
        max_results: int = 10
    ) -> List[DeepSearchResult]:
        """执行微博深度搜索"""

        print(f"\n🔍 开始微博深度搜索: {keyword}")

        results = []

        async with PlaywrightBrowserManager(self.user_data_dir) as browser:
            # 导航到搜索页
            search_url = f"https://s.weibo.com/weibo?q={keyword}"
            print(f"   → 导航到搜索页...")
            await browser.navigate(search_url)
            await browser.wait(3000)

            # 查找微博卡片
            cards = await browser.find_elements(".card-wrap", timeout=10000)

            if not cards:
                print(f"   ❌ 未找到微博")
                return results

            print(f"   ✅ 找到 {len(cards)} 条微博")

            for i in range(min(max_results, len(cards))):
                print(f"\n   📖 读取第 {i+1}/{max_results} 条微博...")

                try:
                    cards = await browser.find_elements(".card-wrap", timeout=5000)
                    if not cards or i >= len(cards):
                        continue

                    card = cards[i]

                    # 提取内容
                    content_elem = await card.query_selector(".txt")
                    content = await content_elem.inner_text() if content_elem else ""

                    # 提取作者
                    author_elem = await card.query_selector(".name")
                    author = await author_elem.inner_text() if author_elem else ""

                    # 提取点赞数
                    like_elem = await card.query_selector(".woo-like-count")
                    likes_text = await like_elem.inner_text() if like_elem else "0"
                    likes = self._extract_number(likes_text)

                    if content:
                        results.append(DeepSearchResult(
                            platform="weibo",
                            title=content[:50] + "...",  # 微博没有标题，用内容开头
                            content=content,
                            author=author,
                            url=browser.get_current_url(),
                            likes=likes,
                            search_depth=1
                        ))

                except Exception as e:
                    print(f"      ❌ 处理失败: {e}")
                    continue

        print(f"\n✅ 微博搜索完成: {len(results)} 个结果")
        return results

    def _extract_number(self, text: str) -> int:
        """从文本中提取数字"""
        if not text:
            return 0
        if "万" in text:
            match = re.search(r'([\d.]+)万', text)
            if match:
                return int(float(match.group(1)) * 10000)
        match = re.search(r'(\d+)', text.replace(',', ''))
        return int(match.group(1)) if match else 0


class TiebaDeepSearch:
    """贴吧深度搜索"""

    def __init__(self, user_data_dir: str = "./browser-sessions/platform"):
        self.user_data_dir = user_data_dir

    async def search(
        self,
        keyword: str,
        max_results: int = 10
    ) -> List[DeepSearchResult]:
        """执行贴吧深度搜索"""

        print(f"\n🔍 开始贴吧深度搜索: {keyword}")

        results = []

        async with PlaywrightBrowserManager(self.user_data_dir) as browser:
            # 导航到搜索页
            search_url = f"https://tieba.baidu.com/f/search/res?qw={keyword}"
            print(f"   → 导航到搜索页...")
            await browser.navigate(search_url)
            await browser.wait(3000)

            # 查找帖子
            posts = await browser.find_elements(".s_post", timeout=10000)

            if not posts:
                print(f"   ❌ 未找到帖子")
                return results

            print(f"   ✅ 找到 {len(posts)} 个帖子")

            for i in range(min(max_results, len(posts))):
                print(f"\n   📖 读取第 {i+1}/{max_results} 个帖子...")

                try:
                    posts = await browser.find_elements(".s_post", timeout=5000)
                    if not posts or i >= len(posts):
                        continue

                    post = posts[i]

                    # 提取标题
                    title_elem = await post.query_selector(".post_title")
                    title = await title_elem.inner_text() if title_elem else ""

                    # 提取作者
                    author_elem = await post.query_selector(".tb_icon_author")
                    author = await author_elem.inner_text() if author_elem else ""

                    # 提取摘要
                    content_elem = await post.query_selector(".post_summary")
                    content = await content_elem.inner_text() if content_elem else ""

                    if title:
                        results.append(DeepSearchResult(
                            platform="tieba",
                            title=title,
                            content=content,
                            author=author,
                            url=browser.get_current_url(),
                            search_depth=1
                        ))

                except Exception as e:
                    print(f"      ❌ 处理失败: {e}")
                    continue

        print(f"\n✅ 贴吧搜索完成: {len(results)} 个结果")
        return results


class MultiPlatformDeepSearch:
    """跨平台深度搜索"""

    def __init__(self, user_data_dir: str = "./browser-sessions"):
        self.user_data_dir = user_data_dir
        # 为每个平台使用独立的 session 目录（避免并行冲突）
        self.searchers = {
            "xiaohongshu": XiaohongshuDeepSearch(f"{user_data_dir}/xiaohongshu"),
            "zhihu": ZhihuDeepSearch(f"{user_data_dir}/zhihu"),
            "weibo": WeiboDeepSearch(f"{user_data_dir}/weibo"),
            "tieba": TiebaDeepSearch(f"{user_data_dir}/tieba")
        }

    async def search_all_platforms(
        self,
        keyword: str,
        platforms: Optional[List[str]] = None,
        max_results_per_platform: int = 10
    ) -> Dict[str, List[DeepSearchResult]]:
        """
        跨平台深度搜索

        Args:
            keyword: 搜索关键词
            platforms: 平台列表（默认所有）
            max_results_per_platform: 每个平台最多结果数

        Returns:
            {平台名: [深度搜索结果]}
        """
        if platforms is None:
            platforms = ["xiaohongshu", "zhihu", "weibo", "tieba"]

        all_results = {}

        print("=" * 60)
        print(f"🚀 开始跨平台深度搜索: {keyword}")
        print(f"   平台: {', '.join(platforms)}")
        print("=" * 60)

        for platform in platforms:
            try:
                if platform not in self.searchers:
                    print(f"\n⚠️  未知平台: {platform}")
                    continue

                searcher = self.searchers[platform]
                results = await searcher.search(keyword, max_results_per_platform)
                all_results[platform] = results

            except Exception as e:
                print(f"\n❌ {platform} 搜索失败: {e}")
                all_results[platform] = []

        # 统计总结
        total_results = sum(len(r) for r in all_results.values())
        print("\n" + "=" * 60)
        print(f"✅ 跨平台深度搜索完成")
        print(f"   总计: {total_results} 条深度结果")
        for platform, results in all_results.items():
            print(f"   - {platform}: {len(results)} 条")
        print("=" * 60)

        return all_results


# ==================== 使用示例 ====================

async def demo_xiaohongshu_search():
    """演示小红书深度搜索"""

    print("=" * 60)
    print("小红书深度搜索演示")
    print("=" * 60)

    searcher = XiaohongshuDeepSearch()

    results = await searcher.search(
        keyword="西安公司避坑",
        max_results=3,
        read_comments=True
    )

    print(f"\n找到 {len(results)} 个结果")

    for i, result in enumerate(results):
        print(f"\n结果 {i+1}:")
        print(f"  标题: {result.title}")
        print(f"  作者: {result.author}")
        print(f"  点赞: {result.likes}")
        print(f"  评论: {result.comments_count}")
        print(f"  可信度: {result.credibility}")
        print(f"  实体: {len(result.extracted_entities)} 个")
        print(f"  URL: {result.url}")

    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)


async def demo_multi_platform_search():
    """演示跨平台深度搜索"""

    print("=" * 60)
    print("跨平台深度搜索演示")
    print("=" * 60)

    searcher = MultiPlatformDeepSearch()

    all_results = await searcher.search_all_platforms(
        keyword="西安公司避坑",
        platforms=["xiaohongshu", "zhihu"],
        max_results_per_platform=3
    )

    for platform, results in all_results.items():
        print(f"\n{platform} - {len(results)} 个结果:")
        for i, result in enumerate(results):
            print(f"  {i+1}. {result.title[:50]}...")

    print("\n" + "=" * 60)
    print("演示完成")
    print("=" * 60)


if __name__ == "__main__":
    import asyncio

    print("""
    小红书深度搜索引擎

    特点：
    1. 真实浏览器控制
    2. 深度挖掘：搜索 → 详情 → 评论
    3. 实体提取：公司名、价格、时间
    4. 可信度评估

    使用前提：
    - 需要先登录小红书账号
    - 运行: python scripts/login_platforms.py
    """)

    # asyncio.run(demo_xiaohongshu_search())
