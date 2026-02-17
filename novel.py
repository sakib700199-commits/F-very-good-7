#!/usr/bin/env python3
"""
novel.py — Production-Grade Enterprise Novel Scraping Platform
==============================================================
A single-file, high-performance, intelligent novel scraping engine
with advanced bypass, live dashboard, and deep monitoring.

Server Target: 12GB RAM / 15 CPU cores / 112GB Storage
"""

import os
import re
import sys
import json
import time
import uuid
import gzip
import shutil
import signal
import struct
import hashlib
import logging
import mimetypes
import pickle
import socket
import string
import threading
import traceback
import unicodedata
import urllib.parse
import zipfile
import html as html_module
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import (
    Any, Callable, Dict, List, Optional, Set, Tuple, Union
)
from enum import Enum
from collections import deque, OrderedDict
from concurrent.futures import (
    ThreadPoolExecutor, ProcessPoolExecutor, as_completed, Future
)
from functools import wraps, lru_cache
import multiprocessing as mp

# --- Third-party imports with graceful fallback ---
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry as URLRetry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from flask import (
        Flask, render_template_string, request, jsonify,
        send_file, redirect, url_for, Response, stream_with_context
    )
    HAS_FLASK = True
except ImportError:
    HAS_FLASK = False

try:
    from bs4 import BeautifulSoup, Comment
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    import chardet
    HAS_CHARDET = True
except ImportError:
    HAS_CHARDET = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

try:
    import ebooklib
    from ebooklib import epub
    HAS_EPUB = True
except ImportError:
    HAS_EPUB = False

import random
import queue

# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "scraper_data"
JOBS_DIR = DATA_DIR / "jobs"
LOGS_DIR = DATA_DIR / "logs"
OUTPUT_DIR = DATA_DIR / "output"
STATE_DIR = DATA_DIR / "state"
COOKIE_DIR = DATA_DIR / "cookies"

for d in [DATA_DIR, JOBS_DIR, LOGS_DIR, OUTPUT_DIR, STATE_DIR, COOKIE_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class Config:
    """Global configuration with environment override support."""
    SECRET_KEY = os.environ.get("SCRAPER_SECRET", "novel-scraper-secret-key-2024")
    MAX_WORKERS = min(int(os.environ.get("MAX_WORKERS", "10")), 15)
    MAX_CHAPTERS = int(os.environ.get("MAX_CHAPTERS", "50000"))
    MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
    REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", "30"))
    BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "45000"))
    MIN_DELAY = float(os.environ.get("MIN_DELAY", "0.3"))
    MAX_DELAY = float(os.environ.get("MAX_DELAY", "3.0"))
    RATE_LIMIT_PAUSE = int(os.environ.get("RATE_LIMIT_PAUSE", "30"))
    MAX_LOG_LINES = int(os.environ.get("MAX_LOG_LINES", "5000"))
    CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "50"))
    CPU_COUNT = min(mp.cpu_count(), 15)
    RAM_LIMIT_MB = int(os.environ.get("RAM_LIMIT_MB", "8192"))
    PORT = int(os.environ.get("PORT", "5000"))
    HOST = os.environ.get("HOST", "0.0.0.0")
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"


# ============================================================
# LOGGING SYSTEM
# ============================================================

class BoundedMemoryHandler(logging.Handler):
    """Keeps last N log records in memory for dashboard."""
    def __init__(self, capacity=5000):
        super().__init__()
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)
        self.lock_obj = threading.Lock()

    def emit(self, record):
        with self.lock_obj:
            self.buffer.append(self.format(record))

    def get_logs(self, n=200):
        with self.lock_obj:
            return list(self.buffer)[-n:]

    def clear(self):
        with self.lock_obj:
            self.buffer.clear()


