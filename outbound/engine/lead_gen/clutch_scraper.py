#!/usr/bin/env python3
"""
Production-Ready Clutch.co Business Scraper with Django ORM Integration
Handles JavaScript-rendered content, duplicates, rate limiting, and edge cases
Saves directly to Django Lead model instead of CSV
"""

import os
import sys
import time
import logging
from typing import Set, List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, unquote
from dataclasses import dataclass
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    WebDriverException,
    StaleElementReferenceException
)
from webdriver_manager.chrome import ChromeDriverManager

# ---------------- Django Setup ----------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "genesis_engine.settings")  # <- replace with your project

try:
    import django
    django.setup()
    from django.db import IntegrityError, transaction
    from django.core.exceptions import ValidationError
    from outbound.models import Lead  # UPDATE THIS TO YOUR ACTUAL APP NAME
    print("✅ Django setup complete")
except Exception as e:
    print(f"⚠️  Django setup failed: {e}")
    sys.exit(1)


# ---------------- Configuration ----------------
@dataclass
class ScraperConfig:
    """Production configuration for the scraper"""
    base_url: str = "https://clutch.co"
    max_pages: int = 10
    page_delay: float = 5.0  # Delay between pages
    element_timeout: int = 20
    max_retries: int = 3
    retry_delay: float = 10.0
    headless: bool = False  # Set to True for production
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    save_batch_size: int = 10  # Save to DB in batches
    captcha_timeout: int = 120  # Max wait time for CAPTCHA resolution
    scroll_pause: float = 2.0  # Pause between scrolls


# ---------------- Logger Setup ----------------
def setup_logger(log_file: Optional[str] = None) -> logging.Logger:
    """Set up production logging configuration"""
    logger = logging.getLogger('clutch_scraper_prod')
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Console handler
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # File handler (optional)
        if log_file:
            file_handler = logging.FileHandler(log_file)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

    return logger


