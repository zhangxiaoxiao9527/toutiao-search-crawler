from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from playwright.async_api import Browser, BrowserContext, Error, Page, async_playwright

LOGGER = logging.getLogger(__name__)

DEFAULT_SEARCH_URL = (
    "https://so.toutiao.com/search?"
    "cur_tab_title=news&enable_druid_v2=1&pd=information&"
    "keyword=%E7%BE%8E%E4%BC%8A%E5%86%B2%E7%AA%81%E6%9C%80%E6%96%B0%E8%BF%9B%E5%B1%95&"
    "page_num=0&dvpf=pc&from=news&source=search_subtab_switch&"
    "action_type=search_subtab_switch&search_id="
)

ARTICLE_URL_RE = re.compile(r"https?://(?:www\.)?toutiao\.com/(?:article/|a)(\d+)")


@dataclass(slots=True)
class ArticleData:
    url: str
    title: str | None
    publish_time: str | None
    author: str | None
    like_count: str | None
    content: str | None


class ToutiaoCrawler:
    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 30_000,
        delay_seconds: float = 0.8,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.delay_seconds = delay_seconds

    async def crawl(self, search_url: str = DEFAULT_SEARCH_URL, limit: int = 20) -> list[ArticleData]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await self._new_context(browser)
            try:
                article_urls = await self.collect_article_urls(context, search_url, limit)
                LOGGER.info("Collected %s article urls from search page", len(article_urls))

                articles: list[ArticleData] = []
                for index, url in enumerate(article_urls, start=1):
                    LOGGER.info("Crawling article %s/%s: %s", index, len(article_urls), url)
                    article = await self.fetch_article(context, url)
                    articles.append(article)
                    LOGGER.info("ARTICLE %s", json.dumps(asdict(article), ensure_ascii=False))
                    await asyncio.sleep(self.delay_seconds)
                return articles
            finally:
                await context.close()
                await browser.close()

    async def _new_context(self, browser: Browser) -> BrowserContext:
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        context.set_default_timeout(self.timeout_ms)
        return context

    async def collect_article_urls(
        self,
        context: BrowserContext,
        search_url: str,
        limit: int,
    ) -> list[str]:
        page = await context.new_page()
        try:
            await page.goto(search_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await self._settle(page)

            urls: list[str] = []
            seen: set[str] = set()
            for _ in range(6):
                for _ in range(4):
                    for url in await self._extract_search_links(page):
                        if url not in seen:
                            seen.add(url)
                            urls.append(url)
                            if len(urls) >= limit:
                                return urls
                    await page.mouse.wheel(0, 1200)
                    await page.wait_for_timeout(800)

                next_page_url = await self._get_next_page_url(page)
                if not next_page_url:
                    break
                await page.goto(next_page_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await self._settle(page)
            return urls
        finally:
            await page.close()

    async def _extract_search_links(self, page: Page) -> list[str]:
        raw_links = await page.eval_on_selector_all(
            "a[href]",
            """anchors => anchors.map(anchor => anchor.href || anchor.getAttribute("href"))""",
        )
        html = await page.content()
        urls: list[str] = []
        for raw_link in [*raw_links, html]:
            if not isinstance(raw_link, str):
                continue
            for candidate in _article_urls_from_text(urljoin(page.url, raw_link)):
                urls.append(candidate)
        return urls

    async def _get_next_page_url(self, page: Page) -> str | None:
        links = await page.eval_on_selector_all(
            "a[href]",
            """anchors => anchors.map(anchor => ({
                text: anchor.innerText || anchor.textContent || "",
                href: anchor.href || anchor.getAttribute("href") || ""
            }))""",
        )
        for link in links:
            if not isinstance(link, dict):
                continue
            text = str(link.get("text", "")).strip()
            href = str(link.get("href", "")).strip()
            if text == "下一页" and href:
                return urljoin(page.url, href)
        return None

    async def fetch_article(self, context: BrowserContext, article_url: str) -> ArticleData:
        page = await context.new_page()
        try:
            await page.goto(article_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            await self._settle(page)
            extracted = await page.evaluate(EXTRACT_ARTICLE_SCRIPT)
            if not isinstance(extracted, dict):
                extracted = {}

            return ArticleData(
                url=page.url,
                title=_clean(extracted.get("title")),
                publish_time=_clean(extracted.get("publishTime")),
                author=_clean(extracted.get("author")),
                like_count=_clean_like_count(extracted.get("likeCount")),
                content=_clean(extracted.get("content")),
            )
        except Error as exc:
            LOGGER.warning("Failed to crawl %s: %s", article_url, exc)
            return ArticleData(
                url=article_url,
                title=None,
                publish_time=None,
                author=None,
                like_count=None,
                content=None,
            )
        finally:
            await page.close()

    async def _settle(self, page: Page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=10_000)
        except Error:
            pass
        await page.wait_for_timeout(1_000)


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _clean_like_count(value: Any) -> str | None:
    text = _clean(value)
    if not text or text in {"赞", "点赞"}:
        return None
    match = re.search(r"([0-9,.万wW]+)", text)
    return match.group(1) if match else text


def _article_urls_from_text(text: str) -> list[str]:
    decoded_texts = [text]
    for _ in range(3):
        decoded = unquote(decoded_texts[-1])
        if decoded == decoded_texts[-1]:
            break
        decoded_texts.append(decoded)

    urls: list[str] = []
    seen: set[str] = set()
    for decoded_text in decoded_texts:
        candidates = [decoded_text, *_nested_url_params(decoded_text)]
        for candidate in candidates:
            for match in ARTICLE_URL_RE.finditer(candidate):
                article_id = match.group(1)
                url = f"https://www.toutiao.com/article/{article_id}/?channel=&source=news"
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def _nested_url_params(text: str) -> list[str]:
    urls: list[str] = []
    pending = [text]
    seen: set[str] = set()
    for _ in range(4):
        if not pending:
            break
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        parsed = urlparse(current)
        for value in parse_qs(parsed.query).get("url", []):
            decoded = unquote(value)
            urls.append(decoded)
            pending.append(decoded)
    return urls


EXTRACT_ARTICLE_SCRIPT = r"""
() => {
  const textOf = (selector) => {
    const node = document.querySelector(selector);
    return node ? node.textContent.trim() : null;
  };

  const attrOf = (selector, attr) => {
    const node = document.querySelector(selector);
    return node ? node.getAttribute(attr) : null;
  };

  const firstText = (selectors) => {
    for (const selector of selectors) {
      const value = textOf(selector);
      if (value) return value;
    }
    return null;
  };

  const bodyText = document.body ? document.body.innerText : "";
  const paragraphText = Array.from(document.querySelectorAll("article p, [class*=article] p, p"))
    .map((node) => node.textContent.trim())
    .filter((value) => value.length > 0)
    .join("\n");

  const title = firstText([
    "h1",
    "[data-testid*=title]",
    "[class*=article-title]",
    "[class*=title]"
  ]) || document.title.replace(/_今日头条.*/, "").trim();

  const publishTime = firstText([
    "time",
    "[datetime]",
    "[class*=time]",
    "[class*=date]",
    "[class*=publish]"
  ]) || attrOf("meta[property='article:published_time']", "content")
     || attrOf("meta[name='publishdate']", "content")
     || attrOf("[datetime]", "datetime")
     || (bodyText.match(/20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?/) || [null])[0];

  const author = firstText([
    "[class*=author]",
    "[class*=source]",
    "[class*=name]",
    "address"
  ]) || attrOf("meta[name='author']", "content");

  const likeCount = firstText([
    "[class*=like] [class*=count]",
    "[class*=digg] [class*=count]",
    "[class*=like]",
    "[class*=digg]"
  ]) || ((bodyText.match(/(?:点赞|赞)\s*[:：]?\s*([0-9,.万wW]+)/) || [null, null])[1]);

  const content = firstText([
    "article",
    "[class*=article-content]",
    "[class*=articleContent]",
    "[class*=content]",
    ".syl-page-article"
  ]) || paragraphText;

  return { title, publishTime, author, likeCount, content };
}
"""
