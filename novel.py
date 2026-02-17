#!/usr/bin/env python3
"""
Novel Scraper Web App - Production Ready
Requirements (requirements.txt):
flask>=2.3.0
requests>=2.31.0
beautifulsoup4>=4.12.0
cloudscraper>=1.2.71
lxml>=4.9.0
"""

import os
import re
import sys
import json
import time
import uuid
import random
import signal
import hashlib
import logging
import threading
from io import BytesIO
from datetime import datetime
from html import unescape
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import (
    Flask, request, jsonify, send_file, Response,
    render_template_string
)
from bs4 import BeautifulSoup, Comment
import cloudscraper
import requests

# ============================================================
# Configuration
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('NovelScraper')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', uuid.uuid4().hex)

MAX_THREADS = 10
DEFAULT_THREADS = 5
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2
MAX_CHAPTERS_LIMIT = 5000
CHUNK_SIZE = 50

# ============================================================
# Global Job Store
# ============================================================

jobs = {}
jobs_lock = threading.Lock()

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 OPR/104.0.0.0',
]


# ============================================================
# Scraper Engine
# ============================================================

class NovelScraper:
    """Core scraping engine with anti-detection and smart content extraction."""

    def __init__(self, job_id):
        self.job_id = job_id
        self.session = None
        self.cloud_session = None
        self._init_sessions()

    def _init_sessions(self):
        """Initialize HTTP sessions with anti-detection measures."""
        self.session = requests.Session()
        self.session.headers.update(self._get_headers())
        try:
            self.cloud_session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
                delay=5
            )
            self.cloud_session.headers.update(self._get_headers())
        except Exception:
            self.cloud_session = self.session

    def _get_headers(self):
        return {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

    def _rotate_agent(self):
        ua = random.choice(USER_AGENTS)
        self.session.headers['User-Agent'] = ua
        if self.cloud_session and self.cloud_session != self.session:
            self.cloud_session.headers['User-Agent'] = ua

    def fetch_page(self, url, retry=0):
        """Fetch page with retry logic and Cloudflare bypass."""
        if retry >= MAX_RETRIES:
            return None

        self._rotate_agent()
        delay = random.uniform(0.5, 2.0) + (retry * RETRY_DELAY_BASE)
        time.sleep(delay)

        # Try cloudscraper first, then regular requests
        sessions_to_try = [self.cloud_session, self.session]
        if self.cloud_session == self.session:
            sessions_to_try = [self.session]

        last_error = None
        for sess in sessions_to_try:
            try:
                resp = sess.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
                if resp.status_code == 200:
                    resp.encoding = resp.apparent_encoding or 'utf-8'
                    return resp.text
                elif resp.status_code == 403:
                    last_error = f"403 Forbidden"
                    continue
                elif resp.status_code == 429:
                    time.sleep(5 + retry * 3)
                    last_error = f"429 Rate Limited"
                    continue
                elif resp.status_code == 404:
                    return None
                else:
                    last_error = f"HTTP {resp.status_code}"
                    continue
            except requests.exceptions.Timeout:
                last_error = "Timeout"
                continue
            except requests.exceptions.ConnectionError:
                last_error = "Connection Error"
                continue
            except Exception as e:
                last_error = str(e)
                continue

        logger.warning(f"Retry {retry + 1}/{MAX_RETRIES} for {url}: {last_error}")
        return self.fetch_page(url, retry + 1)

    @staticmethod
    def clean_content(html_content):
        """Advanced content cleaning: remove ads, scripts, navigation, etc."""
        if not html_content:
            return ""

        soup = BeautifulSoup(html_content, 'lxml')

        # Remove unwanted tags
        unwanted_tags = [
            'script', 'style', 'noscript', 'iframe', 'ins', 'aside',
            'footer', 'header', 'nav', 'form', 'button', 'input',
            'select', 'textarea', 'svg', 'canvas', 'video', 'audio',
            'source', 'picture', 'figure', 'figcaption', 'meta', 'link'
        ]
        for tag in soup.find_all(unwanted_tags):
            tag.decompose()

        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()

        # Remove ad-related elements
        ad_patterns = re.compile(
            r'(ad[s\-_]?|banner|sponsor|promo|popup|modal|overlay|social|share|'
            r'comment[s]?|sidebar|widget|related|recommend|disqus|copyright|'
            r'footer|header|menu|breadcrumb|pagination|rating|bookmark|'
            r'notice|alert|cookie|consent|newsletter|subscribe)',
            re.IGNORECASE
        )
        for el in soup.find_all(attrs={'class': ad_patterns}):
            el.decompose()
        for el in soup.find_all(attrs={'id': ad_patterns}):
            el.decompose()

        return soup

    @staticmethod
    def extract_chapter_content(html_content, url=""):
        """Intelligently extract chapter text content from a page."""
        if not html_content:
            return "", ""

        soup = NovelScraper.clean_content(html_content)

        # Try to find chapter title
        title = ""
        title_candidates = []

        # Check common title patterns
        for selector in ['h1', 'h2', '.chapter-title', '.entry-title',
                         '#chapter-title', '.title', '[class*="chapter"]>h1',
                         '[class*="chapter"]>h2', '.cap-title', '.text-title']:
            try:
                found = soup.select(selector)
                for f in found:
                    text = f.get_text(strip=True)
                    if text and len(text) < 200:
                        title_candidates.append(text)
            except Exception:
                pass

        if title_candidates:
            # Pick the most likely chapter title
            for tc in title_candidates:
                if re.search(r'(chapter|ch\.?|chap|episode|ep\.?|part|vol)', tc, re.IGNORECASE):
                    title = tc
                    break
            if not title:
                title = title_candidates[0]

        # Content extraction strategies (ordered by specificity)
        content_selectors = [
            '#chapter-content', '.chapter-content', '#chaptercontent',
            '.chaptercontent', '#chapter_content', '.chapter_content',
            '.entry-content', '#content', '.content', '.text-content',
            '.reading-content', '.read-content', '#chr-content',
            '.chr-content', '#article', '.article', 'article',
            '.novel-content', '.story-content', '.post-content',
            '#story-content', '.c-content', '.fr-view',
            '.cont-text', '#cont-text', '.text-left',
            '#text-content', '.box-text', '#box-text',
            '.reader-content', '#reader-content',
            '#bookContent', '.bookContent',
            '.txtnav', '#TextContent', '.TextContent',
        ]

        content_element = None
        for selector in content_selectors:
            try:
                found = soup.select_one(selector)
                if found:
                    text = found.get_text(strip=True)
                    if len(text) > 100:
                        content_element = found
                        break
            except Exception:
                pass

        # Fallback: find the largest text block
        if not content_element:
            all_divs = soup.find_all(['div', 'article', 'section', 'main'])
            best = None
            best_len = 0
            for div in all_divs:
                text = div.get_text(strip=True)
                # Filter out very short or navigation-heavy blocks
                links = div.find_all('a')
                link_text_len = sum(len(a.get_text()) for a in links)
                actual_text_len = len(text) - link_text_len
                if actual_text_len > best_len and actual_text_len > 200:
                    best = div
                    best_len = actual_text_len
            content_element = best

        if not content_element:
            # Last resort: get body text
            body = soup.find('body')
            if body:
                raw = body.get_text(separator='\n', strip=True)
                return title, NovelScraper.normalize_text(raw)
            return title, ""

        # Extract text preserving paragraph structure
        paragraphs = content_element.find_all(['p', 'br', 'div'])
        if paragraphs:
            lines = []
            seen = set()
            for p in paragraphs:
                text = p.get_text(strip=True)
                if text and text not in seen and len(text) > 1:
                    seen.add(text)
                    lines.append(text)
            if lines:
                result = '\n\n'.join(lines)
            else:
                result = content_element.get_text(separator='\n', strip=True)
        else:
            result = content_element.get_text(separator='\n', strip=True)

        return title, NovelScraper.normalize_text(result)

    @staticmethod
    def normalize_text(text):
        """Normalize extracted text."""
        if not text:
            return ""

        # Decode HTML entities
        text = unescape(text)

        # Remove excessive whitespace but keep paragraph breaks
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            line = re.sub(r'[ \t]+', ' ', line)
            if line:
                cleaned.append(line)

        text = '\n\n'.join(cleaned)

        # Remove common junk patterns
        junk_patterns = [
            r'(Please enable JavaScript.*?\.)',
            r'(Advertisements?)',
            r'(Loading\.\.\.)',
            r'(Click here to report.*)',
            r'(If you find any errors.*)',
            r'(Translator[:\s]*\S+)',
            r'(Editor[:\s]*\S+)',
            r'(Proofreader[:\s]*\S+)',
            r'(Support us at.*)',
            r'(Visit .* for faster updates)',
            r'(Read .* at .*)',
            r'(Join our discord.*)',
        ]
        for pattern in junk_patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)

        # Clean up extra blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @staticmethod
    def find_next_page(html_content, current_url):
        """Smart detection of 'Next' page link."""
        if not html_content:
            return None

        soup = BeautifulSoup(html_content, 'lxml')

        # Strategy 1: rel="next"
        link = soup.find('link', rel='next')
        if link and link.get('href'):
            return urljoin(current_url, link['href'])

        a_rel = soup.find('a', rel='next')
        if a_rel and a_rel.get('href'):
            return urljoin(current_url, a_rel['href'])

        # Strategy 2: Button/link text patterns
        next_patterns = [
            r'^next$', r'^next\s*chapter$', r'^next\s*page$',
            r'^→$', r'^>>$', r'^>$', r'^»$',
            r'^\s*next\s*→\s*$', r'^\s*→\s*next\s*$',
            r'^tiếp$', r'^sau$', r'^siguiente$', r'^suivant$',
            r'^weiter$', r'^次へ$', r'^下一章$', r'^다음$',
        ]

        all_links = soup.find_all('a', href=True)
        for pattern in next_patterns:
            for a in all_links:
                link_text = a.get_text(strip=True)
                if re.match(pattern, link_text, re.IGNORECASE):
                    href = a['href']
                    if href and href != '#' and not href.startswith('javascript:'):
                        return urljoin(current_url, href)

        # Strategy 3: Class/ID containing "next"
        for a in all_links:
            classes = ' '.join(a.get('class', []))
            aid = a.get('id', '')
            if re.search(r'next', classes + ' ' + aid, re.IGNORECASE):
                href = a['href']
                if href and href != '#' and not href.startswith('javascript:'):
                    # Make sure it's not "previous" misidentified
                    text = a.get_text(strip=True).lower()
                    if 'prev' not in text and 'back' not in text:
                        return urljoin(current_url, href)

        # Strategy 4: aria-label
        for a in all_links:
            aria = a.get('aria-label', '')
            title_attr = a.get('title', '')
            combined = (aria + ' ' + title_attr).lower()
            if 'next' in combined and 'prev' not in combined:
                href = a['href']
                if href and href != '#' and not href.startswith('javascript:'):
                    return urljoin(current_url, href)

        # Strategy 5: Check for incremented URL pattern in links
        parsed = urlparse(current_url)
        current_path = parsed.path
        numbers_in_path = re.findall(r'\d+', current_path)
        if numbers_in_path:
            last_num = numbers_in_path[-1]
            next_num = str(int(last_num) + 1)
            expected_next_path = current_path[:current_path.rfind(last_num)] + \
                                 next_num + \
                                 current_path[current_path.rfind(last_num) + len(last_num):]
            for a in all_links:
                href = a.get('href', '')
                full_href = urljoin(current_url, href)
                if urlparse(full_href).path == expected_next_path:
                    return full_href

        return None