def setup_logging():
    logger = logging.getLogger("NovelScraper")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    fh = logging.FileHandler(LOGS_DIR / "scraper.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    mem_handler = BoundedMemoryHandler(Config.MAX_LOG_LINES)
    mem_handler.setLevel(logging.DEBUG)
    mem_handler.setFormatter(fmt)
    logger.addHandler(mem_handler)

    return logger, mem_handler


logger, memory_log_handler = setup_logging()


# ============================================================
# ENUMS AND DATA CLASSES
# ============================================================

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESUMING = "resuming"


class FetchMode(Enum):
    HTTP = "http"
    CLOUDSCRAPER = "cloudscraper"
    BROWSER = "browser"
    SLOW = "slow"


class ScrapeMode(Enum):
    PATTERN = "pattern"
    SMART = "smart"


@dataclass
class ChapterResult:
    chapter_number: int
    url: str
    title: str = ""
    content: str = ""
    status: str = "pending"
    response_code: int = 0
    response_time: float = 0.0
    retry_count: int = 0
    mode_used: str = ""
    content_size: int = 0
    cleaned_size: int = 0
    error_type: str = ""
    error_message: str = ""
    fetch_start_time: float = 0.0
    fetch_end_time: float = 0.0
    encoding_used: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class JobConfig:
    job_id: str = ""
    url_pattern: str = ""
    start_chapter: int = 1
    end_chapter: int = 100
    scrape_mode: str = "pattern"
    content_selector: str = ""
    title_selector: str = ""
    next_button_selector: str = ""
    start_url: str = ""
    max_workers: int = 5
    delay_min: float = 0.5
    delay_max: float = 2.0
    output_format: str = "single_txt"
    novel_name: str = "Novel"
    login_url: str = ""
    login_user: str = ""
    login_pass: str = ""
    cookies_json: str = ""
    use_browser: bool = False
    auto_detect_encoding: bool = True
    remove_watermark: bool = True
    created_at: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class JobState:
    job_id: str
    config: JobConfig
    status: JobStatus = JobStatus.PENDING
    chapters: Dict[int, ChapterResult] = field(default_factory=dict)
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    total_chapters: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    current_delay: float = 1.0
    active_threads: int = 0
    avg_response_time: float = 0.0
    current_speed: float = 0.0
    estimated_eta: str = ""
    error_log: List[str] = field(default_factory=list)
    last_successful_chapter: int = 0
    output_files: List[str] = field(default_factory=list)

    def to_dict(self):
        d = {
            "job_id": self.job_id,
            "config": self.config.to_dict(),
            "status": self.status.value,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "total_chapters": self.total_chapters,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "current_delay": self.current_delay,
            "active_threads": self.active_threads,
            "avg_response_time": self.avg_response_time,
            "current_speed": self.current_speed,
            "estimated_eta": self.estimated_eta,
            "last_successful_chapter": self.last_successful_chapter,
            "output_files": self.output_files,
            "error_log": self.error_log[-50:],
            "chapters_summary": {
                "total": self.total_chapters,
                "completed": self.completed_count,
                "failed": self.failed_count,
                "pending": self.total_chapters - self.completed_count - self.failed_count - self.skipped_count
            }
        }
        return d


# ============================================================
# USER-AGENT ROTATION
# ============================================================

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


# ============================================================
# ANTI-DETECTION ENGINE
# ============================================================

class AntiDetectionEngine:
    """Handles all anti-detection, rotation, and bypass logic."""

    def __init__(self):
        self.lock = threading.Lock()
        self.consecutive_blocks = 0
        self.total_requests = 0
        self.blocked_requests = 0
        self.current_mode = FetchMode.HTTP
        self.delay_multiplier = 1.0
        self._session_cache: Dict[str, requests.Session] = {}

    def get_headers(self, url: str, extra_headers: Optional[Dict] = None) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(url)
        ua = random.choice(USER_AGENTS)
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
            "Referer": f"{parsed.scheme}://{parsed.netloc}/",
            "DNT": "1",
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def get_session(self, domain: str) -> requests.Session:
        if not HAS_REQUESTS:
            raise RuntimeError("requests library not installed")
        with self.lock:
            if domain not in self._session_cache:
                session = requests.Session()
                retry_strategy = URLRetry(
                    total=3,
                    backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504],
                    allowed_methods=["GET", "POST"]
                )
                adapter = HTTPAdapter(
                    max_retries=retry_strategy,
                    pool_connections=20,
                    pool_maxsize=20,
                    pool_block=False
                )
                session.mount("http://", adapter)
                session.mount("https://", adapter)
                self._session_cache[domain] = session
            return self._session_cache[domain]

    def get_cloudscraper_session(self) -> Any:
        if HAS_CLOUDSCRAPER:
            scraper = cloudscraper.create_scraper(
                browser={
                    "browser": "chrome",
                    "platform": "windows",
                    "desktop": True,
                }
            )
            return scraper
        return None

    def get_delay(self, base_min: float = 0.3, base_max: float = 2.0) -> float:
        d = random.uniform(base_min, base_max) * self.delay_multiplier
        # Add micro-jitter for human-like behavior
        d += random.uniform(0.01, 0.15)
        return min(d, 30.0)

    def report_success(self):
        with self.lock:
            self.total_requests += 1
            self.consecutive_blocks = 0
            if self.delay_multiplier > 1.0:
                self.delay_multiplier = max(1.0, self.delay_multiplier * 0.95)

    def report_block(self, status_code: int = 0):
        with self.lock:
            self.total_requests += 1
            self.blocked_requests += 1
            self.consecutive_blocks += 1
            # Increase delay on blocks
            if self.consecutive_blocks >= 3:
                self.delay_multiplier = min(self.delay_multiplier * 1.5, 10.0)
            if self.consecutive_blocks >= 5:
                self.delay_multiplier = min(self.delay_multiplier * 2.0, 15.0)

    def should_switch_mode(self) -> Optional[FetchMode]:
        with self.lock:
            if self.consecutive_blocks >= 3 and self.current_mode == FetchMode.HTTP:
                if HAS_CLOUDSCRAPER:
                    self.current_mode = FetchMode.CLOUDSCRAPER
                    return FetchMode.CLOUDSCRAPER
                elif HAS_PLAYWRIGHT:
                    self.current_mode = FetchMode.BROWSER
                    return FetchMode.BROWSER
            if self.consecutive_blocks >= 5 and self.current_mode == FetchMode.CLOUDSCRAPER:
                if HAS_PLAYWRIGHT:
                    self.current_mode = FetchMode.BROWSER
                    return FetchMode.BROWSER
            if self.consecutive_blocks >= 8:
                self.current_mode = FetchMode.SLOW
                return FetchMode.SLOW
            return None

    def reset_blocks(self):
        with self.lock:
            self.consecutive_blocks = 0
            self.current_mode = FetchMode.HTTP
            self.delay_multiplier = 1.0

    def load_cookies(self, session: requests.Session, cookie_path: Path):
        if cookie_path.exists():
            try:
                with open(cookie_path, "r", encoding="utf-8") as f:
                    cookies = json.load(f)
                for c in cookies:
                    session.cookies.set(c.get("name", ""), c.get("value", ""), domain=c.get("domain", ""))
                logger.info(f"Loaded {len(cookies)} cookies from {cookie_path}")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")

    def save_cookies(self, session: requests.Session, cookie_path: Path):
        try:
            cookies = []
            for c in session.cookies:
                cookies.append({
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain,
                    "path": c.path,
                })
            with open(cookie_path, "w", encoding="utf-8") as f:
                json.dump(cookies, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    def close_all(self):
        for s in self._session_cache.values():
            try:
                s.close()
            except Exception:
                pass
        self._session_cache.clear()


# ============================================================
# EXTRACTION ENGINE
# ============================================================

class ExtractionEngine:
    """Intelligent content extraction with cleaning."""

    JUNK_PATTERNS = [
        re.compile(r'<script[\s\S]*?</script>', re.I),
        re.compile(r'<style[\s\S]*?</style>', re.I),
        re.compile(r'<iframe[\s\S]*?</iframe>', re.I),
        re.compile(r'<noscript[\s\S]*?</noscript>', re.I),
        re.compile(r'<!--[\s\S]*?-->', re.I),
    ]

    WATERMARK_PATTERNS = [
        re.compile(r'(本章未完.*?点击下一页继续阅读)', re.I),
        re.compile(r'(请记住本站域名.*?)(?:\n|$)', re.I),
        re.compile(r'(手机版阅读网址.*?)(?:\n|$)', re.I),
        re.compile(r'(最新章节.*?请关注.*?)(?:\n|$)', re.I),
        re.compile(r'(www\.[a-zA-Z0-9]+\.(com|net|org|cc|me))', re.I),
        re.compile(r'(http[s]?://\S+)', re.I),
        re.compile(r'(笔趣阁|笔下文学|书迷楼|顶点小说)', re.I),
        re.compile(r'(天才一秒记住.*?)(?:\n|$)', re.I),
        re.compile(r'(喜欢.*?请大家收藏.*?)(?:\n|$)', re.I),
        re.compile(r'(百度搜索.*?)(?:\n|$)', re.I),
    ]

    CONTENT_SELECTORS = [
        "#content",
        "#chaptercontent",
        "#chapter-content",
        "#booktxt",
        "#booktext",
        "#htmlContent",
        "#TextContent",
        "#text_content",
        "#novel_content",
        ".content",
        ".chapter-content",
        ".chapter_content",
        ".booktext",
        ".read-content",
        ".readcontent",
        ".novel-content",
        ".text-content",
        ".reader-content",
        ".article-content",
        ".entry-content",
        "article .content",
        "div.content",
        "#reader .content",
        ".box_con #content",
        "#wrapper .content",
    ]

    TITLE_SELECTORS = [
        "h1.chapter-title",
        "h1.bookname",
        ".chapter-title",
        ".bookname",
        "h1",
        ".chapter_title",
        "#chapter-title",
        ".title",
        "h2.title",
        "h3.title",
    ]

    NEXT_SELECTORS = [
        'a[rel="next"]',
        'a:contains("下一章")',
        'a:contains("下一页")',
        'a:contains("Next")',
        'a:contains("next chapter")',
        '#next_url',
        '#pager_next',
        '.next a',
        '.next-page a',
        'a.next',
        '#next',
        '.bottem a:last-child',
        '#linkNext',
    ]

    NAV_SELECTORS_TO_REMOVE = [
        "header", "footer", "nav", ".nav", ".navbar",
        ".header", ".footer", ".sidebar", ".ad", ".ads",
        ".advertisement", ".social-share", ".comments",
        ".comment-section", "#comments", ".pagination",
        ".breadcrumb", ".bookmark", ".toolbar", ".menu",
        "#header", "#footer", "#sidebar", "#nav",
        ".read-nav", ".chapter-nav", ".page-nav",
        "script", "style", "iframe", "noscript",
    ]

    def __init__(self):
        self.content_selector_cache: Dict[str, str] = {}

    def detect_encoding(self, raw_bytes: bytes) -> str:
        """Detect encoding from raw bytes."""
        # Check BOM
        if raw_bytes[:3] == b'\xef\xbb\xbf':
            return 'utf-8'
        if raw_bytes[:2] in (b'\xff\xfe', b'\xfe\xff'):
            return 'utf-16'

        # Check meta tags
        head = raw_bytes[:2048].decode('ascii', errors='ignore').lower()
        meta_match = re.search(r'charset=["\']?([a-zA-Z0-9_-]+)', head)
        if meta_match:
            enc = meta_match.group(1).strip().lower()
            enc_map = {'gb2312': 'gbk', 'gb18030': 'gbk'}
            return enc_map.get(enc, enc)

        # Use chardet
        if HAS_CHARDET:
            det = chardet.detect(raw_bytes[:10000])
            if det and det.get('encoding') and det.get('confidence', 0) > 0.5:
                enc = det['encoding'].lower()
                if enc in ('gb2312', 'gb18030'):
                    return 'gbk'
                return enc

        return 'utf-8'

    def decode_content(self, raw_bytes: bytes, declared_encoding: str = '') -> Tuple[str, str]:
        """Try multiple encodings to decode content."""
        encodings_to_try = []
        if declared_encoding:
            encodings_to_try.append(declared_encoding)

        detected = self.detect_encoding(raw_bytes)
        if detected and detected not in encodings_to_try:
            encodings_to_try.append(detected)

        encodings_to_try.extend(['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin-1'])

        for enc in encodings_to_try:
            try:
                text = raw_bytes.decode(enc)
                # Verify it's not garbled by checking for common chars
                if len(text) > 0:
                    return text, enc
            except (UnicodeDecodeError, LookupError):
                continue

        return raw_bytes.decode('utf-8', errors='replace'), 'utf-8-fallback'

    def extract_content(self, html: str, url: str,
                        content_selector: str = '',
                        title_selector: str = '',
                        remove_watermark: bool = True) -> Tuple[str, str]:
        """Extract main content and title from HTML."""
        if not HAS_BS4:
            return self._fallback_extract(html), ""

        soup = BeautifulSoup(html, 'html.parser')

        # Extract title
        title = self._extract_title(soup, title_selector)

        # Extract content
        content = self._extract_body(soup, url, content_selector)

        # Clean content
        content = self._clean_content(content, remove_watermark)

        return title, content

    def _extract_title(self, soup: BeautifulSoup, selector: str = '') -> str:
        if selector:
            el = soup.select_one(selector)
            if el:
                return el.get_text(strip=True)

        for sel in self.TITLE_SELECTORS:
            try:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    if 3 < len(text) < 200:
                        return text
            except Exception:
                continue

        title_tag = soup.find("title")
        if title_tag:
            text = title_tag.get_text(strip=True)
            text = re.split(r'[-_|–—]', text)[0].strip()
            if text:
                return text

        return ""

    def _extract_body(self, soup: BeautifulSoup, url: str, selector: str = '') -> str:
        domain = urllib.parse.urlparse(url).netloc

        # Use provided selector first
        if selector:
            el = soup.select_one(selector)
            if el:
                self.content_selector_cache[domain] = selector
                return self._element_to_text(el)

        # Use cached selector for domain
        if domain in self.content_selector_cache:
            cached = self.content_selector_cache[domain]
            el = soup.select_one(cached)
            if el:
                text = self._element_to_text(el)
                if len(text) > 100:
                    return text

        # Try known selectors
        for sel in self.CONTENT_SELECTORS:
            try:
                el = soup.select_one(sel)
                if el:
                    text = self._element_to_text(el)
                    if len(text) > 100:
                        self.content_selector_cache[domain] = sel
                        return text
            except Exception:
                continue

        # Auto-detect: find largest text block
        return self._auto_detect_content(soup, domain)

    def _auto_detect_content(self, soup: BeautifulSoup, domain: str) -> str:
        """Find the DOM element with the most text content."""
        # Remove known non-content elements
        for sel in self.NAV_SELECTORS_TO_REMOVE:
            for tag in soup.select(sel):
                tag.decompose()

        # Remove comments
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        best_el = None
        best_len = 0

        for tag in soup.find_all(['div', 'article', 'section', 'main', 'td']):
            text = tag.get_text(separator='\n', strip=True)
            # Filter: content should have substantial text
            # and text density should be high
            if len(text) > best_len and len(text) > 200:
                # Check text density
                html_len = len(str(tag))
                if html_len > 0:
                    density = len(text) / html_len
                    if density > 0.15:
                        best_el = tag
                        best_len = len(text)

        if best_el:
            # Try to get a CSS selector for caching
            if best_el.get('id'):
                self.content_selector_cache[domain] = f"#{best_el['id']}"
            elif best_el.get('class'):
                cls = best_el['class'][0]
                self.content_selector_cache[domain] = f".{cls}"
            return self._element_to_text(best_el)

        # Absolute fallback: get body text
        body = soup.find('body')
        if body:
            return self._element_to_text(body)
        return soup.get_text(separator='\n', strip=True)

    def _element_to_text(self, el) -> str:
        """Convert element to clean text, preserving paragraph structure."""
        # Remove unwanted child elements
        for sel in self.NAV_SELECTORS_TO_REMOVE:
            for tag in el.select(sel):
                tag.decompose()

        # Convert <br> to newline
        for br in el.find_all('br'):
            br.replace_with('\n')

        # Convert <p> to text with newlines
        for p in el.find_all('p'):
            p.insert_before('\n')
            p.insert_after('\n')

        text = el.get_text(separator='\n')
        return text

    def _clean_content(self, text: str, remove_watermark: bool = True) -> str:
        """Clean extracted text content."""
        if not text:
            return ""

        # Decode HTML entities
        text = html_module.unescape(text)

        # Remove watermarks
        if remove_watermark:
            for pattern in self.WATERMARK_PATTERNS:
                text = pattern.sub('', text)

        # Clean whitespace
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            # Remove lines that are just whitespace/special chars
            if line and not re.match(r'^[\s\u3000\xa0·.…—\-_=+*#@!]+$', line):
                # Normalize whitespace within line
                line = re.sub(r'[\s\u3000\xa0]+', ' ', line).strip()
                cleaned_lines.append(line)

        # Remove consecutive duplicate lines
        deduped = []
        for line in cleaned_lines:
            if not deduped or line != deduped[-1]:
                deduped.append(line)

        # Join with proper paragraph spacing
        text = '\n\n'.join(deduped)

        # Remove excessive newlines
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    def _fallback_extract(self, html: str) -> str:
        """Fallback extraction without BeautifulSoup."""
        # Remove scripts and styles
        for pattern in self.JUNK_PATTERNS:
            html = pattern.sub('', html)
        # Remove tags
        text = re.sub(r'<br\s*/?\s*>', '\n', html, flags=re.I)
        text = re.sub(r'</p>', '\n', text, flags=re.I)
        text = re.sub(r'<[^>]+>', '', text)
        text = html_module.unescape(text)
        return text.strip()

    def find_next_url(self, html: str, current_url: str,
                      next_selector: str = '') -> Optional[str]:
        """Find the next chapter URL from current page."""
        if not HAS_BS4:
            return None

        soup = BeautifulSoup(html, 'html.parser')

        # Try provided selector
        if next_selector:
            el = soup.select_one(next_selector)
            if el and el.get('href'):
                return urllib.parse.urljoin(current_url, el['href'])

        # Try standard selectors
        for sel in self.NEXT_SELECTORS:
            try:
                if ':contains(' in sel:
                    # Manual text search
                    text_match = re.search(r':contains\("(.+?)"\)', sel)
                    if text_match:
                        search_text = text_match.group(1)
                        for a in soup.find_all('a'):
                            if search_text in (a.get_text() or ''):
                                href = a.get('href', '')
                                if href and href != '#' and 'javascript:' not in href:
                                    return urllib.parse.urljoin(current_url, href)
                else:
                    el = soup.select_one(sel)
                    if el and el.get('href'):
                        href = el['href']
                        if href and href != '#' and 'javascript:' not in href:
                            return urllib.parse.urljoin(current_url, href)
            except Exception:
                continue

        # Try rel="next"
        next_link = soup.find('a', rel='next')
        if next_link and next_link.get('href'):
            return urllib.parse.urljoin(current_url, next_link['href'])

        # Try link rel="next"
        next_link = soup.find('link', rel='next')
        if next_link and next_link.get('href'):
            return urllib.parse.urljoin(current_url, next_link['href'])

        # URL increment fallback
        return self._try_url_increment(current_url)

    def _try_url_increment(self, url: str) -> Optional[str]:
        """Try to increment numeric part of URL."""
        # Match patterns like /chapter-123.html or /123.html or /read/123/
        patterns = [
            (r'(/\d+)(\.html?)', lambda m: f"{int(m.group(1)[1:]) + 1}"),
            (r'[-_](\d+)(\.html?)', lambda m: str(int(m.group(1)) + 1)),
            (r'/(\d+)/?$', lambda m: str(int(m.group(1)) + 1)),
        ]
        for pattern, _ in patterns:
            match = re.search(pattern, url)
            if match:
                num = re.search(r'\d+', match.group())
                if num:
                    old_num = num.group()
                    new_num = str(int(old_num) + 1)
                    # Preserve zero padding
                    if old_num[0] == '0' and len(old_num) > 1:
                        new_num = new_num.zfill(len(old_num))
                    return url[:match.start() + url[match.start():].index(old_num)] + \
                           new_num + \
                           url[match.start() + url[match.start():].index(old_num) + len(old_num):]
        return None


# ============================================================
# SESSION MANAGER (Login Support)
# ============================================================

class SessionManager:
    """Handles login, session persistence, cookies."""

    def __init__(self, anti_detection: AntiDetectionEngine):
        self.anti_detection = anti_detection
        self.logged_in_sessions: Dict[str, requests.Session] = {}

    def login(self, session: requests.Session, login_url: str,
              username: str, password: str, url: str) -> bool:
        """Attempt to login to the site."""
        if not login_url or not username:
            return False

        try:
            logger.info(f"Attempting login at {login_url}")

            # First, get the login page to find CSRF token and form fields
            headers = self.anti_detection.get_headers(login_url)
            resp = session.get(login_url, headers=headers, timeout=Config.REQUEST_TIMEOUT)

            if not HAS_BS4:
                logger.warning("BeautifulSoup not available for login form parsing")
                return False

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Find login form
            form = soup.find('form', attrs={'method': re.compile(r'post', re.I)})
            if not form:
                form = soup.find('form')

            if not form:
                logger.warning("No login form found")
                return False

            # Extract form data
            form_data = {}
            action = form.get('action', login_url)
            if not action.startswith('http'):
                action = urllib.parse.urljoin(login_url, action)

            # Get all hidden fields (CSRF tokens, etc)
            for inp in form.find_all('input'):
                name = inp.get('name', '')
                if not name:
                    continue
                input_type = inp.get('type', 'text').lower()
                value = inp.get('value', '')

                if input_type == 'hidden':
                    form_data[name] = value
                elif input_type in ('text', 'email'):
                    form_data[name] = username
                elif input_type == 'password':
                    form_data[name] = password

            # If we couldn't find username/password fields, try common names
            if not any(v == username for v in form_data.values()):
                for field_name in ['username', 'user', 'email', 'account', 'login']:
                    if field_name in [inp.get('name', '') for inp in form.find_all('input')]:
                        form_data[field_name] = username
                        break

            if not any(v == password for v in form_data.values()):
                for field_name in ['password', 'pass', 'pwd']:
                    if field_name in [inp.get('name', '') for inp in form.find_all('input')]:
                        form_data[field_name] = password
                        break

            # Submit
            headers['Referer'] = login_url
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            resp = session.post(action, data=form_data, headers=headers,
                                timeout=Config.REQUEST_TIMEOUT, allow_redirects=True)

            # Check success
            if resp.status_code in (200, 302, 303):
                # Verify by checking if we can access the target page
                domain = urllib.parse.urlparse(url).netloc
                cookie_path = COOKIE_DIR / f"{domain}_cookies.json"
                self.anti_detection.save_cookies(session, cookie_path)
                self.logged_in_sessions[domain] = session
                logger.info(f"Login successful for {domain}")
                return True

            logger.warning(f"Login may have failed: status {resp.status_code}")
            return False

        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def import_cookies(self, session: requests.Session, cookies_json: str, url: str):
        """Import cookies from JSON string."""
        try:
            cookies = json.loads(cookies_json)
            if isinstance(cookies, list):
                for c in cookies:
                    session.cookies.set(
                        c.get('name', ''),
                        c.get('value', ''),
                        domain=c.get('domain', ''),
                        path=c.get('path', '/')
                    )
            elif isinstance(cookies, dict):
                for name, value in cookies.items():
                    session.cookies.set(name, value)
            domain = urllib.parse.urlparse(url).netloc
            cookie_path = COOKIE_DIR / f"{domain}_cookies.json"
            self.anti_detection.save_cookies(session, cookie_path)
            logger.info(f"Imported cookies for {domain}")
        except Exception as e:
            logger.error(f"Cookie import error: {e}")


# ============================================================
# BROWSER ENGINE
# ============================================================

class BrowserEngine:
    """Playwright-based browser for JS-rendered pages."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._lock = threading.Lock()

    def _ensure_browser(self):
        if not HAS_PLAYWRIGHT:
            raise RuntimeError("Playwright not installed")
        if self._browser is None:
            with self._lock:
                if self._browser is None:
                    self._pw = sync_playwright().start()
                    self._browser = self._pw.chromium.launch(
                        headless=True,
                        args=[
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                            '--disable-blink-features=AutomationControlled',
                            '--disable-extensions',
                            '--disable-gpu',
                            '--window-size=1920,1080',
                        ]
                    )

    def fetch(self, url: str, timeout: int = 45000) -> Tuple[str, int]:
        """Fetch page using headless browser."""
        self._ensure_browser()
        context = None
        page = None
        try:
            context = self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=random.choice(USER_AGENTS),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                java_script_enabled=True,
            )
            # Stealth patches
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => false});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = {runtime: {}};
            """)
            page = context.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            # Wait for content to load
            page.wait_for_timeout(2000)

            # Try to wait for common content selectors
            for sel in ['#content', '#chaptercontent', '.content', '.chapter-content', 'article']:
                try:
                    page.wait_for_selector(sel, timeout=3000)
                    break
                except Exception:
                    continue

            html = page.content()
            status = resp.status if resp else 200
            return html, status

        except Exception as e:
            logger.error(f"Browser fetch error for {url}: {e}")
            raise
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if context:
                try:
                    context.close()
                except Exception:
                    pass

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None


