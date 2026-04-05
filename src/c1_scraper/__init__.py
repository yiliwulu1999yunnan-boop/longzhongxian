# C1: Boss直聘简历获取（Playwright 浏览器自动化）

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.models import RecommendCandidate
from src.c1_scraper.recommend_scraper import RecommendScraper, parse_recommend_response

__all__ = [
    "BrowserManager",
    "RecommendCandidate",
    "RecommendScraper",
    "parse_recommend_response",
]