# ============================================================
# Job Manager
# ============================================================

class ScrapingJob:
    """Manages a single scraping job with progress tracking and pause/resume."""

    def __init__(self, job_id, config):
        self.job_id = job_id
        self.config = config
        self.status = 'queued'  # queued, running, paused, completed, failed, cancelled
        self.progress = 0
        self.total = 0
        self.chapters = {}  # {chapter_num: {'title': ..., 'content': ...}}
        self.errors = []
        self.log_messages = []
        self.start_time = None
        self.end_time = None
        self.pause_event = threading.Event()
        self.pause_event.set()  # Not paused initially
        self.cancel_flag = False
        self.lock = threading.Lock()
        self.output_file = None
        self.current_chapter = 0
        self.eta_seconds = 0

    def log(self, message, level='info'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        entry = {'time': timestamp, 'level': level, 'message': message}
        with self.lock:
            self.log_messages.append(entry)
            if len(self.log_messages) > 500:
                self.log_messages = self.log_messages[-500:]
        if level == 'error':
            logger.error(f"[Job {self.job_id[:8]}] {message}")
        else:
            logger.info(f"[Job {self.job_id[:8]}] {message}")

    def update_progress(self, current, total=None):
        with self.lock:
            self.current_chapter = current
            if total is not None:
                self.total = total
            self.progress = int((current / self.total * 100)) if self.total > 0 else 0

            # Calculate ETA
            if self.start_time and current > 0:
                elapsed = time.time() - self.start_time
                rate = current / elapsed
                remaining = self.total - current
                self.eta_seconds = int(remaining / rate) if rate > 0 else 0

    def get_status(self):
        with self.lock:
            return {
                'job_id': self.job_id,
                'status': self.status,
                'progress': self.progress,
                'current': self.current_chapter,
                'total': self.total,
                'errors': self.errors[-20:],
                'logs': self.log_messages[-50:],
                'eta_seconds': self.eta_seconds,
                'chapters_done': len(self.chapters),
                'start_time': self.start_time,
            }

    def run(self):
        """Execute the scraping job."""
        self.status = 'running'
        self.start_time = time.time()
        scraper = NovelScraper(self.job_id)
        mode = self.config.get('mode', 'pattern')

        try:
            if mode == 'pattern':
                self._run_pattern_mode(scraper)
            elif mode == 'smart':
                self._run_smart_mode(scraper)
            else:
                raise ValueError(f"Unknown mode: {mode}")

            if self.cancel_flag:
                self.status = 'cancelled'
                self.log("Job cancelled by user.", 'warning')
            else:
                self._compile_output()
                self.status = 'completed'
                self.log(f"Completed! {len(self.chapters)} chapters scraped.")

        except Exception as e:
            self.status = 'failed'
            self.errors.append(str(e))
            self.log(f"Job failed: {str(e)}", 'error')
        finally:
            self.end_time = time.time()

    def _run_pattern_mode(self, scraper):
        """Pattern-based URL scraping with multi-threading."""
        url_pattern = self.config['url_pattern']
        start_ch = self.config.get('start_chapter', 1)
        end_ch = self.config.get('end_chapter', 10)
        thread_count = min(self.config.get('threads', DEFAULT_THREADS), MAX_THREADS)

        # Validate
        if '{}' not in url_pattern:
            # Try to auto-detect number pattern
            numbers = re.findall(r'\d+', url_pattern)
            if numbers:
                last_num = numbers[-1]
                idx = url_pattern.rfind(last_num)
                url_pattern = url_pattern[:idx] + '{}' + url_pattern[idx + len(last_num):]
                self.log(f"Auto-detected pattern: {url_pattern}")
            else:
                raise ValueError("URL pattern must contain '{}' placeholder or a number to auto-detect.")

        total = end_ch - start_ch + 1
        self.total = total
        self.log(f"Pattern mode: chapters {start_ch}-{end_ch} ({total} total), {thread_count} threads")

        chapter_nums = list(range(start_ch, end_ch + 1))
        completed = 0

        def fetch_chapter(ch_num):
            nonlocal completed
            if self.cancel_flag:
                return

            # Check pause
            self.pause_event.wait()

            url = url_pattern.replace('{}', str(ch_num))
            self.log(f"Fetching chapter {ch_num}: {url}")

            html = scraper.fetch_page(url)
            if html is None:
                error_msg = f"Chapter {ch_num}: Failed to fetch"
                self.errors.append(error_msg)
                self.log(error_msg, 'error')
                return

            title, content = scraper.extract_chapter_content(html, url)
            if not content or len(content.strip()) < 50:
                error_msg = f"Chapter {ch_num}: Content too short or empty"
                self.errors.append(error_msg)
                self.log(error_msg, 'warning')
                if content:
                    with self.lock:
                        self.chapters[ch_num] = {
                            'title': title or f"Chapter {ch_num}",
                            'content': content
                        }
                return

            with self.lock:
                self.chapters[ch_num] = {
                    'title': title or f"Chapter {ch_num}",
                    'content': content
                }
                completed += 1
                self.update_progress(completed, total)

            self.log(f"Chapter {ch_num} done ({len(content)} chars)")

        # Process in chunks to manage memory
        for i in range(0, len(chapter_nums), CHUNK_SIZE):
            if self.cancel_flag:
                break
            chunk = chapter_nums[i:i + CHUNK_SIZE]

            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = {executor.submit(fetch_chapter, ch): ch for ch in chunk}
                for future in as_completed(futures):
                    if self.cancel_flag:
                        break
                    try:
                        future.result()
                    except Exception as e:
                        ch = futures[future]
                        self.errors.append(f"Chapter {ch}: {str(e)}")
                        self.log(f"Chapter {ch} error: {str(e)}", 'error')

        self.update_progress(total, total)

    def _run_smart_mode(self, scraper):
        """Smart mode: follow 'Next' links."""
        start_url = self.config['url_pattern']
        max_chapters = self.config.get('end_chapter', 100)
        self.total = max_chapters
        self.log(f"Smart mode: starting from {start_url}, max {max_chapters} chapters")

        current_url = start_url
        ch_num = 0
        visited = set()

        while ch_num < max_chapters and not self.cancel_flag:
            self.pause_event.wait()

            if current_url in visited:
                self.log("Loop detected, stopping.", 'warning')
                break

            visited.add(current_url)
            ch_num += 1
            self.log(f"Fetching chapter {ch_num}: {current_url}")

            html = scraper.fetch_page(current_url)
            if html is None:
                self.log(f"Chapter {ch_num}: Could not fetch page. Stopping.", 'warning')
                break

            title, content = scraper.extract_chapter_content(html, current_url)

            if content and len(content.strip()) >= 50:
                with self.lock:
                    self.chapters[ch_num] = {
                        'title': title or f"Chapter {ch_num}",
                        'content': content
                    }
                self.log(f"Chapter {ch_num} done ({len(content)} chars)")
            else:
                self.log(f"Chapter {ch_num}: Content too short, skipping.", 'warning')
                self.errors.append(f"Chapter {ch_num}: Content too short")

            self.update_progress(ch_num, max_chapters)

            # Find next page
            next_url = scraper.find_next_page(html, current_url)
            if next_url is None:
                self.log("No next page found. Scraping complete.")
                break

            # Validate it's a different page
            if next_url == current_url:
                self.log("Next URL same as current. Stopping.", 'warning')
                break

            current_url = next_url

        self.total = ch_num
        self.update_progress(ch_num, ch_num)

    def _compile_output(self):
        """Compile all chapters into a single text file."""
        if not self.chapters:
            self.log("No chapters to compile.", 'warning')
            return

        filename = self.config.get('filename', 'novel') or 'novel'
        filename = re.sub(r'[^\w\s\-]', '', filename).strip() or 'novel'

        lines = []
        lines.append(f"{'=' * 60}")
        lines.append(f"  {filename}")
        lines.append(f"  Scraped on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Total chapters: {len(self.chapters)}")
        lines.append(f"{'=' * 60}")
        lines.append("")

        for ch_num in sorted(self.chapters.keys()):
            ch = self.chapters[ch_num]
            title = ch.get('title', f'Chapter {ch_num}')
            content = ch.get('content', '')

            lines.append(f"{'─' * 50}")
            lines.append(f"--- {title} ---")
            lines.append(f"{'─' * 50}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("")

        self.output_file = '\n'.join(lines)
        self.log(f"Output compiled: {len(self.output_file)} bytes")


def run_job(job_id):
    """Background job runner."""
    with jobs_lock:
        job = jobs.get(job_id)
    if job:
        job.run()


# ============================================================
# HTML Template
# ============================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Novel Scraper Pro</title>
    <style>
        :root {
            --pink: #ff4da6;
            --purple: #8a2be2;
            --dark-purple: #5b1a9e;
            --light-pink: #ffb3d9;
            --bg-dark: #0d0015;
            --bg-card: rgba(255,255,255,0.06);
            --bg-card-hover: rgba(255,255,255,0.1);
            --text: #f0e6ff;
            --text-muted: #b8a4d6;
            --success: #00e676;
            --error: #ff5252;
            --warning: #ffd740;
            --border: rgba(255,77,166,0.2);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }

        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background:
                radial-gradient(ellipse at 20% 20%, rgba(138,43,226,0.15) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(255,77,166,0.1) 0%, transparent 50%),
                radial-gradient(ellipse at 50% 50%, rgba(91,26,158,0.08) 0%, transparent 70%);
            pointer-events: none;
            z-index: 0;
        }

        .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            position: relative;
            z-index: 1;
        }

        .header {
            text-align: center;
            padding: 40px 0 30px;
        }

        .header h1 {
            font-size: 2.8em;
            font-weight: 800;
            background: linear-gradient(135deg, var(--pink), var(--purple), var(--light-pink));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
            letter-spacing: -1px;
        }

        .header p {
            color: var(--text-muted);
            font-size: 1.05em;
        }

        .card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 28px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }

        .card:hover {
            background: var(--bg-card-hover);
            border-color: rgba(255,77,166,0.35);
        }

        .card h2 {
            font-size: 1.3em;
            margin-bottom: 20px;
            color: var(--pink);
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .form-group {
            margin-bottom: 18px;
        }

        .form-group label {
            display: block;
            margin-bottom: 6px;
            color: var(--text-muted);
            font-size: 0.9em;
            font-weight: 500;
        }

        .form-group input, .form-group select {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255,255,255,0.05);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: var(--text);
            font-size: 0.95em;
            transition: all 0.3s ease;
            outline: none;
        }

        .form-group input:focus, .form-group select:focus {
            border-color: var(--pink);
            box-shadow: 0 0 0 3px rgba(255,77,166,0.15);
            background: rgba(255,255,255,0.08);
        }

        .form-group input::placeholder {
            color: rgba(255,255,255,0.25);
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }

        .form-row-3 {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 15px;
        }

        .mode-selector {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 20px;
        }

        .mode-btn {
            padding: 16px;
            border: 2px solid var(--border);
            border-radius: 12px;
            background: rgba(255,255,255,0.03);
            color: var(--text-muted);
            cursor: pointer;
            text-align: center;
            transition: all 0.3s ease;
            font-size: 0.95em;
        }

        .mode-btn:hover {
            border-color: rgba(255,77,166,0.4);
            background: rgba(255,77,166,0.05);
        }

        .mode-btn.active {
            border-color: var(--pink);
            background: linear-gradient(135deg, rgba(255,77,166,0.15), rgba(138,43,226,0.15));
            color: var(--text);
            box-shadow: 0 0 20px rgba(255,77,166,0.1);
        }

        .mode-btn .mode-title {
            font-weight: 700;
            font-size: 1.05em;
            margin-bottom: 4px;
        }

        .mode-btn .mode-desc {
            font-size: 0.8em;
            opacity: 0.7;
        }

        .btn {
            padding: 14px 32px;
            border: none;
            border-radius: 12px;
            font-size: 1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
            position: relative;
            overflow: hidden;
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--pink), var(--purple));
            color: white;
            width: 100%;
            justify-content: center;
            font-size: 1.1em;
            padding: 16px;
        }

        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(255,77,166,0.3);
        }

        .btn-primary:active {
            transform: translateY(0);
        }

        .btn-primary::after {
            content: '';
            position: absolute;
            top: -50%; left: -50%;
            width: 200%; height: 200%;
            background: linear-gradient(transparent, rgba(255,255,255,0.1), transparent);
            transform: rotate(45deg);
            transition: 0.5s;
            opacity: 0;
        }

        .btn-primary:hover::after {
            opacity: 1;
            transform: rotate(45deg) translate(50%, 50%);
        }

        .btn-secondary {
            background: rgba(255,255,255,0.08);
            color: var(--text);
            border: 1px solid var(--border);
        }

        .btn-secondary:hover {
            background: rgba(255,255,255,0.12);
        }

        .btn-success {
            background: linear-gradient(135deg, #00c853, #00e676);
            color: #003300;
        }

        .btn-warning {
            background: rgba(255,215,64,0.2);
            color: var(--warning);
            border: 1px solid rgba(255,215,64,0.3);
        }

        .btn-danger {
            background: rgba(255,82,82,0.2);
            color: var(--error);
            border: 1px solid rgba(255,82,82,0.3);
        }

        .btn-sm {
            padding: 8px 16px;
            font-size: 0.85em;
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none !important;
        }

        .actions-row {
            display: flex;
            gap: 10px;
            margin-top: 15px;
            flex-wrap: wrap;
        }

        /* Progress Section */
        .progress-section {
            display: none;
        }

        .progress-section.active {
            display: block;
        }

        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: rgba(255,255,255,0.08);
            border-radius: 4px;
            overflow: hidden;
            margin: 15px 0;
        }

        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--pink), var(--purple));
            border-radius: 4px;
            transition: width 0.5s ease;
            width: 0%;
            position: relative;
        }

        .progress-bar::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            animation: shimmer 2s infinite;
        }

        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }

        .progress-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin: 15px 0;
        }

        .stat-item {
            background: rgba(255,255,255,0.04);
            border-radius: 10px;
            padding: 12px 16px;
            text-align: center;
        }

        .stat-value {
            font-size: 1.5em;
            font-weight: 700;
            background: linear-gradient(135deg, var(--pink), var(--purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }

        .stat-label {
            font-size: 0.75em;
            color: var(--text-muted);
            margin-top: 4px;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
        }

        .status-running {
            background: rgba(255,77,166,0.15);
            color: var(--pink);
        }

        .status-completed {
            background: rgba(0,230,118,0.15);
            color: var(--success);
        }

        .status-failed {
            background: rgba(255,82,82,0.15);
            color: var(--error);
        }

        .status-paused {
            background: rgba(255,215,64,0.15);
            color: var(--warning);
        }

        .status-cancelled {
            background: rgba(255,255,255,0.1);
            color: var(--text-muted);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: currentColor;
        }

        .status-running .status-dot {
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        /* Log Panel */
        .log-panel {
            background: rgba(0,0,0,0.3);
            border: 1px solid rgba(255,255,255,0.06);
            border-radius: 10px;
            padding: 16px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 0.8em;
            line-height: 1.6;
            margin-top: 15px;
        }

        .log-panel::-webkit-scrollbar {
            width: 6px;
        }

        .log-panel::-webkit-scrollbar-track {
            background: transparent;
        }

        .log-panel::-webkit-scrollbar-thumb {
            background: rgba(255,77,166,0.3);
            border-radius: 3px;
        }

        .log-entry {
            margin-bottom: 3px;
            word-break: break-all;
        }

        .log-time {
            color: rgba(255,255,255,0.3);
            margin-right: 8px;
        }

        .log-info { color: #81d4fa; }
        .log-warning { color: var(--warning); }
        .log-error { color: var(--error); }

        .error-list {
            margin-top: 12px;
        }

        .error-item {
            padding: 8px 12px;
            background: rgba(255,82,82,0.08);
            border-left: 3px solid var(--error);
            border-radius: 0 8px 8px 0;
            margin-bottom: 6px;
            font-size: 0.85em;
            color: rgba(255,150,150,0.9);
        }

        /* Toggle / Switch */
        .toggle-container {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 15px;
        }

        .toggle-switch {
            position: relative;
            width: 48px;
            height: 26px;
            cursor: pointer;
        }

        .toggle-switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .toggle-slider {
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255,255,255,0.1);
            border-radius: 13px;
            transition: 0.3s;
        }

        .toggle-slider::before {
            content: '';
            position: absolute;
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background: white;
            border-radius: 50%;
            transition: 0.3s;
        }

        .toggle-switch input:checked + .toggle-slider {
            background: linear-gradient(135deg, var(--pink), var(--purple));
        }

        .toggle-switch input:checked + .toggle-slider::before {
            transform: translateX(22px);
        }

        .hint {
            font-size: 0.8em;
            color: var(--text-muted);
            margin-top: 5px;
            font-style: italic;
        }

        /* Dark mode toggle */
        .theme-toggle {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 100;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 50%;
            width: 44px;
            height: 44px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.2em;
            transition: all 0.3s ease;
        }

        .theme-toggle:hover {
            transform: scale(1.1);
            border-color: var(--pink);
        }

        /* Light mode */
        body.light-mode {
            --bg-dark: #faf0ff;
            --bg-card: rgba(138,43,226,0.06);
            --bg-card-hover: rgba(138,43,226,0.1);
            --text: #2d1b4e;
            --text-muted: #6b5b7b;
            --border: rgba(138,43,226,0.15);
        }

        body.light-mode::before {
            background:
                radial-gradient(ellipse at 20% 20%, rgba(255,77,166,0.08) 0%, transparent 50%),
                radial-gradient(ellipse at 80% 80%, rgba(138,43,226,0.06) 0%, transparent 50%);
        }

        body.light-mode .log-panel {
            background: rgba(0,0,0,0.04);
        }

        body.light-mode .form-group input,
        body.light-mode .form-group select {
            background: rgba(255,255,255,0.6);
            color: var(--text);
        }

        @media (max-width: 640px) {
            .container { padding: 12px; }
            .header h1 { font-size: 1.9em; }
            .form-row, .form-row-3 { grid-template-columns: 1fr; }
            .mode-selector { grid-template-columns: 1fr; }
            .card { padding: 18px; }
            .progress-stats { grid-template-columns: 1fr 1fr; }
        }

        .fade-in {
            animation: fadeIn 0.5s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .spinner {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid transparent;
            border-top-color: currentColor;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .tab-btns {
            display: flex;
            gap: 0;
            margin-bottom: 15px;
            border: 1px solid var(--border);
            border-radius: 10px;
            overflow: hidden;
        }

        .tab-btn {
            flex: 1;
            padding: 10px 16px;
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-size: 0.85em;
            font-weight: 500;
            transition: all 0.3s ease;
        }

        .tab-btn.active {
            background: linear-gradient(135deg, rgba(255,77,166,0.15), rgba(138,43,226,0.15));
            color: var(--text);
        }

        .tab-btn:hover:not(.active) {
            background: rgba(255,255,255,0.05);
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
        }

        .download-section {
            text-align: center;
            padding: 30px;
        }

        .download-section .btn-success {
            font-size: 1.2em;
            padding: 16px 40px;
        }
    </style>
</head>
<body>
    <div class="theme-toggle" onclick="toggleTheme()" title="Toggle theme">🌙</div>

    <div class="container">
        <div class="header fade-in">
            <h1>✨ Novel Scraper Pro</h1>
            <p>Advanced chapter fetching with intelligent detection</p>
        </div>

        <!-- Configuration Card -->
        <div class="card fade-in" id="config-card">
            <h2>⚙️ Configuration</h2>

            <label style="color: var(--text-muted); font-size: 0.9em; margin-bottom: 8px; display: block;">Scraping Mode</label>
            <div class="mode-selector">
                <div class="mode-btn active" onclick="setMode('pattern')" id="mode-pattern">
                    <div class="mode-title">🔗 Pattern Mode</div>
                    <div class="mode-desc">URL with chapter number pattern</div>
                </div>
                <div class="mode-btn" onclick="setMode('smart')" id="mode-smart">
                    <div class="mode-title">🧠 Smart Detect</div>
                    <div class="mode-desc">Auto-detect next page links</div>
                </div>
            </div>

            <div class="form-group">
                <label id="url-label">URL Pattern (use {} for chapter number)</label>
                <input type="text" id="url-input"
                       placeholder="https://example.com/novel/chapter-{}"
                       autocomplete="off">
                <div class="hint" id="url-hint">Example: https://novelsite.com/my-novel/chapter-{}</div>
            </div>

            <div class="form-row" id="chapter-range">
                <div class="form-group">
                    <label>Start Chapter</label>
                    <input type="number" id="start-chapter" value="1" min="1">
                </div>
                <div class="form-group">
                    <label id="end-label">End Chapter</label>
                    <input type="number" id="end-chapter" value="10" min="1">
                </div>
            </div>

            <div class="form-row">
                <div class="form-group">
                    <label>Output Filename</label>
                    <input type="text" id="filename" placeholder="my-novel" value="novel">
                </div>
                <div class="form-group" id="thread-group">
                    <label>Threads (1-10)</label>
                    <input type="number" id="threads" value="5" min="1" max="10">
                </div>
            </div>

            <button class="btn btn-primary" onclick="startScraping()" id="start-btn">
                🚀 Start Scraping
            </button>
        </div>

        <!-- Progress Card -->
        <div class="card progress-section" id="progress-card">
            <h2>
                📊 Progress
                <span class="status-badge status-running" id="status-badge">
                    <span class="status-dot"></span>
                    <span id="status-text">Running</span>
                </span>
            </h2>

            <div class="progress-bar-container">
                <div class="progress-bar" id="progress-bar"></div>
            </div>

            <div class="progress-stats">
                <div class="stat-item">
                    <div class="stat-value" id="stat-progress">0%</div>
                    <div class="stat-label">Progress</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value" id="stat-chapters">0/0</div>
                    <div class="stat-label">Chapters</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value" id="stat-errors">0</div>
                    <div class="stat-label">Errors</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value" id="stat-eta">--</div>
                    <div class="stat-label">ETA</div>
                </div>
            </div>

            <div class="actions-row">
                <button class="btn btn-warning btn-sm" onclick="pauseJob()" id="pause-btn">⏸️ Pause</button>
                <button class="btn btn-secondary btn-sm" onclick="resumeJob()" id="resume-btn" style="display:none">▶️ Resume</button>
                <button class="btn btn-danger btn-sm" onclick="cancelJob()">❌ Cancel</button>
            </div>

            <div class="tab-btns" style="margin-top: 20px;">
                <button class="tab-btn active" onclick="switchTab('logs')">📝 Logs</button>
                <button class="tab-btn" onclick="switchTab('errors')">⚠️ Errors</button>
            </div>

            <div class="tab-content active" id="tab-logs">
                <div class="log-panel" id="log-panel"></div>
            </div>

            <div class="tab-content" id="tab-errors">
                <div class="error-list" id="error-list">
                    <div style="color: var(--text-muted); text-align: center; padding: 20px;">No errors yet</div>
                </div>
            </div>
        </div>

        <!-- Download Card -->
        <div class="card progress-section" id="download-card">
            <div class="download-section">
                <h2 style="justify-content: center; margin-bottom: 20px;">🎉 Scraping Complete!</h2>
                <p style="color: var(--text-muted); margin-bottom: 20px;" id="download-info"></p>
                <button class="btn btn-success" onclick="downloadFile()" id="download-btn">
                    📥 Download Novel (.txt)
                </button>
            </div>
        </div>
    </div>

    <script>
        let currentMode = 'pattern';
        let currentJobId = null;
        let pollInterval = null;
        let isDark = true;

        function setMode(mode) {
            currentMode = mode;
            document.getElementById('mode-pattern').classList.toggle('active', mode === 'pattern');
            document.getElementById('mode-smart').classList.toggle('active', mode === 'smart');

            if (mode === 'pattern') {
                document.getElementById('url-label').textContent = 'URL Pattern (use {} for chapter number)';
                document.getElementById('url-input').placeholder = 'https://example.com/novel/chapter-{}';
                document.getElementById('url-hint').textContent = 'Example: https://novelsite.com/my-novel/chapter-{}';
                document.getElementById('end-label').textContent = 'End Chapter';
                document.getElementById('thread-group').style.display = '';
            } else {
                document.getElementById('url-label').textContent = 'Starting URL (first chapter)';
                document.getElementById('url-input').placeholder = 'https://example.com/novel/chapter-1';
                document.getElementById('url-hint').textContent = 'Enter the first chapter URL. The scraper will follow "Next" links automatically.';
                document.getElementById('end-label').textContent = 'Max Chapters';
                document.getElementById('thread-group').style.display = 'none';
            }
        }

        function toggleTheme() {
            isDark = !isDark;
            document.body.classList.toggle('light-mode', !isDark);
            document.querySelector('.theme-toggle').textContent = isDark ? '🌙' : '☀️';
        }

        function switchTab(tab) {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            if (tab === 'logs') {
                document.querySelectorAll('.tab-btn')[0].classList.add('active');
                document.getElementById('tab-logs').classList.add('active');
            } else {
                document.querySelectorAll('.tab-btn')[1].classList.add('active');
                document.getElementById('tab-errors').classList.add('active');
            }
        }

        function formatETA(seconds) {
            if (!seconds || seconds <= 0) return '--';
            if (seconds < 60) return seconds + 's';
            if (seconds < 3600) return Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's';
            return Math.floor(seconds / 3600) + 'h ' + Math.floor((seconds % 3600) / 60) + 'm';
        }

        async function startScraping() {
            const url = document.getElementById('url-input').value.trim();
            if (!url) {
                alert('Please enter a URL');
                return;
            }

            const config = {
                mode: currentMode,
                url_pattern: url,
                start_chapter: parseInt(document.getElementById('start-chapter').value) || 1,
                end_chapter: parseInt(document.getElementById('end-chapter').value) || 10,
                filename: document.getElementById('filename').value.trim() || 'novel',
                threads: parseInt(document.getElementById('threads').value) || 5
            };

            document.getElementById('start-btn').disabled = true;
            document.getElementById('start-btn').innerHTML = '<span class="spinner"></span> Starting...';

            try {
                const resp = await fetch('/api/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config)
                });
                const data = await resp.json();

                if (data.error) {
                    alert(data.error);
                    resetStartBtn();
                    return;
                }

                currentJobId = data.job_id;
                document.getElementById('progress-card').classList.add('active');
                document.getElementById('download-card').classList.remove('active');

                startPolling();
            } catch (e) {
                alert('Failed to start: ' + e.message);
                resetStartBtn();
            }
        }

        function resetStartBtn() {
            document.getElementById('start-btn').disabled = false;
            document.getElementById('start-btn').innerHTML = '🚀 Start Scraping';
        }

        function startPolling() {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(pollStatus, 1500);
        }

        async function pollStatus() {
            if (!currentJobId) return;

            try {
                const resp = await fetch('/api/status/' + currentJobId);
                const data = await resp.json();

                updateUI(data);

                if (['completed', 'failed', 'cancelled'].includes(data.status)) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                    resetStartBtn();

                    if (data.status === 'completed' && data.chapters_done > 0) {
                        document.getElementById('download-card').classList.add('active');
                        document.getElementById('download-info').textContent =
                            `${data.chapters_done} chapters scraped successfully!`;
                    }
                }
            } catch (e) {
                console.error('Poll error:', e);
            }
        }

        function updateUI(data) {
            // Progress bar
            document.getElementById('progress-bar').style.width = data.progress + '%';
            document.getElementById('stat-progress').textContent = data.progress + '%';
            document.getElementById('stat-chapters').textContent = data.chapters_done + '/' + data.total;
            document.getElementById('stat-errors').textContent = data.errors.length;
            document.getElementById('stat-eta').textContent = formatETA(data.eta_seconds);

            // Status badge
            const badge = document.getElementById('status-badge');
            const statusText = document.getElementById('status-text');
            badge.className = 'status-badge status-' + data.status;
            statusText.textContent = data.status.charAt(0).toUpperCase() + data.status.slice(1);

            // Logs
            const logPanel = document.getElementById('log-panel');
            let logHtml = '';
            data.logs.forEach(log => {
                logHtml += `<div class="log-entry">
                    <span class="log-time">[${log.time}]</span>
                    <span class="log-${log.level}">${escapeHtml(log.message)}</span>
                </div>`;
            });
            logPanel.innerHTML = logHtml;
            logPanel.scrollTop = logPanel.scrollHeight;

            // Errors
            const errorList = document.getElementById('error-list');
            if (data.errors.length > 0) {
                errorList.innerHTML = data.errors.map(e =>
                    `<div class="error-item">${escapeHtml(e)}</div>`
                ).join('');
            } else {
                errorList.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">No errors yet</div>';
            }

            // Pause/Resume buttons
            if (data.status === 'paused') {
                document.getElementById('pause-btn').style.display = 'none';
                document.getElementById('resume-btn').style.display = '';
            } else if (data.status === 'running') {
                document.getElementById('pause-btn').style.display = '';
                document.getElementById('resume-btn').style.display = 'none';
            }
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        async function pauseJob() {
            if (!currentJobId) return;
            await fetch('/api/pause/' + currentJobId, { method: 'POST' });
        }

        async function resumeJob() {
            if (!currentJobId) return;
            await fetch('/api/resume/' + currentJobId, { method: 'POST' });
        }

        async function cancelJob() {
            if (!currentJobId) return;
            if (!confirm('Are you sure you want to cancel?')) return;
            await fetch('/api/cancel/' + currentJobId, { method: 'POST' });
        }

        function downloadFile() {
            if (!currentJobId) return;
            window.location.href = '/api/download/' + currentJobId;
        }
    </script>
</body>
</html>"""


# ============================================================
# API Routes
# ============================================================

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/api/start', methods=['POST'])
def api_start():
    try:
        config = request.get_json()
        if not config:
            return jsonify({'error': 'No configuration provided'}), 400

        url = config.get('url_pattern', '').strip()
        if not url:
            return jsonify({'error': 'URL is required'}), 400

        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
            config['url_pattern'] = url

        mode = config.get('mode', 'pattern')
        if mode not in ('pattern', 'smart'):
            return jsonify({'error': 'Invalid mode'}), 400

        start_ch = int(config.get('start_chapter', 1))
        end_ch = int(config.get('end_chapter', 10))
        threads = min(int(config.get('threads', DEFAULT_THREADS)), MAX_THREADS)

        if end_ch - start_ch + 1 > MAX_CHAPTERS_LIMIT:
            return jsonify({'error': f'Maximum {MAX_CHAPTERS_LIMIT} chapters allowed'}), 400

        if start_ch < 1:
            return jsonify({'error': 'Start chapter must be >= 1'}), 400

        if mode == 'pattern' and end_ch < start_ch:
            return jsonify({'error': 'End chapter must be >= start chapter'}), 400

        config['start_chapter'] = start_ch
        config['end_chapter'] = end_ch
        config['threads'] = threads

        job_id = uuid.uuid4().hex
        job = ScrapingJob(job_id, config)

        with jobs_lock:
            # Cleanup old jobs (keep only last 10)
            if len(jobs) > 10:
                old_ids = sorted(jobs.keys(), key=lambda k: jobs[k].start_time or 0)
                for old_id in old_ids[:len(jobs) - 10]:
                    del jobs[old_id]
            jobs[job_id] = job

        # Run job in background thread
        thread = threading.Thread(target=run_job, args=(job_id,), daemon=True)
        thread.start()

        return jsonify({'job_id': job_id, 'status': 'started'})

    except Exception as e:
        logger.error(f"Start error: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/status/<job_id>')
def api_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job.get_status())


@app.route('/api/pause/<job_id>', methods=['POST'])
def api_pause(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    job.pause_event.clear()
    job.status = 'paused'
    job.log("Job paused.", 'warning')
    return jsonify({'status': 'paused'})


@app.route('/api/resume/<job_id>', methods=['POST'])
def api_resume(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    job.pause_event.set()
    job.status = 'running'
    job.log("Job resumed.")
    return jsonify({'status': 'running'})


@app.route('/api/cancel/<job_id>', methods=['POST'])
def api_cancel(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    job.cancel_flag = True
    job.pause_event.set()  # Unpause so it can exit
    job.log("Cancellation requested.", 'warning')
    return jsonify({'status': 'cancelling'})


@app.route('/api/download/<job_id>')
def api_download(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404

    if not job.output_file:
        # Try to compile if chapters exist
        if job.chapters:
            job._compile_output()
        else:
            return jsonify({'error': 'No content available'}), 404

    filename = job.config.get('filename', 'novel') or 'novel'
    filename = re.sub(r'[^\w\s\-]', '', filename).strip() or 'novel'

    buffer = BytesIO(job.output_file.encode('utf-8'))
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'{filename}.txt',
        mimetype='text/plain; charset=utf-8'
    )


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'active_jobs': len(jobs)})


# ============================================================
# Entry Point
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'

    logger.info(f"Starting Novel Scraper Pro on port {port}")

    app.run(
        host='0.0.0.0',
        port=port,
        debug=debug,
        threaded=True
    )