# ---------------- Database Helper ----------------
class LeadManager:
    """Manages Lead database operations with duplicate prevention"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.processed_websites: Set[str] = set()
        self.load_existing_websites()

    def load_existing_websites(self):
        """Load existing websites from database to prevent duplicates"""
        try:
            existing = Lead.objects.values_list('website', flat=True)
            self.processed_websites = set(url.lower().strip() for url in existing if url)
            self.logger.info(f"📊 Loaded {len(self.processed_websites)} existing websites from database")
        except Exception as e:
            self.logger.error(f"Failed to load existing websites: {e}")
            self.processed_websites = set()

    def normalize_website(self, url: str) -> str:
        """Normalize website URL for comparison"""
        if not url:
            return ""

        url = url.lower().strip()
        # Remove trailing slash
        url = url.rstrip('/')
        # Remove www.
        url = url.replace('://www.', '://')
        return url

    def is_duplicate(self, website: str) -> bool:
        """Check if website already exists in database"""
        normalized = self.normalize_website(website)
        return normalized in self.processed_websites

    def save_lead(self, name: str, website: str, niche: str,
                  clutch_url: str = "", source: str = "Clutch.co") -> Tuple[bool, Optional[Lead]]:
        """
        Save a single lead to database with validation
        Returns: (success: bool, lead: Lead or None)
        """
        try:
            # Normalize and validate
            website = self.normalize_website(website)

            if not website or not name:
                self.logger.debug(f"Invalid lead data: name={name}, website={website}")
                return False, None

            # Check for duplicates
            if self.is_duplicate(website):
                self.logger.debug(f"Duplicate website: {website}")
                return False, None

            print('-----',clutch_url)
            print('-----',website)


            # Create lead with transaction
            with transaction.atomic():
                lead, created = Lead.objects.get_or_create(
                    website=website,
                    defaults={
                        'name': name.strip(),
                        'source': source,
                        'website': website.strip() if website else "",
                        'created_at': datetime.now(),
                        # Add any other fields your Lead model has
                    }
                )

                if created:
                    self.processed_websites.add(website)
                    self.logger.info(f"✅ Saved: {name} - {website}")
                    return True, lead
                else:
                    self.logger.debug(f"Lead already exists: {website}")
                    return False, lead

        except IntegrityError as e:
            self.logger.warning(f"Integrity error saving lead {name}: {e}")
            return False, None
        except ValidationError as e:
            self.logger.warning(f"Validation error for {name}: {e}")
            return False, None
        except Exception as e:
            self.logger.error(f"Unexpected error saving lead {name}: {e}")
            return False, None

    def save_leads_batch(self, leads_data: List[dict]) -> Tuple[int, int]:
        """
        Save multiple leads in a batch transaction
        Returns: (saved_count, skipped_count)
        """
        saved = 0
        skipped = 0

        for lead_data in leads_data:
            success, _ = self.save_lead(
                name=lead_data.get('name', ''),
                website=lead_data.get('website', ''),
                source=lead_data.get('source', 'Clutch.co')
            )

            if success:
                saved += 1
            else:
                skipped += 1

        return saved, skipped


# ---------------- Scraper Class ----------------
class ClutchScraperProd:
    """Production-ready Clutch.co scraper with Django ORM integration"""

    def __init__(self, config: ScraperConfig, niche: str, log_file: Optional[str] = None):
        self.config = config
        self.niche = niche
        self.logger = setup_logger(log_file)
        self.driver: Optional[webdriver.Chrome] = None
        self.lead_manager = LeadManager(self.logger)
        self.stats = {
            'pages_scraped': 0,
            'leads_found': 0,
            'leads_saved': 0,
            'duplicates_skipped': 0,
            'errors': 0
        }

    def setup_driver(self) -> webdriver.Chrome:
        """Initialize Chrome driver with production settings"""
        self.logger.info("🚀 Setting up Chrome driver...")

        chrome_options = Options()

        if self.config.headless:
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--disable-gpu")

        # Anti-detection measures
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument(f"--user-agent={self.config.user_agent}")

        # Performance optimizations
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-plugins")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-images")  # Faster loading
        chrome_options.add_argument("--disable-javascript-harmony")

        # Memory optimization
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-software-rasterizer")

        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

            # Stealth JavaScript injection
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    window.chrome = { runtime: {} };
                '''
            })

            self.logger.info("✅ Chrome driver initialized")
            return driver

        except Exception as e:
            self.logger.error(f"Failed to initialize Chrome driver: {e}")
            raise

    def extract_real_website(self, redirect_url: str) -> Optional[str]:
        """Extract actual website from Clutch's redirect URL"""
        try:
            if not redirect_url:
                return None

            parsed = urlparse(redirect_url)

            # Handle Clutch redirect URLs
            if 'clutch.co' in parsed.netloc and '/redirect' in parsed.path:
                query_params = parse_qs(parsed.query)
                if 'u' in query_params:
                    real_url = unquote(query_params['u'][0])
                    # Clean URL
                    real_parsed = urlparse(real_url)
                    clean_url = f"{real_parsed.scheme}://{real_parsed.netloc}{real_parsed.path}"
                    return clean_url.rstrip('/')

            # Direct URL (not redirect)
            if 'clutch.co' not in redirect_url:
                parsed = urlparse(redirect_url)
                clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                return clean_url.rstrip('/')

        except Exception as e:
            self.logger.debug(f"Failed to extract URL from {redirect_url}: {e}")

        return None

    def is_valid_website(self, url: str) -> bool:
        """Validate if URL is a legitimate business website"""
        if not url:
            return False

        # Exclude social media and non-business domains
        excluded_domains = {
            'facebook.com', 'fb.com', 'twitter.com', 'x.com', 'linkedin.com',
            'instagram.com', 'youtube.com', 'youtu.be', 'tiktok.com',
            'pinterest.com', 'behance.net', 'dribbble.com', 'github.com',
            'clutch.co', 'goodfirms.co', 'upwork.com', 'fiverr.com',
            'mailto:', 'tel:', 'javascript:'
        }

        try:
            parsed = urlparse(url.lower())
            domain = parsed.netloc.replace('www.', '')

            # Check if domain is in excluded list
            for excluded in excluded_domains:
                if excluded in domain:
                    return False

            # Must have valid scheme
            if parsed.scheme not in ['http', 'https']:
                return False

            # Must have a domain
            if not domain or '.' not in domain:
                return False

            return True

        except Exception:
            return False

    def handle_captcha_detection(self) -> bool:
        """Detect and handle CAPTCHA challenges"""
        page_source = self.driver.page_source.lower()
        page_title = self.driver.title.lower()

        captcha_indicators = [
            'captcha', 'verify you are human', 'complete the action',
            'cloudflare', 'please verify', 'security check',
            'human verification', 'prove you are human'
        ]

        if any(indicator in page_source or indicator in page_title for indicator in captcha_indicators):
            self.logger.warning("🤖 CAPTCHA detected!")
            self.logger.info(f"Page title: {self.driver.title}")
            self.logger.info(f"Current URL: {self.driver.current_url}")

            if not self.config.headless:
                self.logger.info("🖱️  Browser is visible - you can manually solve the CAPTCHA")
                self.logger.info("⏳ Waiting 60 seconds for manual intervention...")

                # Wait for user to solve CAPTCHA manually
                for i in range(60, 0, -5):
                    time.sleep(5)
                    current_title = self.driver.title.lower()
                    if not any(indicator in current_title for indicator in captcha_indicators):
                        self.logger.info("✅ CAPTCHA appears to be resolved!")
                        return True
                    self.logger.info(f"⏳ Still waiting... {i - 5} seconds remaining")

                self.logger.warning("⏰ Timeout waiting for CAPTCHA resolution")
                return False
            else:
                self.logger.error("❌ CAPTCHA detected in headless mode - cannot proceed")
                return False

        return True  # No CAPTCHA detected

    def smart_scroll(self):
        """Intelligent scrolling to trigger lazy loading"""
        try:
            # Get page height
            total_height = self.driver.execute_script("return document.body.scrollHeight")

            # Scroll in segments
            scroll_positions = [0.25, 0.5, 0.75, 1.0]

            for position in scroll_positions:
                scroll_to = int(total_height * position)
                self.driver.execute_script(f"window.scrollTo(0, {scroll_to});")
                time.sleep(self.config.scroll_pause)

            # Scroll back to top
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(self.config.scroll_pause)

        except Exception as e:
            self.logger.debug(f"Scroll error: {e}")

    def find_business_cards(self) -> Tuple[List, Optional[str]]:
        """Locate business card elements with multiple strategies"""

        # Primary selectors (based on current Clutch structure)
        selectors = [
            ".provider",
            "li.provider",
            ".provider-item",
            ".directory-providers .provider",
            "[data-provider-id]",
            ".company-listing",
            "article.provider"
        ]

        for selector in selectors:
            try:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements and len(elements) > 0:
                    self.logger.info(f"✅ Found {len(elements)} cards with: {selector}")
                    return elements, selector
            except Exception as e:
                self.logger.debug(f"Selector '{selector}' failed: {e}")

        # Fallback: find by website links
        try:
            website_links = self.driver.find_elements(
                By.CSS_SELECTOR,
                "a[href*='redirect'][title*='Visit'], a.website-link__item"
            )

            if website_links:
                cards = []
                for link in website_links:
                    try:
                        parent = link.find_element(
                            By.XPATH,
                            "./ancestor::*[contains(@class, 'provider') or contains(@class, 'listing')][1]"
                        )
                        if parent not in cards:
                            cards.append(parent)
                    except:
                        pass

                if cards:
                    self.logger.info(f"✅ Found {len(cards)} cards via fallback method")
                    return cards, "fallback-website-links"

        except Exception as e:
            self.logger.debug(f"Fallback method failed: {e}")

        self.logger.warning("❌ No business cards found")
        return [], None

    def extract_business_data(self, card) -> Optional[dict]:
        """Extract business information from card element with retry logic"""
        max_attempts = 2

        for attempt in range(max_attempts):
            try:
                # Extract business name
                name_selectors = [
                    "h3.provider__name a",
                    ".provider__name a",
                    "h3 a[href*='/profile/']",
                    ".company-name a",
                    "h2 a"
                ]

                name_element = None
                for selector in name_selectors:
                    try:
                        name_element = card.find_element(By.CSS_SELECTOR, selector)
                        if name_element and name_element.text.strip():
                            break
                    except NoSuchElementException:
                        continue

                if not name_element:
                    return None

                business_name = name_element.text.strip()
                clutch_profile = name_element.get_attribute('href') or ""

                # Extract website URL
                website_selectors = [
                    "a.provider__cta-link.website-link__item[href*='redirect']",
                    "a[href*='redirect'][title*='Visit']",
                    ".website-link__item[href*='redirect']",
                    "a.visit-website"
                ]

                website_url = None
                for selector in website_selectors:
                    try:
                        website_elem = card.find_element(By.CSS_SELECTOR, selector)
                        redirect_url = website_elem.get_attribute('href')
                        if redirect_url:
                            website_url = self.extract_real_website(redirect_url)
                            if website_url:
                                break
                    except NoSuchElementException:
                        continue

                if not website_url or not self.is_valid_website(website_url):
                    self.logger.debug(f"Invalid/missing website for: {business_name}")
                    return None

                return {
                    'name': business_name,
                    'website': website_url,
                    'clutch_url': clutch_profile,
                    'niche': self.niche
                }

            except StaleElementReferenceException:
                if attempt < max_attempts - 1:
                    self.logger.debug(f"Stale element, retry {attempt + 1}")
                    time.sleep(1)
                    continue
                else:
                    return None
            except Exception as e:
                self.logger.debug(f"Error extracting business data: {e}")
                return None

        return None

    def scrape_page(self, url: str, page_num: int) -> int:
        """Scrape a single page and save leads to database"""
        self.logger.info(f"📄 Scraping page {page_num}: {url}")
        leads_saved = 0

        try:
            self.driver.get(url)
            time.sleep(self.config.page_delay)

            # Handle CAPTCHA
            if not self.handle_captcha_detection():
                self.stats['errors'] += 1
                return 0

            # Smart scrolling
            self.smart_scroll()

            # Find business cards
            cards, selector = self.find_business_cards()

            if not cards:
                self.logger.warning(f"No cards found on page {page_num}")
                return 0

            self.logger.info(f"Processing {len(cards)} business cards...")

            # Process cards
            for idx, card in enumerate(cards, 1):
                try:
                    business_data = self.extract_business_data(card)

                    if not business_data:
                        continue

                    self.stats['leads_found'] += 1

                    # Save to database
                    success, lead = self.lead_manager.save_lead(
                        name=business_data['name'],
                        website=business_data['website'],
                        niche=business_data['niche'],
                        clutch_url=business_data['clutch_url']
                    )

                    if success:
                        leads_saved += 1
                        self.stats['leads_saved'] += 1
                    else:
                        self.stats['duplicates_skipped'] += 1

                except Exception as e:
                    self.logger.error(f"Error processing card {idx}: {e}")
                    self.stats['errors'] += 1
                    continue

            self.stats['pages_scraped'] += 1

        except TimeoutException:
            self.logger.error(f"Timeout on page {page_num}")
            self.stats['errors'] += 1
        except Exception as e:
            self.logger.error(f"Error scraping page {page_num}: {e}")
            self.stats['errors'] += 1

        return leads_saved

    def scrape_niche_url(self, base_url: str) -> dict:
        """Scrape all pages for a niche URL"""
        self.logger.info(f"🎯 Starting scrape for niche: {self.niche}")
        self.logger.info(f"🔗 Base URL: {base_url}")

        for page_num in range(1, self.config.max_pages + 1):
            # Construct paginated URL
            if page_num == 1:
                url = base_url
            else:
                separator = "&" if "?" in base_url else "?"
                url = f"{base_url}{separator}page={page_num}"

            # Scrape page with retry logic
            for retry in range(self.config.max_retries):
                try:
                    leads_saved = self.scrape_page(url, page_num)

                    if leads_saved == 0 and page_num > 1:
                        self.logger.info(f"No leads found on page {page_num}, stopping pagination")
                        return self.stats

                    break  # Success, move to next page

                except Exception as e:
                    if retry < self.config.max_retries - 1:
                        self.logger.warning(f"Retry {retry + 1}/{self.config.max_retries} after error: {e}")
                        time.sleep(self.config.retry_delay)
                    else:
                        self.logger.error(f"Failed after {self.config.max_retries} retries: {e}")
                        self.stats['errors'] += 1

            # Delay between pages
            time.sleep(self.config.page_delay)

        return self.stats

    def run(self, niche_urls: List[str]) -> dict:
        """Main execution method"""
        start_time = datetime.now()

        try:
            self.driver = self.setup_driver()
            self.logger.info(f"🚀 Starting scrape for {len(niche_urls)} URL(s)")

            for url in niche_urls:
                self.scrape_niche_url(url)

            # Final statistics
            duration = (datetime.now() - start_time).total_seconds()

            self.logger.info("=" * 60)
            self.logger.info("📊 SCRAPING COMPLETE")
            self.logger.info(f"⏱️  Duration: {duration:.1f}s")
            self.logger.info(f"📄 Pages scraped: {self.stats['pages_scraped']}")
            self.logger.info(f"🔍 Leads found: {self.stats['leads_found']}")
            self.logger.info(f"💾 Leads saved: {self.stats['leads_saved']}")
            self.logger.info(f"⏭️  Duplicates skipped: {self.stats['duplicates_skipped']}")
            self.logger.info(f"❌ Errors: {self.stats['errors']}")
            self.logger.info("=" * 60)

            return self.stats

        except KeyboardInterrupt:
            self.logger.warning("⏹️  Interrupted by user")
            return self.stats
        except Exception as e:
            self.logger.error(f"💥 Critical error: {e}", exc_info=True)
            raise
        finally:
            if self.driver:
                self.driver.quit()
                self.logger.info("🚪 Browser closed")


