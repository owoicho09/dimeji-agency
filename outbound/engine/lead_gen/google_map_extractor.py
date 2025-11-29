import asyncio
from playwright.async_api import async_playwright
import django
import os, sys, re, csv
from urllib.parse import urljoin, urlparse
from asgiref.sync import sync_to_async

import time
import sys

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "genesis_engine.settings")  # <- replace with your project
django.setup()
from outbound.models import Lead  # <- replace with your app name

# Enhanced email regex patterns
EMAIL_PATTERNS = [
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'email[:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
    r'contact[:\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
]

# Common pages to check for contact info
CONTACT_PAGES = [
    '/contact',
    '/contact-us',
    '/about',
    '/about-us',
    '/team',
    '/staff',
    '/get-in-touch',
    '/reach-out',
    '/connect',
    '/book',
    '/booking',
    '/consultation',
]


async def extract_emails_from_content(content):
    """Extract emails using multiple regex patterns"""
    print("    🔍 Starting email extraction from content...")
    emails = set()

    for i, pattern in enumerate(EMAIL_PATTERNS):
        print(f"    📧 Trying pattern {i + 1}: {pattern}")
        matches = re.findall(pattern, content, re.IGNORECASE)
        print(f"    📧 Pattern {i + 1} found {len(matches)} matches")

        if matches and isinstance(matches[0], tuple):
            pattern_emails = [match[0] for match in matches]
        else:
            pattern_emails = matches

        emails.update(pattern_emails)
        print(f"    📧 Pattern {i + 1} emails: {pattern_emails}")

    print(f"    📧 Total raw emails found: {len(emails)}")
    print(f"    📧 Raw emails: {list(emails)}")

    # Enhanced filtering - exclude common non-personal emails and error tracking
    filtered_emails = []
    exclude_patterns = [
        r'noreply@', r'no-reply@', r'support@', r'hello@',
        r'admin@', r'webmaster@', r'postmaster@', r'mail@', r'contact@',
        r'example\.com', r'test\.com', r'placeholder', r'localhost',
        r'@facebook\.com', r'@twitter\.com', r'@instagram\.com',
        r'@linkedin\.com', r'@youtube\.com', r'@gmail\.com',
        r'@sentry\.', r'@sentry\.io', r'@sentry\.wixpress\.com',  # Sentry error tracking
        r'@wixpress\.com', r'@wix\.com',  # Wix platform emails
        r'@hubspot\.com', r'@mailchimp\.com', r'@constantcontact\.com',
        r'@sendgrid\.', r'@mailgun\.', r'@amazonaws\.com',
        r'[0-9a-f]{8}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{4}[0-9a-f]{12}@',  # UUID-like patterns
        r'^[0-9a-f]{32}@',  # Hash-like patterns
    ]

    for email in emails:
        email_lower = email.lower()
        print(f"    🔍 Checking email: {email_lower}")

        excluded = False
        for pattern in exclude_patterns:
            if re.search(pattern, email_lower, re.IGNORECASE):
                print(f"    ❌ Excluded {email_lower} (matches pattern: {pattern})")
                excluded = True
                break

        if not excluded:
            print(f"    ✅ Accepted email: {email_lower}")
            filtered_emails.append(email_lower)

    print(f"    📧 Final filtered emails: {len(filtered_emails)}")
    print(f"    📧 Filtered emails list: {filtered_emails}")

    return list(set(filtered_emails))


