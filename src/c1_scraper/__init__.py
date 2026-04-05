# C1: Boss直聘简历获取（Playwright 浏览器自动化）

from src.c1_scraper.browser import BrowserManager
from src.c1_scraper.candidate_store import store_candidates
from src.c1_scraper.detail_extractor import CandidateDetail, parse_candidate_detail
from src.c1_scraper.models import RecommendCandidate
from src.c1_scraper.recommend_scraper import RecommendScraper, parse_recommend_response

__all__ = [
    "BrowserManager",
    "CandidateDetail",
    "RecommendCandidate",
    "RecommendScraper",
    "parse_candidate_detail",
    "parse_recommend_response",
    "store_candidates",
]