# ---------------- CLI Interface ----------------
def main():
    """Command-line interface"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Production Clutch.co scraper with Django ORM integration"
    )
    parser.add_argument(
        'niche',
        help='Niche/industry to scrape (e.g., "digital-marketing")'
    )
    parser.add_argument(
        '--urls',
        nargs='+',
        help='Clutch.co URLs to scrape',
        default=None
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=10,
        help='Maximum pages to scrape per URL (default: 10)'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='Run in headless mode'
    )
    parser.add_argument(
        '--log-file',
        help='Log file path (optional)'
    )

    args = parser.parse_args()

    # Default URLs if none provided
    if not args.urls:
        args.urls = [
            f"https://clutch.co/agencies/{args.niche}",
            f"https://clutch.co/{args.niche}-companies"
        ]

    # Configuration
    config = ScraperConfig(
        max_pages=args.max_pages,
        headless=args.headless,
        page_delay=5.0,
        element_timeout=20
    )

    # Initialize and run scraper
    scraper = ClutchScraperProd(
        config=config,
        niche=args.niche,
        log_file=args.log_file
    )

    try:
        stats = scraper.run(args.urls)

        if stats['leads_saved'] > 0:
            print(f"\n✅ Successfully saved {stats['leads_saved']} leads to database")
        else:
            print(f"\n⚠️  No new leads saved")

        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()