async def extract_business_description(page):
    """Extract meaningful business description from various sources"""
    print("    📝 Starting business description extraction...")
    descriptions = []

    # Try different selectors for business descriptions
    selectors = [
        'meta[name="description"]',
        'meta[property="og:description"]',
        '[class*="about"]',
        '[class*="description"]',
        '[class*="intro"]',
        '[class*="mission"]',
        '[class*="vision"]',
        '[class*="services"]',
        'h1 + p',
        'h2 + p',
        '.hero p',
        '.banner p',
        'main p:first-of-type',
    ]

    for selector in selectors:
        try:
            print(f"    📝 Trying selector: {selector}")
            elements = await page.locator(selector).all()
            print(f"    📝 Found {len(elements)} elements for selector: {selector}")

            for element in elements:
                text = await element.text_content()
                if text and len(text.strip()) > 50:  # Only meaningful text
                    descriptions.append(text.strip())
                    print(f"    📝 Found description: {text.strip()[:100]}...")
        except Exception as e:
            print(f"    ⚠️ Error with selector {selector}: {e}")
            continue

    # If no specific descriptions found, get general page text
    if not descriptions:
        print("    📝 No specific descriptions found, trying general paragraphs...")
        try:
            paragraphs = await page.locator("p").all_text_contents()
            print(f"    📝 Found {len(paragraphs)} paragraphs")
            descriptions = [p.strip() for p in paragraphs if len(p.strip()) > 50]
            print(f"    📝 Filtered to {len(descriptions)} meaningful paragraphs")
        except Exception as e:
            print(f"    ⚠️ Error getting paragraphs: {e}")

    # Return best description (longest meaningful one)
    if descriptions:
        best_desc = max(descriptions, key=len)
        final_desc = best_desc[:500] if len(best_desc) > 500 else best_desc
        print(f"    📝 Selected best description: {final_desc[:100]}...")
        return final_desc

    print("    📝 No description found")
    return None


async def scrape_page_thoroughly(page, base_url):
    """Thoroughly scrape a page and related contact pages"""
    print(f"  🔍 Starting thorough scrape of: {base_url}")
    all_emails = set()
    description = None

    try:
        # First, extract from current page
        print("  📄 Extracting from main page...")
        content = await page.content()
        print(f"  📄 Page content length: {len(content)} characters")

        emails = await extract_emails_from_content(content)
        all_emails.update(emails)
        print(f"  📄 Main page emails: {emails}")

        # Get description from current page
        if not description:
            description = await extract_business_description(page)

        # Check for contact links and visit them
        contact_links = []

        # Look for contact page links
        print("  🔗 Building contact page URLs...")
        for contact_path in CONTACT_PAGES:
            try:
                contact_url = urljoin(base_url, contact_path)
                contact_links.append(contact_url)
                print(f"  🔗 Added contact URL: {contact_url}")
            except Exception as e:
                print(f"  ⚠️ Error building contact URL {contact_path}: {e}")
                continue

        # Also look for contact links in the page
        print("  🔗 Looking for contact links in page...")
        try:
            links = await page.locator('a[href*="contact"], a[href*="about"]').all()
            print(f"  🔗 Found {len(links)} contact/about links")

            for i, link in enumerate(links[:5]):  # Limit to avoid too many requests
                href = await link.get_attribute('href')
                if href:
                    full_url = urljoin(base_url, href)
                    contact_links.append(full_url)
                    print(f"  🔗 Added link {i + 1}: {full_url}")
        except Exception as e:
            print(f"  ⚠️ Error finding contact links: {e}")

        # Visit contact pages
        unique_contact_links = list(set(contact_links))[:3]  # Limit to 3 contact pages
        print(f"  🔗 Will visit {len(unique_contact_links)} contact pages")

        for i, contact_url in enumerate(unique_contact_links):
            try:
                print(f"  📧 [{i + 1}/{len(unique_contact_links)}] Checking contact page: {contact_url}")
                await page.goto(contact_url, timeout=15000)
                await page.wait_for_timeout(2000)

                contact_content = await page.content()
                print(f"  📧 Contact page content length: {len(contact_content)} characters")

                contact_emails = await extract_emails_from_content(contact_content)
                all_emails.update(contact_emails)
                print(f"  📧 Contact page emails: {contact_emails}")

                # Get description from contact page if not found yet
                if not description:
                    description = await extract_business_description(page)

            except Exception as e:
                print(f"  ⚠️ Could not access contact page {contact_url}: {e}")
                continue

        final_emails = list(all_emails)
        print(f"  ✅ Total emails found: {len(final_emails)}")
        print(f"  ✅ Final email list: {final_emails}")
        print(f"  ✅ Description found: {'Yes' if description else 'No'}")

        return final_emails, description

    except Exception as e:
        print(f"  ❌ Error during thorough scraping: {e}")
        return [], None