# ============================================================
# SCRAPER ENGINE (Core)
# ============================================================

class ScraperEngine:
    """Core scraping engine with multi-mode fetch and fallback chain."""

    def __init__(self):
        self.anti_detection = AntiDetectionEngine()
        self.extraction = ExtractionEngine()
        self.session_mgr = SessionManager(self.anti_detection)
        self.browser_engine = BrowserEngine()
        self._active = True

    def fetch_page(self, url: str, job_config: JobConfig,
                   force_mode: Optional[FetchMode] = None) -> Tuple[str, int, str, float]:
        """
        Fetch a page with fallback chain.
        Returns: (html, status_code, mode_used, response_time)
        """
        modes_to_try = []

        if force_mode:
            modes_to_try.append(force_mode)
        elif job_config.use_browser and HAS_PLAYWRIGHT:
            modes_to_try.append(FetchMode.BROWSER)
        else:
            # Build fallback chain
            current = self.anti_detection.current_mode
            if current == FetchMode.HTTP:
                modes_to_try = [FetchMode.HTTP]
                if HAS_CLOUDSCRAPER:
                    modes_to_try.append(FetchMode.CLOUDSCRAPER)
                if HAS_PLAYWRIGHT:
                    modes_to_try.append(FetchMode.BROWSER)
                modes_to_try.append(FetchMode.SLOW)
            elif current == FetchMode.CLOUDSCRAPER:
                modes_to_try = [FetchMode.CLOUDSCRAPER]
                if HAS_PLAYWRIGHT:
                    modes_to_try.append(FetchMode.BROWSER)
                modes_to_try.append(FetchMode.SLOW)
            elif current == FetchMode.BROWSER:
                modes_to_try = [FetchMode.BROWSER, FetchMode.SLOW]
            else:
                modes_to_try = [FetchMode.SLOW]

        last_error = None
        for mode in modes_to_try:
            if not self._active:
                raise InterruptedError("Scraper stopped")
            try:
                start = time.time()
                html, status = self._fetch_with_mode(url, mode, job_config)
                elapsed = time.time() - start

                if status in (200, 301, 302):
                    self.anti_detection.report_success()
                    return html, status, mode.value, elapsed
                elif status in (403, 429, 503):
                    self.anti_detection.report_block(status)
                    logger.warning(f"Blocked ({status}) on {url} with mode {mode.value}")
                    # Check if should switch
                    new_mode = self.anti_detection.should_switch_mode()
                    if new_mode:
                        logger.info(f"Switching to mode: {new_mode.value}")
                    continue
                else:
                    return html, status, mode.value, elapsed
            except Exception as e:
                last_error = e
                logger.warning(f"Fetch failed with mode {mode.value}: {e}")
                continue

        # All modes failed
        if last_error:
            raise last_error
        raise RuntimeError(f"All fetch modes failed for {url}")

    def _fetch_with_mode(self, url: str, mode: FetchMode,
                         config: JobConfig) -> Tuple[str, int]:
        domain = urllib.parse.urlparse(url).netloc

        if mode == FetchMode.HTTP:
            session = self.anti_detection.get_session(domain)
            # Load cookies if available
            cookie_path = COOKIE_DIR / f"{domain}_cookies.json"
            self.anti_detection.load_cookies(session, cookie_path)

            if config.cookies_json:
                self.session_mgr.import_cookies(session, config.cookies_json, url)

            headers = self.anti_detection.get_headers(url)
            resp = session.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT,
                               allow_redirects=True)

            # Handle encoding
            if config.auto_detect_encoding:
                html, _ = self.extraction.decode_content(resp.content, resp.encoding or '')
            else:
                html = resp.text

            self.anti_detection.save_cookies(session, cookie_path)
            return html, resp.status_code

        elif mode == FetchMode.CLOUDSCRAPER:
            if not HAS_CLOUDSCRAPER:
                raise RuntimeError("cloudscraper not installed")
            scraper = self.anti_detection.get_cloudscraper_session()
            headers = self.anti_detection.get_headers(url)
            resp = scraper.get(url, headers=headers, timeout=Config.REQUEST_TIMEOUT)
            if config.auto_detect_encoding:
                html, _ = self.extraction.decode_content(resp.content, resp.encoding or '')
            else:
                html = resp.text
            return html, resp.status_code

        elif mode == FetchMode.BROWSER:
            html, status = self.browser_engine.fetch(url, Config.BROWSER_TIMEOUT)
            return html, status

        elif mode == FetchMode.SLOW:
            # Ultra slow mode - last resort
            time.sleep(random.uniform(5, 10))
            session = self.anti_detection.get_session(domain)
            headers = self.anti_detection.get_headers(url)
            resp = session.get(url, headers=headers, timeout=60, allow_redirects=True)
            if config.auto_detect_encoding:
                html, _ = self.extraction.decode_content(resp.content, resp.encoding or '')
            else:
                html = resp.text
            return html, resp.status_code

        raise ValueError(f"Unknown mode: {mode}")

    def scrape_chapter(self, chapter_num: int, url: str,
                       config: JobConfig) -> ChapterResult:
        """Scrape a single chapter with full error handling and retry."""
        result = ChapterResult(
            chapter_number=chapter_num,
            url=url,
            fetch_start_time=time.time()
        )

        for attempt in range(Config.MAX_RETRIES):
            if not self._active:
                result.status = "cancelled"
                return result

            try:
                html, status, mode, resp_time = self.fetch_page(url, config)
                result.response_code = status
                result.response_time = resp_time
                result.mode_used = mode
                result.retry_count = attempt

                if status == 200:
                    title, content = self.extraction.extract_content(
                        html, url,
                        content_selector=config.content_selector,
                        title_selector=config.title_selector,
                        remove_watermark=config.remove_watermark
                    )
                    result.title = title
                    result.content = content
                    result.content_size = len(html)
                    result.cleaned_size = len(content)
                    result.status = "success" if content else "empty"
                    result.fetch_end_time = time.time()

                    if not content:
                        logger.warning(f"Chapter {chapter_num}: empty content from {url}")

                    return result
                elif status in (404,):
                    result.status = "not_found"
                    result.error_type = "404"
                    return result
                elif status in (403, 429, 503):
                    result.error_type = str(status)
                    # Exponential backoff
                    wait = min(2 ** attempt * 2 + random.uniform(0, 2), 60)
                    logger.warning(f"Chapter {chapter_num}: {status}, retry in {wait:.1f}s (attempt {attempt+1})")
                    time.sleep(wait)
                    continue
                else:
                    result.status = "error"
                    result.error_type = f"http_{status}"
                    return result

            except InterruptedError:
                result.status = "cancelled"
                return result
            except Exception as e:
                result.error_type = type(e).__name__
                result.error_message = str(e)[:500]
                wait = min(2 ** attempt + random.uniform(0, 1), 30)
                logger.error(f"Chapter {chapter_num} attempt {attempt+1} error: {e}")
                if attempt < Config.MAX_RETRIES - 1:
                    time.sleep(wait)

        result.status = "failed"
        result.fetch_end_time = time.time()
        return result

    def stop(self):
        self._active = False

    def resume(self):
        self._active = True

    def close(self):
        self._active = False
        self.anti_detection.close_all()
        self.browser_engine.close()


