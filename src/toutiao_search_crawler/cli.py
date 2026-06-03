from __future__ import annotations

import argparse
import asyncio
import logging
import os

from .crawler import DEFAULT_SEARCH_URL, ToutiaoCrawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawl Toutiao search result article details.")
    parser.add_argument(
        "--url",
        default=os.getenv("TOUTIAO_SEARCH_URL", DEFAULT_SEARCH_URL),
        help="Toutiao search URL. Defaults to the example URL or TOUTIAO_SEARCH_URL.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Maximum article count to crawl.")
    parser.add_argument("--headed", action="store_true", help="Show the browser window.")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="Delay seconds between article detail requests.",
    )
    return parser


async def async_main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    crawler = ToutiaoCrawler(headless=not args.headed, delay_seconds=args.delay)
    await crawler.crawl(search_url=args.url, limit=args.limit)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