# Create async versions of Django ORM operations
@sync_to_async
def get_leads_without_email():
    """Get all leads that don't have an email"""
    return list(Lead.objects.filter(email__isnull=True))


@sync_to_async
def update_lead_with_email(lead_id, email, description):
    """Update lead with scraped email and description"""
    lead = Lead.objects.get(lead_id=lead_id)
    lead.email = email
    if description:
        lead.note = description
    lead.save()
    return lead


async def process_database_and_scrape():
    """Main function to process database leads and scrape websites"""
    print(f"🚀 Starting database processing and scraping...")

    async with async_playwright() as p:
        print("🌐 Launching browser...")
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )

        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        )

        processed_count = 0
        successful_extractions = 0

        try:
            print("📂 Querying database for leads without email...")
            leads = await get_leads_without_email()
            print(f"📊 Found {len(leads)} leads to process")

            for lead in leads:
                name = lead.name if hasattr(lead, 'name') else " "
                url = lead.website if hasattr(lead, 'website') else " "
                phone = lead.phone if hasattr(lead, 'phone') else None
                address = lead.address if hasattr(lead, 'address') else None

                processed_count += 1

                print(f"\n{'=' * 80}")
                print(f"🔗 [{processed_count}/{len(leads)}] Processing: {name}")
                print(f"🌐 URL: {url}")

                if not url:
                    print(f"⚠️ No URL found for {name}")
                    continue

                # Ensure URL has protocol
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                    print(f"🔧 Fixed URL: {url}")

                try:
                    print(f"🚀 Creating new page...")
                    page = await context.new_page()

                    print(f"🌐 Navigating to: {url}")
                    await page.goto(url, timeout=30000, wait_until='domcontentloaded')
                    print(f"⏱️ Waiting for page to load...")
                    await page.wait_for_timeout(3000)

                    # Thorough scraping
                    print(f"🔍 Starting thorough scraping...")
                    emails, description = await scrape_page_thoroughly(page, url)

                    if emails:
                        print(f"✅ Found {len(emails)} email(s): {', '.join(emails)}")

                        # Update the lead with the first email found
                        primary_email = emails[0]
                        print(f"  💾 Updating lead with email: {primary_email}")

                        await update_lead_with_email(lead.lead_id, primary_email, description)
                        print(f"  ✅ Updated lead: {primary_email}")

                        successful_extractions += 1
                    else:
                        print(f"❌ No emails found for {name}")

                    print(f"🗑️ Closing page...")
                    await page.close()

                    # Add delay between requests to be respectful
                    print(f"⏱️ Waiting 2 seconds before next request...")
                    await asyncio.sleep(2)

                except Exception as e:
                    print(f"❌ Failed to scrape {url}: {e}")
                    print(f"❌ Error type: {type(e).__name__}")
                    continue

        except Exception as e:
            print(f"❌ Error processing database: {e}")
        finally:
            print(f"🚫 Closing browser...")
            await browser.close()
            print(f"\n📊 FINAL SUMMARY:")
            print(f"📊 Processed: {processed_count} websites")
            print(f"📊 Successful extractions: {successful_extractions}")
            print(
                f"📊 Success rate: {(successful_extractions / processed_count) * 100:.1f}%" if processed_count > 0 else "0%")
            subject = "Genesis Google Map Extraction Completed "

            # Calculate success rate with 1 decimal place
            if processed_count > 0:
                success_rate = f"{(successful_extractions / processed_count) * 100:.1f}%"
            else:
                success_rate = "0%"

            message = f"""
Hi Michael,

Here's your scraping update from Genesis.ai:

- 📊 Processed: {processed_count} websites
- 📊 Successful extractions: {successful_extractions}
-   Success rate: {success_rate}
Keep grinding 💪

– Genesis.ai Bot
            """


def run_email_extractor(verbose=True):
    """
    Run the email extractor on database leads.
    :param niche: Niche label to associate with scraped leads.
    :param verbose: Whether to print logs.
    """
    if verbose:
        print("🎯 EMAIL SCRAPER STARTING")
        print("=" * 80)
        print("\n🚀 Starting scraping process...")

    return asyncio.run(process_database_and_scrape())


import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run email extractor on database leads.")


    run_email_extractor()