# ============================================================
# OUTPUT MANAGER
# ============================================================

class OutputManager:
    """Handles all output formats."""

    @staticmethod
    def safe_filename(name: str) -> str:
        """Create a safe filename."""
        name = unicodedata.normalize('NFKC', name)
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
        name = name.strip('. ')
        if not name:
            name = "novel"
        return name[:200]

    def compile_output(self, job_state: JobState) -> List[str]:
        """Compile all chapters into requested output format(s)."""
        config = job_state.config
        novel_name = self.safe_filename(config.novel_name or "Novel")
        job_dir = OUTPUT_DIR / job_state.job_id
        job_dir.mkdir(parents=True, exist_ok=True)

        output_files = []
        fmt = config.output_format

        # Sort chapters
        sorted_chapters = sorted(
            [ch for ch in job_state.chapters.values() if ch.status == "success"],
            key=lambda c: c.chapter_number
        )

        if not sorted_chapters:
            logger.warning("No successful chapters to compile")
            return []

        if fmt in ("single_txt", "all"):
            path = self._write_single_txt(sorted_chapters, job_dir, novel_name)
            if path:
                output_files.append(str(path))

        if fmt in ("separate_files", "all"):
            paths = self._write_separate_files(sorted_chapters, job_dir, novel_name)
            output_files.extend([str(p) for p in paths])

        if fmt in ("json", "all"):
            path = self._write_json(sorted_chapters, job_dir, novel_name, job_state)
            if path:
                output_files.append(str(path))

        if fmt in ("markdown", "all"):
            path = self._write_markdown(sorted_chapters, job_dir, novel_name)
            if path:
                output_files.append(str(path))

        if fmt in ("epub", "all") and HAS_EPUB:
            path = self._write_epub(sorted_chapters, job_dir, novel_name)
            if path:
                output_files.append(str(path))

        if fmt in ("zip", "all"):
            path = self._write_zip(sorted_chapters, job_dir, novel_name)
            if path:
                output_files.append(str(path))

        # Save metadata
        meta_path = job_dir / f"{novel_name}_metadata.json"
        meta = {
            "novel_name": novel_name,
            "total_chapters": len(sorted_chapters),
            "scraped_date": datetime.now().isoformat(),
            "job_id": job_state.job_id,
            "source_pattern": config.url_pattern or config.start_url,
            "chapters": [
                {
                    "number": ch.chapter_number,
                    "title": ch.title,
                    "url": ch.url,
                    "size": ch.cleaned_size,
                }
                for ch in sorted_chapters
            ]
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
        output_files.append(str(meta_path))

        return output_files

    def _write_single_txt(self, chapters, job_dir, name) -> Optional[Path]:
        path = job_dir / f"{name}.txt"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"{'='*60}\n")
                f.write(f"  {name}\n")
                f.write(f"  Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"  Total Chapters: {len(chapters)}\n")
                f.write(f"{'='*60}\n\n")
                for ch in chapters:
                    title = ch.title or f"Chapter {ch.chapter_number}"
                    f.write(f"\n{'─'*50}\n")
                    f.write(f"  --- Chapter {ch.chapter_number}: {title} ---\n")
                    f.write(f"{'─'*50}\n\n")
                    f.write(ch.content or "[No content]")
                    f.write("\n\n")
            logger.info(f"Written single TXT: {path}")
            return path
        except Exception as e:
            logger.error(f"Error writing TXT: {e}")
            return None

    def _write_separate_files(self, chapters, job_dir, name) -> List[Path]:
        ch_dir = job_dir / f"{name}_chapters"
        ch_dir.mkdir(exist_ok=True)
        paths = []
        for ch in chapters:
            title = self.safe_filename(ch.title or f"Chapter_{ch.chapter_number}")
            path = ch_dir / f"{ch.chapter_number:05d}_{title}.txt"
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"--- Chapter {ch.chapter_number}: {ch.title or ''} ---\n\n")
                    f.write(ch.content or "[No content]")
                paths.append(path)
            except Exception as e:
                logger.error(f"Error writing chapter file: {e}")
        return paths

    def _write_json(self, chapters, job_dir, name, job_state) -> Optional[Path]:
        path = job_dir / f"{name}.json"
        try:
            data = {
                "novel_name": name,
                "scraped_date": datetime.now().isoformat(),
                "total_chapters": len(chapters),
                "chapters": [
                    {
                        "number": ch.chapter_number,
                        "title": ch.title,
                        "url": ch.url,
                        "content": ch.content,
                        "content_length": ch.cleaned_size,
                    }
                    for ch in chapters
                ]
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return path
        except Exception as e:
            logger.error(f"Error writing JSON: {e}")
            return None

    def _write_markdown(self, chapters, job_dir, name) -> Optional[Path]:
        path = job_dir / f"{name}.md"
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\n")
                f.write(f"*Scraped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n")
                f.write(f"**Total Chapters: {len(chapters)}**\n\n---\n\n")
                for ch in chapters:
                    title = ch.title or f"Chapter {ch.chapter_number}"
                    f.write(f"## Chapter {ch.chapter_number}: {title}\n\n")
                    f.write(ch.content or "*No content*")
                    f.write("\n\n---\n\n")
            return path
        except Exception as e:
            logger.error(f"Error writing Markdown: {e}")
            return None

    def _write_epub(self, chapters, job_dir, name) -> Optional[Path]:
        if not HAS_EPUB:
            return None
        path = job_dir / f"{name}.epub"
        try:
            book = epub.EpubBook()
            book.set_identifier(f"novel-{uuid.uuid4().hex[:8]}")
            book.set_title(name)
            book.set_language('zh')
            book.add_author('Novel Scraper')

            spine = ['nav']
            toc = []

            for ch in chapters:
                title = ch.title or f"Chapter {ch.chapter_number}"
                chapter = epub.EpubHtml(
                    title=title,
                    file_name=f"chapter_{ch.chapter_number:05d}.xhtml",
                    lang="zh"
                )
                content_html = ch.content.replace('\n', '<br/>\n') if ch.content else ""
                chapter.content = f"<h2>{html_module.escape(title)}</h2><p>{content_html}</p>"
                book.add_item(chapter)
                spine.append(chapter)
                toc.append(chapter)

            book.toc = toc
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = spine
            epub.write_epub(str(path), book)
            return path
        except Exception as e:
            logger.error(f"Error writing EPUB: {e}")
            return None

    def _write_zip(self, chapters, job_dir, name) -> Optional[Path]:
        path = job_dir / f"{name}.zip"
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for ch in chapters:
                    title = self.safe_filename(ch.title or f"Chapter_{ch.chapter_number}")
                    fname = f"{ch.chapter_number:05d}_{title}.txt"
                    content = f"--- Chapter {ch.chapter_number}: {ch.title or ''} ---\n\n"
                    content += ch.content or "[No content]"
                    zf.writestr(fname, content)
            return path
        except Exception as e:
            logger.error(f"Error writing ZIP: {e}")
            return None


# ============================================================
# PERFORMANCE MONITOR
# ============================================================

class PerformanceMonitor:
    """System performance monitoring."""

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        stats = {
            "cpu_count": Config.CPU_COUNT,
            "cpu_percent": 0.0,
            "ram_total_mb": 0,
            "ram_used_mb": 0,
            "ram_percent": 0.0,
            "disk_total_gb": 0,
            "disk_used_gb": 0,
            "disk_free_gb": 0,
        }
        if HAS_PSUTIL:
            try:
                stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
                mem = psutil.virtual_memory()
                stats["ram_total_mb"] = round(mem.total / (1024**2))
                stats["ram_used_mb"] = round(mem.used / (1024**2))
                stats["ram_percent"] = mem.percent
                disk = psutil.disk_usage('/')
                stats["disk_total_gb"] = round(disk.total / (1024**3), 1)
                stats["disk_used_gb"] = round(disk.used / (1024**3), 1)
                stats["disk_free_gb"] = round(disk.free / (1024**3), 1)
            except Exception:
                pass
        return stats


# ============================================================
# JOB MANAGER
# ============================================================

class JobManager:
    """Manages scraping jobs with lifecycle control."""

    def __init__(self):
        self.jobs: Dict[str, JobState] = {}
        self.scraper_engines: Dict[str, ScraperEngine] = {}
        self.job_threads: Dict[str, threading.Thread] = {}
        self.output_manager = OutputManager()
        self.performance = PerformanceMonitor()
        self._lock = threading.Lock()
        self._load_persisted_jobs()

    def _load_persisted_jobs(self):
        """Load completed/failed jobs from disk for history."""
        try:
            for f in STATE_DIR.glob("*.json"):
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    job_id = data.get("job_id", f.stem)
                    config = JobConfig(**data.get("config", {}))
                    state = JobState(job_id=job_id, config=config)
                    state.status = JobStatus(data.get("status", "completed"))
                    state.completed_count = data.get("completed_count", 0)
                    state.failed_count = data.get("failed_count", 0)
                    state.total_chapters = data.get("total_chapters", 0)
                    state.start_time = data.get("start_time", 0)
                    state.end_time = data.get("end_time", 0)
                    state.output_files = data.get("output_files", [])
                    state.last_successful_chapter = data.get("last_successful_chapter", 0)
                    self.jobs[job_id] = state
                except Exception as e:
                    logger.warning(f"Failed to load job state {f}: {e}")
        except Exception as e:
            logger.warning(f"Failed to scan state dir: {e}")

    def _persist_job(self, job_id: str):
        """Save job state to disk."""
        try:
            state = self.jobs.get(job_id)
            if not state:
                return
            data = {
                "job_id": job_id,
                "config": state.config.to_dict(),
                "status": state.status.value,
                "completed_count": state.completed_count,
                "failed_count": state.failed_count,
                "total_chapters": state.total_chapters,
                "start_time": state.start_time,
                "end_time": state.end_time,
                "output_files": state.output_files,
                "last_successful_chapter": state.last_successful_chapter,
            }
            with open(STATE_DIR / f"{job_id}.json", "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to persist job {job_id}: {e}")

    def create_job(self, config: JobConfig) -> str:
        """Create a new scraping job."""
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        config.job_id = job_id
        config.created_at = datetime.now().isoformat()

        # Validate and fix pattern
        if config.scrape_mode == "pattern":
            config.url_pattern = self._validate_pattern(config.url_pattern)

        state = JobState(job_id=job_id, config=config)
        self.jobs[job_id] = state

        logger.info(f"Job created: {job_id}")
        return job_id

    def _validate_pattern(self, pattern: str) -> str:
        """Validate and fix URL pattern."""
        if not pattern:
            return pattern

        # Check if {} exists
        if '{}' not in pattern:
            # Try to find numeric part and replace with {}
            match = re.search(r'(\d+)(\.html?)?$', pattern)
            if match:
                num_start = match.start(1)
                num_end = match.end(1)
                pattern = pattern[:num_start] + '{}' + pattern[num_end:]
                logger.info(f"Auto-fixed pattern: {pattern}")
            else:
                # Append {}
                if pattern.endswith('/'):
                    pattern += '{}.html'
                else:
                    pattern += '/{}.html'
                logger.info(f"Auto-appended pattern: {pattern}")

        # Validate URL
        parsed = urllib.parse.urlparse(pattern.replace('{}', '1'))
        if not parsed.scheme:
            pattern = 'https://' + pattern
        if not parsed.netloc:
            logger.warning(f"Pattern may be invalid: {pattern}")

        return pattern

    def start_job(self, job_id: str):
        """Start a scraping job in background thread."""
        state = self.jobs.get(job_id)
        if not state:
            raise ValueError(f"Job not found: {job_id}")

        if state.status in (JobStatus.RUNNING, JobStatus.RESUMING):
            raise ValueError("Job is already running")

        engine = ScraperEngine()
        self.scraper_engines[job_id] = engine

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"job-{job_id}"
        )
        self.job_threads[job_id] = thread
        state.status = JobStatus.RUNNING
        state.start_time = time.time()
        thread.start()
        logger.info(f"Job started: {job_id}")

    def _run_job(self, job_id: str):
        """Main job execution logic."""
        state = self.jobs[job_id]
        config = state.config
        engine = self.scraper_engines[job_id]

        try:
            # Handle login if needed
            if config.login_url and config.login_user:
                domain = urllib.parse.urlparse(config.url_pattern or config.start_url).netloc
                session = engine.anti_detection.get_session(domain)
                engine.session_mgr.login(
                    session, config.login_url,
                    config.login_user, config.login_pass,
                    config.url_pattern or config.start_url
                )

            if config.scrape_mode == "pattern":
                self._run_pattern_mode(job_id)
            elif config.scrape_mode == "smart":
                self._run_smart_mode(job_id)
            else:
                raise ValueError(f"Unknown scrape mode: {config.scrape_mode}")

            # Compile output
            if state.status not in (JobStatus.CANCELLED, JobStatus.FAILED):
                state.output_files = self.output_manager.compile_output(state)
                state.status = JobStatus.COMPLETED

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}\n{traceback.format_exc()}")
            state.status = JobStatus.FAILED
            state.error_log.append(f"Fatal: {str(e)}")
        finally:
            state.end_time = time.time()
            engine.close()
            self._persist_job(job_id)
            logger.info(f"Job {job_id} finished: {state.status.value}")

    def _run_pattern_mode(self, job_id: str):
        """Run pattern-based scraping with thread pool."""
        state = self.jobs[job_id]
        config = state.config
        engine = self.scraper_engines[job_id]

        start = config.start_chapter
        end = min(config.end_chapter, config.start_chapter + Config.MAX_CHAPTERS - 1)
        state.total_chapters = end - start + 1

        # Generate URLs
        urls = {}
        for i in range(start, end + 1):
            url = config.url_pattern.replace('{}', str(i))
            urls[i] = url

        # Resume support: skip already completed
        completed_chapters = {ch_num for ch_num, ch in state.chapters.items() if ch.status == "success"}
        pending = {k: v for k, v in urls.items() if k not in completed_chapters}

        max_workers = min(config.max_workers, Config.MAX_WORKERS)
        response_times = deque(maxlen=100)
        chapters_done_since_start = 0
        speed_start_time = time.time()

        # Process in chunks
        chunk_keys = sorted(pending.keys())

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scrape") as pool:
            futures: Dict[Future, int] = {}

            for chunk_start in range(0, len(chunk_keys), Config.CHUNK_SIZE):
                if state.status in (JobStatus.CANCELLED, JobStatus.PAUSED):
                    break

                chunk = chunk_keys[chunk_start:chunk_start + Config.CHUNK_SIZE]

                for ch_num in chunk:
                    if state.status in (JobStatus.CANCELLED, JobStatus.PAUSED):
                        break

                    # Dynamic worker adjustment
                    current_workers = min(max_workers, max(1, max_workers - engine.anti_detection.consecutive_blocks))
                    state.active_threads = len([f for f in futures.values() if not isinstance(f, int)])

                    # Wait if too many active
                    while len(futures) >= current_workers:
                        done_futures = [f for f in futures if f.done()]
                        if not done_futures:
                            time.sleep(0.1)
                            continue
                        for df in done_futures:
                            ch = df.result()
                            state.chapters[ch.chapter_number] = ch
                            if ch.status == "success":
                                state.completed_count += 1
                                state.last_successful_chapter = max(
                                    state.last_successful_chapter, ch.chapter_number
                                )
                                chapters_done_since_start += 1
                            elif ch.status == "failed":
                                state.failed_count += 1
                                state.error_log.append(
                                    f"Ch {ch.chapter_number}: {ch.error_type} - {ch.error_message[:200]}"
                                )
                            elif ch.status == "not_found":
                                state.skipped_count += 1

                            if ch.response_time > 0:
                                response_times.append(ch.response_time)

                            del futures[df]

                    # Update stats
                    if response_times:
                        state.avg_response_time = sum(response_times) / len(response_times)
                    elapsed = time.time() - speed_start_time
                    if elapsed > 0:
                        state.current_speed = chapters_done_since_start / (elapsed / 60)
                    remaining = state.total_chapters - state.completed_count - state.failed_count - state.skipped_count
                    if state.current_speed > 0:
                        eta_minutes = remaining / state.current_speed
                        state.estimated_eta = str(timedelta(minutes=int(eta_minutes)))
                    state.current_delay = engine.anti_detection.get_delay(config.delay_min, config.delay_max)

                    # Submit task
                    delay = engine.anti_detection.get_delay(config.delay_min, config.delay_max)
                    time.sleep(delay)
                    future = pool.submit(engine.scrape_chapter, ch_num, pending[ch_num], config)
                    futures[future] = ch_num

                # Collect remaining futures from chunk
                for f in as_completed(futures):
                    try:
                        ch = f.result(timeout=120)
                        state.chapters[ch.chapter_number] = ch
                        if ch.status == "success":
                            state.completed_count += 1
                            state.last_successful_chapter = max(
                                state.last_successful_chapter, ch.chapter_number
                            )
                            chapters_done_since_start += 1
                        elif ch.status == "failed":
                            state.failed_count += 1
                        elif ch.status == "not_found":
                            state.skipped_count += 1
                        if ch.response_time > 0:
                            response_times.append(ch.response_time)
                    except Exception as e:
                        logger.error(f"Future error: {e}")
                futures.clear()

            state.active_threads = 0

    def _run_smart_mode(self, job_id: str):
        """Run smart detection mode - follow next links."""
        state = self.jobs[job_id]
        config = state.config
        engine = self.scraper_engines[job_id]

        current_url = config.start_url
        if not current_url:
            raise ValueError("Smart mode requires start_url")

        visited_urls: Set[str] = set()
        visited_hashes: Set[str] = set()
        chapter_num = config.start_chapter
        max_chapters = min(config.end_chapter - config.start_chapter + 1, Config.MAX_CHAPTERS)
        state.total_chapters = max_chapters  # Estimated, will update

        while chapter_num <= config.start_chapter + max_chapters - 1:
            if state.status in (JobStatus.CANCELLED, JobStatus.PAUSED):
                break

            if current_url in visited_urls:
                logger.warning(f"Loop detected at {current_url}, stopping")
                break
            visited_urls.add(current_url)

            # Fetch chapter
            delay = engine.anti_detection.get_delay(config.delay_min, config.delay_max)
            time.sleep(delay)

            result = engine.scrape_chapter(chapter_num, current_url, config)

            # Duplicate detection
            if result.content:
                content_hash = hashlib.md5(result.content.encode()).hexdigest()
                if content_hash in visited_hashes:
                    logger.warning(f"Duplicate content at chapter {chapter_num}, stopping")
                    result.status = "duplicate"
                    state.skipped_count += 1
                    break
                visited_hashes.add(content_hash)

            state.chapters[chapter_num] = result
            if result.status == "success":
                state.completed_count += 1
                state.last_successful_chapter = chapter_num
            elif result.status == "failed":
                state.failed_count += 1
            elif result.status == "not_found":
                state.skipped_count += 1
                break

            # Update progress
            state.total_chapters = max(state.total_chapters, chapter_num)
            elapsed = time.time() - state.start_time if state.start_time else 1
            state.current_speed = state.completed_count / (elapsed / 60) if elapsed > 0 else 0

            # Find next URL
            try:
                html, _, _, _ = engine.fetch_page(current_url, config)
                next_url = engine.extraction.find_next_url(
                    html, current_url, config.next_button_selector
                )
            except Exception:
                next_url = None

            if not next_url:
                logger.info(f"No next URL found after chapter {chapter_num}")
                break

            # Normalize URL
            next_url = urllib.parse.urljoin(current_url, next_url)
            current_url = next_url
            chapter_num += 1

        state.total_chapters = chapter_num - config.start_chapter

    def pause_job(self, job_id: str):
        state = self.jobs.get(job_id)
        if state and state.status == JobStatus.RUNNING:
            state.status = JobStatus.PAUSED
            engine = self.scraper_engines.get(job_id)
            if engine:
                engine.stop()
            logger.info(f"Job paused: {job_id}")

    def resume_job(self, job_id: str):
        state = self.jobs.get(job_id)
        if state and state.status == JobStatus.PAUSED:
            engine = ScraperEngine()
            self.scraper_engines[job_id] = engine
            state.status = JobStatus.RESUMING
            thread = threading.Thread(
                target=self._run_job,
                args=(job_id,),
                daemon=True,
                name=f"job-{job_id}-resume"
            )
            self.job_threads[job_id] = thread
            state.status = JobStatus.RUNNING
            thread.start()
            logger.info(f"Job resumed: {job_id}")

    def cancel_job(self, job_id: str):
        state = self.jobs.get(job_id)
        if state and state.status in (JobStatus.RUNNING, JobStatus.PAUSED, JobStatus.RESUMING):
            state.status = JobStatus.CANCELLED
            engine = self.scraper_engines.get(job_id)
            if engine:
                engine.stop()
            state.end_time = time.time()
            self._persist_job(job_id)
            logger.info(f"Job cancelled: {job_id}")

    def delete_job(self, job_id: str):
        self.cancel_job(job_id)
        if job_id in self.jobs:
            del self.jobs[job_id]
        state_file = STATE_DIR / f"{job_id}.json"
        if state_file.exists():
            state_file.unlink()
        job_output = OUTPUT_DIR / job_id
        if job_output.exists():
            shutil.rmtree(job_output, ignore_errors=True)

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        state = self.jobs.get(job_id)
        if not state:
            return None
        return state.to_dict()

    def get_job_chapters(self, job_id: str) -> List[Dict]:
        state = self.jobs.get(job_id)
        if not state:
            return []
        return [ch.to_dict() for ch in sorted(state.chapters.values(), key=lambda c: c.chapter_number)]

    def get_all_jobs(self) -> List[Dict]:
        result = []
        for jid, state in sorted(self.jobs.items(), key=lambda x: x[1].config.created_at or '', reverse=True):
            result.append({
                "job_id": jid,
                "novel_name": state.config.novel_name,
                "status": state.status.value,
                "progress": f"{state.completed_count}/{state.total_chapters}",
                "created_at": state.config.created_at,
                "output_files": len(state.output_files),
            })
        return result

    def get_output_files(self, job_id: str) -> List[Dict]:
        state = self.jobs.get(job_id)
        if not state:
            return []
        files = []
        for fp in state.output_files:
            p = Path(fp)
            if p.exists():
                files.append({
                    "name": p.name,
                    "path": str(p),
                    "size": p.stat().st_size,
                    "size_human": self._human_size(p.stat().st_size),
                })
        return files

    @staticmethod
    def _human_size(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


# ============================================================
# GLOBAL INSTANCES
# ============================================================

job_manager = JobManager()


# ============================================================
# FLASK WEB DASHBOARD
# ============================================================

DASHBOARD_HTML = r'''
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🔥 Novel Scraper Engine</title>
    <style>
        :root {
            --bg-primary: #0d0d0d;
            --bg-secondary: #1a1a2e;
            --bg-card: #16213e;
            --bg-input: #0f3460;
            --text-primary: #e94560;
            --text-secondary: #f5c6d0;
            --text-white: #ffffff;
            --accent-pink: #e94560;
            --accent-purple: #a855f7;
            --accent-hot: #ff2e63;
            --accent-glow: #ff6b9d;
            --border-color: #e94560;
            --success: #00e676;
            --error: #ff1744;
            --warning: #ffab00;
            --info: #00b0ff;
            --gradient-1: linear-gradient(135deg, #e94560, #a855f7);
            --gradient-2: linear-gradient(135deg, #0f3460, #1a1a2e);
            --shadow-glow: 0 0 20px rgba(233, 69, 96, 0.3);
        }
        [data-theme="light"] {
            --bg-primary: #fdf2f8;
            --bg-secondary: #fce7f3;
            --bg-card: #ffffff;
            --bg-input: #fdf2f8;
            --text-primary: #be185d;
            --text-secondary: #9d174d;
            --text-white: #1a1a1a;
            --border-color: #ec4899;
            --shadow-glow: 0 0 20px rgba(236, 72, 153, 0.2);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg-primary);
            color: var(--text-white);
            min-height: 100vh;
            overflow-x: hidden;
        }
        .top-bar {
            background: var(--gradient-1);
            padding: 12px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 20px rgba(233,69,96,0.4);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .top-bar h1 {
            font-size: 1.5em;
            font-weight: 800;
            letter-spacing: 1px;
        }
        .top-bar .controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .theme-toggle {
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
            transition: 0.3s;
        }
        .theme-toggle:hover { background: rgba(255,255,255,0.3); }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: var(--shadow-glow);
            transition: transform 0.3s, box-shadow 0.3s;
        }
        .stat-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 0 30px rgba(233,69,96,0.5);
        }
        .stat-card .label {
            font-size: 12px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }
        .stat-card .value {
            font-size: 1.8em;
            font-weight: 800;
            color: var(--accent-pink);
        }
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: var(--shadow-glow);
        }
        .card h2 {
            color: var(--accent-pink);
            margin-bottom: 20px;
            font-size: 1.3em;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 16px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .form-group label {
            font-size: 13px;
            color: var(--text-secondary);
            font-weight: 600;
        }
        .form-group input, .form-group select, .form-group textarea {
            background: var(--bg-input);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 14px;
            color: var(--text-white);
            font-size: 14px;
            transition: 0.3s;
            outline: none;
        }
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            border-color: var(--accent-hot);
            box-shadow: 0 0 10px rgba(233,69,96,0.3);
        }
        .btn {
            padding: 10px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 700;
            font-size: 14px;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .btn-primary {
            background: var(--gradient-1);
            color: white;
        }
        .btn-primary:hover {
            box-shadow: 0 0 20px rgba(233,69,96,0.5);
            transform: translateY(-2px);
        }
        .btn-success { background: var(--success); color: #000; }
        .btn-danger { background: var(--error); color: white; }
        .btn-warning { background: var(--warning); color: #000; }
        .btn-info { background: var(--info); color: white; }
        .btn-sm { padding: 6px 14px; font-size: 12px; }
        .btn-group { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
        .progress-container {
            background: var(--bg-secondary);
            border-radius: 10px;
            overflow: hidden;
            height: 28px;
            margin: 12px 0;
            position: relative;
        }
        .progress-bar {
            height: 100%;
            background: var(--gradient-1);
            border-radius: 10px;
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 700;
            color: white;
            min-width: 40px;
        }
        .log-box {
            background: #0a0a0a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 16px;
            max-height: 400px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
            line-height: 1.6;
            color: #aaa;
        }
        .log-box .log-error { color: #ff4444; }
        .log-box .log-warning { color: #ffaa00; }
        .log-box .log-info { color: #44aaff; }
        .log-box .log-success { color: #44ff44; }
        .job-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        .job-table th {
            background: var(--bg-secondary);
            color: var(--accent-pink);
            padding: 12px;
            text-align: left;
            font-weight: 700;
        }
        .job-table td {
            padding: 10px 12px;
            border-bottom: 1px solid rgba(233,69,96,0.1);
        }
        .job-table tr:hover { background: rgba(233,69,96,0.05); }
        .status-badge {
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }
        .status-running { background: rgba(0,176,255,0.2); color: var(--info); }
        .status-completed { background: rgba(0,230,118,0.2); color: var(--success); }
        .status-failed { background: rgba(255,23,68,0.2); color: var(--error); }
        .status-paused { background: rgba(255,171,0,0.2); color: var(--warning); }
        .status-pending { background: rgba(255,255,255,0.1); color: #888; }
        .status-cancelled { background: rgba(255,23,68,0.1); color: #ff6666; }
        .tabs {
            display: flex;
            gap: 4px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .tab {
            padding: 10px 20px;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px 8px 0 0;
            cursor: pointer;
            font-weight: 600;
            font-size: 14px;
            color: var(--text-secondary);
            transition: 0.3s;
        }
        .tab.active {
            background: var(--gradient-1);
            color: white;
            border-color: var(--accent-pink);
        }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .chapters-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(60px, 1fr));
            gap: 4px;
            max-height: 300px;
            overflow-y: auto;
        }
        .ch-cell {
            padding: 6px;
            text-align: center;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
        .ch-success { background: rgba(0,230,118,0.3); color: var(--success); }
        .ch-failed { background: rgba(255,23,68,0.3); color: var(--error); }
        .ch-pending { background: rgba(255,255,255,0.05); color: #666; }
        .ch-fetching { background: rgba(0,176,255,0.3); color: var(--info); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .pulse { animation: pulse 1.5s infinite; }
        .hidden { display: none; }
        @media (max-width: 768px) {
            .container { padding: 10px; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            .form-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="top-bar">
        <h1>🔥 Novel Scraper Engine</h1>
        <div class="controls">
            <span id="clock" style="font-size:13px;opacity:0.8;"></span>
            <button class="theme-toggle" onclick="toggleTheme()">🌓 Theme</button>
        </div>
    </div>

    <div class="container">
        <!-- System Stats -->
        <div class="stats-grid" id="systemStats">
            <div class="stat-card"><div class="label">CPU Usage</div><div class="value" id="cpuUsage">--%</div></div>
            <div class="stat-card"><div class="label">RAM Usage</div><div class="value" id="ramUsage">--%</div></div>
            <div class="stat-card"><div class="label">Active Jobs</div><div class="value" id="activeJobs">0</div></div>
            <div class="stat-card"><div class="label">Total Jobs</div><div class="value" id="totalJobs">0</div></div>
            <div class="stat-card"><div class="label">Disk Free</div><div class="value" id="diskFree">--</div></div>
        </div>

        <!-- Tabs -->
        <div class="tabs">
            <div class="tab active" onclick="switchTab('newJob')">🚀 New Job</div>
            <div class="tab" onclick="switchTab('jobs')">📋 Jobs</div>
            <div class="tab" onclick="switchTab('monitor')">📊 Monitor</div>
            <div class="tab" onclick="switchTab('logs')">📝 Logs</div>
            <div class="tab" onclick="switchTab('downloads')">📥 Downloads</div>
        </div>

        <!-- New Job Tab -->
        <div class="tab-content active" id="tab-newJob">
            <div class="card">
                <h2>🚀 Create New Scraping Job</h2>
                <form id="newJobForm" onsubmit="createJob(event)">
                    <div class="form-grid">
                        <div class="form-group">
                            <label>📖 Novel Name</label>
                            <input type="text" name="novel_name" placeholder="My Novel" required>
                        </div>
                        <div class="form-group">
                            <label>🔧 Scrape Mode</label>
                            <select name="scrape_mode" onchange="toggleMode(this.value)">
                                <option value="pattern">Pattern Mode (URL + Range)</option>
                                <option value="smart">Smart Detect (Auto Next)</option>
                            </select>
                        </div>
                        <div class="form-group pattern-field">
                            <label>🔗 URL Pattern (use {} for chapter number)</label>
                            <input type="text" name="url_pattern" placeholder="https://example.com/novel/chapter-{}.html">
                        </div>
                        <div class="form-group pattern-field">
                            <label>📗 Start Chapter</label>
                            <input type="number" name="start_chapter" value="1" min="1">
                        </div>
                        <div class="form-group pattern-field">
                            <label>📕 End Chapter</label>
                            <input type="number" name="end_chapter" value="100" min="1">
                        </div>
                        <div class="form-group smart-field hidden">
                            <label>🔗 Start URL</label>
                            <input type="text" name="start_url" placeholder="https://example.com/novel/chapter-1.html">
                        </div>
                        <div class="form-group">
                            <label>🎯 Content CSS Selector (optional)</label>
                            <input type="text" name="content_selector" placeholder="#content or .chapter-text">
                        </div>
                        <div class="form-group">
                            <label>📌 Title CSS Selector (optional)</label>
                            <input type="text" name="title_selector" placeholder="h1.chapter-title">
                        </div>
                        <div class="form-group smart-field hidden">
                            <label>➡️ Next Button Selector (optional)</label>
                            <input type="text" name="next_button_selector" placeholder="a.next-chapter">
                        </div>
                        <div class="form-group">
                            <label>⚡ Max Workers</label>
                            <input type="number" name="max_workers" value="5" min="1" max="15">
                        </div>
                        <div class="form-group">
                            <label>⏱ Min Delay (sec)</label>
                            <input type="number" name="delay_min" value="0.5" min="0" step="0.1">
                        </div>
                        <div class="form-group">
                            <label>⏱ Max Delay (sec)</label>
                            <input type="number" name="delay_max" value="2.0" min="0.1" step="0.1">
                        </div>
                        <div class="form-group">
                            <label>📁 Output Format</label>
                            <select name="output_format">
                                <option value="single_txt">Single TXT File</option>
                                <option value="separate_files">Separate Chapter Files</option>
                                <option value="json">JSON Export</option>
                                <option value="markdown">Markdown</option>
                                <option value="zip">ZIP Archive</option>
                                <option value="epub">EPUB Book</option>
                                <option value="all">All Formats</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>🌐 Use Browser Mode</label>
                            <select name="use_browser">
                                <option value="false">No (Fast HTTP)</option>
                                <option value="true">Yes (Playwright)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>🧹 Remove Watermarks</label>
                            <select name="remove_watermark">
                                <option value="true">Yes</option>
                                <option value="false">No</option>
                            </select>
                        </div>
                    </div>

                    <!-- Login Section -->
                    <details style="margin-top: 20px;">
                        <summary style="cursor:pointer;color:var(--accent-pink);font-weight:700;">🔐 Login Settings (Advanced)</summary>
                        <div class="form-grid" style="margin-top: 12px;">
                            <div class="form-group">
                                <label>Login URL</label>
                                <input type="text" name="login_url" placeholder="https://example.com/login">
                            </div>
                            <div class="form-group">
                                <label>Username / Email</label>
                                <input type="text" name="login_user" placeholder="username">
                            </div>
                            <div class="form-group">
                                <label>Password</label>
                                <input type="password" name="login_pass" placeholder="password">
                            </div>
                            <div class="form-group" style="grid-column: 1/-1;">
                                <label>Cookies JSON (paste exported cookies)</label>
                                <textarea name="cookies_json" rows="3" placeholder='[{"name":"session","value":"abc123","domain":".example.com"}]'></textarea>
                            </div>
                        </div>
                    </details>

                    <div class="btn-group">
                        <button type="submit" class="btn btn-primary">🚀 Start Scraping</button>
                        <button type="reset" class="btn btn-warning">🔄 Reset</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Jobs Tab -->
        <div class="tab-content" id="tab-jobs">
            <div class="card">
                <h2>📋 Job History</h2>
                <div style="overflow-x: auto;">
                    <table class="job-table" id="jobsTable">
                        <thead>
                            <tr>
                                <th>Job ID</th>
                                <th>Novel</th>
                                <th>Status</th>
                                <th>Progress</th>
                                <th>Created</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody id="jobsBody"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Monitor Tab -->
        <div class="tab-content" id="tab-monitor">
            <div class="card" id="monitorCard">
                <h2>📊 Job Monitor</h2>
                <select id="monitorJobSelect" onchange="selectMonitorJob(this.value)" style="background:var(--bg-input);border:1px solid var(--border-color);color:var(--text-white);padding:8px 14px;border-radius:8px;margin-bottom:16px;min-width:300px;">
                    <option value="">Select a job...</option>
                </select>
                <div id="monitorContent" class="hidden">
                    <div class="stats-grid">
                        <div class="stat-card"><div class="label">Completed</div><div class="value" id="mCompleted">0</div></div>
                        <div class="stat-card"><div class="label">Failed</div><div class="value" id="mFailed">0</div></div>
                        <div class="stat-card"><div class="label">Pending</div><div class="value" id="mPending">0</div></div>
                        <div class="stat-card"><div class="label">Speed (ch/min)</div><div class="value" id="mSpeed">0</div></div>
                        <div class="stat-card"><div class="label">Avg Response</div><div class="value" id="mAvgResp">0s</div></div>
                        <div class="stat-card"><div class="label">ETA</div><div class="value" id="mEta">--</div></div>
                        <div class="stat-card"><div class="label">Active Threads</div><div class="value" id="mThreads">0</div></div>
                        <div class="stat-card"><div class="label">Current Delay</div><div class="value" id="mDelay">0s</div></div>
                    </div>
                    <div class="progress-container">
                        <div class="progress-bar" id="mProgressBar" style="width:0%">0%</div>
                    </div>
                    <h3 style="margin: 16px 0 8px; color: var(--accent-pink);">📦 Chapter Map</h3>
                    <div class="chapters-grid" id="chapterMap"></div>
                    <h3 style="margin: 16px 0 8px; color: var(--accent-pink);">⚠️ Errors</h3>
                    <div class="log-box" id="errorLog" style="max-height:200px;"></div>
                </div>
            </div>
        </div>

        <!-- Logs Tab -->
        <div class="tab-content" id="tab-logs">
            <div class="card">
                <h2>📝 System Logs</h2>
                <div class="btn-group" style="margin-bottom: 12px;">
                    <button class="btn btn-sm btn-info" onclick="refreshLogs()">🔄 Refresh</button>
                    <button class="btn btn-sm btn-danger" onclick="clearLogs()">🗑 Clear</button>
                </div>
                <div class="log-box" id="systemLogs"></div>
            </div>
        </div>

        <!-- Downloads Tab -->
        <div class="tab-content" id="tab-downloads">
            <div class="card">
                <h2>📥 Download Manager</h2>
                <select id="dlJobSelect" onchange="loadDownloads(this.value)" style="background:var(--bg-input);border:1px solid var(--border-color);color:var(--text-white);padding:8px 14px;border-radius:8px;margin-bottom:16px;min-width:300px;">
                    <option value="">Select a job...</option>
                </select>
                <div id="downloadsList"></div>
            </div>
        </div>
    </div>

    <script>
        let currentTheme = 'dark';
        let monitorInterval = null;
        let statsInterval = null;
        let currentMonitorJob = '';

        function toggleTheme() {
            currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', currentTheme);
        }

        function switchTab(name) {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            document.getElementById('tab-' + name).classList.add('active');
            if (name === 'jobs') refreshJobs();
            if (name === 'logs') refreshLogs();
            if (name === 'monitor') refreshMonitorSelect();
            if (name === 'downloads') refreshDownloadSelect();
        }

        function toggleMode(mode) {
            document.querySelectorAll('.pattern-field').forEach(e => e.classList.toggle('hidden', mode === 'smart'));
            document.querySelectorAll('.smart-field').forEach(e => e.classList.toggle('hidden', mode === 'pattern'));
        }

        async function createJob(e) {
            e.preventDefault();
            const form = new FormData(e.target);
            const data = Object.fromEntries(form.entries());
            data.start_chapter = parseInt(data.start_chapter) || 1;
            data.end_chapter = parseInt(data.end_chapter) || 100;
            data.max_workers = parseInt(data.max_workers) || 5;
            data.delay_min = parseFloat(data.delay_min) || 0.5;
            data.delay_max = parseFloat(data.delay_max) || 2.0;
            data.use_browser = data.use_browser === 'true';
            data.remove_watermark = data.remove_watermark === 'true';
            try {
                const resp = await fetch('/api/jobs', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                });
                const result = await resp.json();
                if (result.success) {
                    alert('✅ Job created and started: ' + result.job_id);
                    switchTab('monitor');
                    currentMonitorJob = result.job_id;
                    startMonitor(result.job_id);
                } else {
                    alert('❌ Error: ' + result.error);
                }
            } catch(err) {
                alert('❌ Request failed: ' + err.message);
            }
        }

        async function refreshJobs() {
            try {
                const resp = await fetch('/api/jobs');
                const data = await resp.json();
                const tbody = document.getElementById('jobsBody');
                tbody.innerHTML = '';
                data.jobs.forEach(j => {
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td style="font-family:monospace;font-size:11px;">${j.job_id}</td>
                        <td><strong>${j.novel_name || '-'}</strong></td>
                        <td><span class="status-badge status-${j.status}">${j.status}</span></td>
                        <td>${j.progress}</td>
                        <td style="font-size:11px;">${j.created_at || '-'}</td>
                        <td>
                            <button class="btn btn-sm btn-info" onclick="viewJob('${j.job_id}')">👁</button>
                            ${j.status === 'running' ? `<button class="btn btn-sm btn-warning" onclick="pauseJob('${j.job_id}')">⏸</button>` : ''}
                            ${j.status === 'paused' ? `<button class="btn btn-sm btn-success" onclick="resumeJob('${j.job_id}')">▶</button>` : ''}
                            ${['running','paused'].includes(j.status) ? `<button class="btn btn-sm btn-danger" onclick="cancelJob('${j.job_id}')">⏹</button>` : ''}
                            ${['completed','failed','cancelled'].includes(j.status) ? `<button class="btn btn-sm btn-danger" onclick="deleteJob('${j.job_id}')">🗑</button>` : ''}
                        </td>
                    `;
                    tbody.appendChild(tr);
                });
            } catch(err) { console.error(err); }
        }

        function viewJob(jobId) {
            currentMonitorJob = jobId;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab')[2].classList.add('active');
            document.getElementById('tab-monitor').classList.add('active');
            startMonitor(jobId);
        }

        async function pauseJob(id) {
            await fetch(`/api/jobs/${id}/pause`, {method:'POST'});
            refreshJobs();
        }
        async function resumeJob(id) {
            await fetch(`/api/jobs/${id}/resume`, {method:'POST'});
            refreshJobs();
        }
        async function cancelJob(id) {
            if (!confirm('Cancel this job?')) return;
            await fetch(`/api/jobs/${id}/cancel`, {method:'POST'});
            refreshJobs();
        }
        async function deleteJob(id) {
            if (!confirm('Delete this job and all its files?')) return;
            await fetch(`/api/jobs/${id}`, {method:'DELETE'});
            refreshJobs();
        }

        function refreshMonitorSelect() {
            fetch('/api/jobs').then(r=>r.json()).then(data => {
                const sel = document.getElementById('monitorJobSelect');
                sel.innerHTML = '<option value="">Select a job...</option>';
                data.jobs.forEach(j => {
                    sel.innerHTML += `<option value="${j.job_id}" ${j.job_id===currentMonitorJob?'selected':''}>${j.novel_name} (${j.status}) - ${j.job_id}</option>`;
                });
                if (currentMonitorJob) startMonitor(currentMonitorJob);
            });
        }

        function selectMonitorJob(jobId) {
            currentMonitorJob = jobId;
            if (jobId) startMonitor(jobId);
        }

        function startMonitor(jobId) {
            document.getElementById('monitorContent').classList.remove('hidden');
            document.getElementById('monitorJobSelect').value = jobId;
            if (monitorInterval) clearInterval(monitorInterval);
            updateMonitor(jobId);
            monitorInterval = setInterval(() => updateMonitor(jobId), 2000);
        }

        async function updateMonitor(jobId) {
            try {
                const resp = await fetch(`/api/jobs/${jobId}`);
                const data = await resp.json();
                if (!data.job) return;
                const j = data.job;
                const s = j.chapters_summary || {};

                document.getElementById('mCompleted').textContent = j.completed_count || 0;
                document.getElementById('mFailed').textContent = j.failed_count || 0;
                document.getElementById('mPending').textContent = s.pending || 0;
                document.getElementById('mSpeed').textContent = (j.current_speed || 0).toFixed(1);
                document.getElementById('mAvgResp').textContent = (j.avg_response_time || 0).toFixed(2) + 's';
                document.getElementById('mEta').textContent = j.estimated_eta || '--';
                document.getElementById('mThreads').textContent = j.active_threads || 0;
                document.getElementById('mDelay').textContent = (j.current_delay || 0).toFixed(2) + 's';

                const total = j.total_chapters || 1;
                const pct = Math.round(((j.completed_count || 0) / total) * 100);
                const bar = document.getElementById('mProgressBar');
                bar.style.width = pct + '%';
                bar.textContent = pct + '% (' + (j.completed_count||0) + '/' + total + ')';

                // Error log
                const errDiv = document.getElementById('errorLog');
                if (j.error_log && j.error_log.length) {
                    errDiv.innerHTML = j.error_log.map(e => `<div class="log-error">${escapeHtml(e)}</div>`).join('');
                } else {
                    errDiv.innerHTML = '<div style="color:#666;">No errors</div>';
                }

                // Chapter map
                const chResp = await fetch(`/api/jobs/${jobId}/chapters`);
                const chData = await chResp.json();
                const mapDiv = document.getElementById('chapterMap');
                if (chData.chapters && chData.chapters.length) {
                    mapDiv.innerHTML = chData.chapters.map(ch => {
                        let cls = 'ch-pending';
                        if (ch.status === 'success') cls = 'ch-success';
                        else if (ch.status === 'failed') cls = 'ch-failed';
                        else if (ch.status === 'fetching') cls = 'ch-fetching';
                        return `<div class="ch-cell ${cls}" title="Ch ${ch.chapter_number}: ${ch.status} (${ch.mode_used || '-'})">${ch.chapter_number}</div>`;
                    }).join('');
                }

                if (['completed','failed','cancelled'].includes(j.status) && monitorInterval) {
                    clearInterval(monitorInterval);
                }
            } catch(err) { console.error(err); }
        }

        async function refreshLogs() {
            try {
                const resp = await fetch('/api/logs');
                const data = await resp.json();
                const div = document.getElementById('systemLogs');
                div.innerHTML = data.logs.map(l => {
                    let cls = '';
                    if (l.includes('[ERROR]')) cls = 'log-error';
                    else if (l.includes('[WARNING]')) cls = 'log-warning';
                    else if (l.includes('[INFO]')) cls = 'log-info';
                    return `<div class="${cls}">${escapeHtml(l)}</div>`;
                }).join('');
                div.scrollTop = div.scrollHeight;
            } catch(err) { console.error(err); }
        }

        async function clearLogs() {
            await fetch('/api/logs', {method: 'DELETE'});
            refreshLogs();
        }

        function refreshDownloadSelect() {
            fetch('/api/jobs').then(r=>r.json()).then(data => {
                const sel = document.getElementById('dlJobSelect');
                sel.innerHTML = '<option value="">Select a job...</option>';
                data.jobs.filter(j => j.output_files > 0).forEach(j => {
                    sel.innerHTML += `<option value="${j.job_id}">${j.novel_name} - ${j.job_id}</option>`;
                });
            });
        }

        async function loadDownloads(jobId) {
            if (!jobId) return;
            try {
                const resp = await fetch(`/api/jobs/${jobId}/files`);
                const data = await resp.json();
                const div = document.getElementById('downloadsList');
                if (data.files && data.files.length) {
                    div.innerHTML = data.files.map(f => `
                        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px;border-bottom:1px solid rgba(233,69,96,0.1);">
                            <div>
                                <strong>${escapeHtml(f.name)}</strong>
                                <span style="color:var(--text-secondary);font-size:12px;margin-left:8px;">${f.size_human}</span>
                            </div>
                            <a href="/api/download?path=${encodeURIComponent(f.path)}" class="btn btn-sm btn-primary">📥 Download</a>
                        </div>
                    `).join('');
                } else {
                    div.innerHTML = '<p style="color:#666;">No files available</p>';
                }
            } catch(err) { console.error(err); }
        }

        async function updateSystemStats() {
            try {
                const resp = await fetch('/api/system');
                const data = await resp.json();
                document.getElementById('cpuUsage').textContent = data.cpu_percent.toFixed(1) + '%';
                document.getElementById('ramUsage').textContent = data.ram_percent.toFixed(1) + '%';
                document.getElementById('diskFree').textContent = data.disk_free_gb + 'GB';
                document.getElementById('activeJobs').textContent = data.active_jobs || 0;
                document.getElementById('totalJobs').textContent = data.total_jobs || 0;
            } catch(err) {}
        }

        function updateClock() {
            document.getElementById('clock').textContent = new Date().toLocaleTimeString();
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.appendChild(document.createTextNode(text));
            return div.innerHTML;
        }

        // Initialize
        updateClock();
        setInterval(updateClock, 1000);
        updateSystemStats();
        statsInterval = setInterval(updateSystemStats, 5000);
        refreshJobs();
    </script>
</body>
</html>
'''

# ============================================================
# FLASK APP
# ============================================================

if HAS_FLASK:
    app = Flask(__name__)
    app.secret_key = Config.SECRET_KEY

    @app.route('/')
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route('/api/jobs', methods=['GET'])
    def api_list_jobs():
        return jsonify({"jobs": job_manager.get_all_jobs()})

    @app.route('/api/jobs', methods=['POST'])
    def api_create_job():
        try:
            data = request.get_json(force=True) or {}

            config = JobConfig(
                url_pattern=data.get('url_pattern', ''),
                start_chapter=int(data.get('start_chapter', 1)),
                end_chapter=int(data.get('end_chapter', 100)),
                scrape_mode=data.get('scrape_mode', 'pattern'),
                content_selector=data.get('content_selector', ''),
                title_selector=data.get('title_selector', ''),
                next_button_selector=data.get('next_button_selector', ''),
                start_url=data.get('start_url', ''),
                max_workers=int(data.get('max_workers', 5)),
                delay_min=float(data.get('delay_min', 0.5)),
                delay_max=float(data.get('delay_max', 2.0)),
                output_format=data.get('output_format', 'single_txt'),
                novel_name=data.get('novel_name', 'Novel'),
                login_url=data.get('login_url', ''),
                login_user=data.get('login_user', ''),
                login_pass=data.get('login_pass', ''),
                cookies_json=data.get('cookies_json', ''),
                use_browser=bool(data.get('use_browser', False)),
                auto_detect_encoding=True,
                remove_watermark=bool(data.get('remove_watermark', True)),
            )

            # Validate
            if config.scrape_mode == 'pattern' and not config.url_pattern:
                return jsonify({"success": False, "error": "URL pattern is required for pattern mode"}), 400
            if config.scrape_mode == 'smart' and not config.start_url:
                return jsonify({"success": False, "error": "Start URL is required for smart mode"}), 400

            job_id = job_manager.create_job(config)
            job_manager.start_job(job_id)

            return jsonify({"success": True, "job_id": job_id})

        except Exception as e:
            logger.error(f"API create job error: {e}\n{traceback.format_exc()}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route('/api/jobs/<job_id>', methods=['GET'])
    def api_get_job(job_id):
        status = job_manager.get_job_status(job_id)
        if not status:
            return jsonify({"error": "Job not found"}), 404
        return jsonify({"job": status})

    @app.route('/api/jobs/<job_id>', methods=['DELETE'])
    def api_delete_job(job_id):
        job_manager.delete_job(job_id)
        return jsonify({"success": True})

    @app.route('/api/jobs/<job_id>/pause', methods=['POST'])
    def api_pause_job(job_id):
        try:
            job_manager.pause_job(job_id)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route('/api/jobs/<job_id>/resume', methods=['POST'])
    def api_resume_job(job_id):
        try:
            job_manager.resume_job(job_id)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
    def api_cancel_job(job_id):
        try:
            job_manager.cancel_job(job_id)
            return jsonify({"success": True})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    @app.route('/api/jobs/<job_id>/chapters', methods=['GET'])
    def api_get_chapters(job_id):
        chapters = job_manager.get_job_chapters(job_id)
        return jsonify({"chapters": chapters})

    @app.route('/api/jobs/<job_id>/files', methods=['GET'])
    def api_get_files(job_id):
        files = job_manager.get_output_files(job_id)
        return jsonify({"files": files})

    @app.route('/api/download')
    def api_download():
        file_path = request.args.get('path', '')
        if not file_path:
            return "No path specified", 400
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return "File not found", 404
        # Security: ensure file is within our output directory
        try:
            p.resolve().relative_to(DATA_DIR.resolve())
        except ValueError:
            return "Access denied", 403
        return send_file(str(p), as_attachment=True, download_name=p.name)

    @app.route('/api/logs', methods=['GET'])
    def api_get_logs():
        n = int(request.args.get('n', 200))
        logs = memory_log_handler.get_logs(n)
        return jsonify({"logs": logs})

    @app.route('/api/logs', methods=['DELETE'])
    def api_clear_logs():
        memory_log_handler.clear()
        return jsonify({"success": True})

    @app.route('/api/system', methods=['GET'])
    def api_system():
        stats = PerformanceMonitor.get_stats()
        active = sum(1 for j in job_manager.jobs.values() if j.status == JobStatus.RUNNING)
        stats['active_jobs'] = active
        stats['total_jobs'] = len(job_manager.jobs)
        return jsonify(stats)

    @app.route('/api/health', methods=['GET'])
    def api_health():
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "uptime": time.time(),
            "version": "2.0.0",
            "libraries": {
                "requests": HAS_REQUESTS,
                "beautifulsoup4": HAS_BS4,
                "playwright": HAS_PLAYWRIGHT,
                "cloudscraper": HAS_CLOUDSCRAPER,
                "chardet": HAS_CHARDET,
                "psutil": HAS_PSUTIL,
                "ebooklib": HAS_EPUB,
            }
        })

else:
    app = None


# ============================================================
# MAIN
# ============================================================

def main():
    """Entry point."""
    print("""
    ╔══════════════════════════════════════════════════╗
    ║    🔥 Novel Scraper Engine v2.0.0               ║
    ║    Production-Grade Scraping Platform            ║
    ╠══════════════════════════════════════════════════╣
    ║  Libraries:                                      ║
    ║    requests:      {:<30s}  ║
    ║    beautifulsoup4: {:<30s}  ║
    ║    playwright:     {:<30s}  ║
    ║    cloudscraper:   {:<30s}  ║
    ║    chardet:        {:<30s}  ║
    ║    psutil:         {:<30s}  ║
    ║    ebooklib:       {:<30s}  ║
    ║    flask:          {:<30s}  ║
    ╠══════════════════════════════════════════════════╣
    ║  Server: {}:{:<36s}  ║
    ║  CPUs: {:<42s}  ║
    ║  Data Dir: {:<38s}  ║
    ╚══════════════════════════════════════════════════╝
    """.format(
        '✅' if HAS_REQUESTS else '❌',
        '✅' if HAS_BS4 else '❌',
        '✅' if HAS_PLAYWRIGHT else '❌',
        '✅' if HAS_CLOUDSCRAPER else '❌',
        '✅' if HAS_CHARDET else '❌',
        '✅' if HAS_PSUTIL else '❌',
        '✅' if HAS_EPUB else '❌',
        '✅' if HAS_FLASK else '❌',
        Config.HOST, str(Config.PORT),
        str(Config.CPU_COUNT),
        str(DATA_DIR),
    ))

    if not HAS_REQUESTS:
        print("❌ CRITICAL: 'requests' library not installed. Run: pip install requests")
        sys.exit(1)

    if not HAS_BS4:
        print("⚠️  WARNING: 'beautifulsoup4' not installed. Content extraction will be limited.")
        print("   Run: pip install beautifulsoup4")

    if not HAS_FLASK:
        print("❌ CRITICAL: 'flask' library not installed. Run: pip install flask")
        sys.exit(1)

    # Graceful shutdown
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down gracefully...")
        for jid in list(job_manager.scraper_engines.keys()):
            try:
                job_manager.cancel_job(jid)
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info(f"Starting Novel Scraper Engine on {Config.HOST}:{Config.PORT}")

    app.run(
        host=Config.HOST,
        port=Config.PORT,
        debug=Config.DEBUG,
        threaded=True,
        use_reloader=False,
    )


if __name__ == '__main__':
    main()