#!/usr/bin/env python3
"""
Smart Cold Outreach Engine
===========================
Intelligent email outreach with tracking, rotation, and real-time metrics.
"""
import os
import re
import sys
import time
import uuid
import random
import logging
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

import django
from django.core.mail import EmailMultiAlternatives, get_connection
from django.conf import settings
from django.utils import timezone
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

# Django setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "genesis_engine.settings")
django.setup()

from outbound.models import VerifiedLead, OutboundMessage


@dataclass
class SMTPConfig:
    """SMTP provider configuration"""
    provider: str
    host: str
    port: int
    use_tls: bool
    username: str
    password: str
    daily_limit: int = 10  # emails per day per inbox


class SmartOutreachEngine:
    """
    Intelligent outreach engine with:
    - Tracking pixel for open monitoring
    - Smart inbox rotation
    - Real-time metrics collection
    - Exponential backoff and retry logic
    """

    def __init__(self, openai_api_key: str, smtp_configs: List[SMTPConfig],
                 tracking_domain: str = os.getenv('TRACKING_DOMAIN', 'https://yourdomain.com')):
        self.client = OpenAI(api_key=openai_api_key)
        self.smtp_configs = smtp_configs
        self.tracking_domain = tracking_domain
        self.logger = self._setup_logging()

        # Inbox rotation tracking
        self.inbox_usage = {config.username: 0 for config in smtp_configs}
        self.current_inbox_index = 0

    def _setup_logging(self) -> logging.Logger:
        """Configure structured logging"""
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)

        if logger.handlers:
            return logger

        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        # File handler with rotation
        file_handler = logging.FileHandler('logs/outreach_engine.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        return logger

    def get_next_inbox(self) -> SMTPConfig:
        """
        Smart inbox rotation with daily limits.
        Cycles through inboxes and skips those that hit daily limits.
        """
        attempts = 0
        while attempts < len(self.smtp_configs):
            config = self.smtp_configs[self.current_inbox_index]

            if self.inbox_usage[config.username] < config.daily_limit:
                self.current_inbox_index = (self.current_inbox_index + 1) % len(self.smtp_configs)
                return config

            self.logger.warning(f"Inbox {config.username} hit daily limit ({config.daily_limit})")
            self.current_inbox_index = (self.current_inbox_index + 1) % len(self.smtp_configs)
            attempts += 1

        raise Exception("All inboxes have reached their daily limits")

    def generate_tracking_pixel(self, lead_id: str) -> str:
        """Generate unique tracking pixel HTML for email opens"""
        tracking_url = f"{self.tracking_domain}/api/track/open/{lead_id}/"
        return f'<img src="{tracking_url}" width="1" height="1" style="display:none;" alt="" />'

    def generate_personalized_email(self, lead: VerifiedLead, max_retries: int = 3) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate personalized email using GPT with enhanced prompt engineering.
        """
        prompt = self._build_smart_prompt(lead)

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are an expert cold email copywriter who writes brief, human emails that get responses."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.85,
                    max_tokens=350
                )

                subject, body = self._parse_email_response(response.choices[0].message.content)

                if subject and body:
                    self.logger.info(f"✓ Generated email for {lead.email}")
                    return subject, body

                self.logger.warning(f"Incomplete response for {lead.email}, retry {attempt + 1}/{max_retries}")

            except Exception as e:
                self.logger.error(f"OpenAI error for {lead.email}, attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff

        return None, None

    def _build_smart_prompt(self, lead: VerifiedLead) -> str:
        """Build context-aware prompt for GPT"""
        return f"""Write a short, casual cold email to {lead.name or "this lead"}.

Context:
- Company: {lead.name or "their business"}
- Website: {lead.website or "N/A"}
- Personalization: {lead.personalization_note or "N/A"}

Guidelines:
- Keep it under 65 words total
- Subject line: lowercase, curiosity-driven, under 8 words
- Body: 2-3 sentences (compliment → pain point → soft CTA)
- End with something like "interested in seeing how?" or "want a quick look?"
- Sound human, not salesy

Format your response as:
SUBJECT: [subject here]

BODY: [body here]
"""

    def _parse_email_response(self, raw_output: str) -> Tuple[Optional[str], Optional[str]]:
        """Parse GPT response into subject and body"""
        try:
            subject = None
            body = None

            # Try structured parsing first
            if "SUBJECT:" in raw_output.upper() and "BODY:" in raw_output.upper():
                subject_match = re.search(r"SUBJECT:\s*(.+?)(?=\n|BODY:)", raw_output, re.IGNORECASE | re.DOTALL)
                body_match = re.search(r"BODY:\s*(.+)", raw_output, re.IGNORECASE | re.DOTALL)

                subject = subject_match.group(1).strip() if subject_match else None
                body = body_match.group(1).strip() if body_match else None
            else:
                # Fallback: first line = subject, rest = body
                lines = [line.strip() for line in raw_output.strip().splitlines() if line.strip()]

                if len(lines) >= 2:
                    subject = lines[0]
                    body = "\n".join(lines[1:])
                elif len(lines) == 1:
                    subject = lines[0]
                    body = ""

            # Clean formatting artifacts
            if subject:
                subject = re.sub(r"^[*•\-]+\s*", "", subject)
                subject = re.sub(r"(?i)^subject:\s*", "", subject).strip()
            if body:
                body = re.sub(r"(?i)^body:\s*", "", body).strip()

            return subject, body

        except Exception as e:
            self.logger.error(f"Parse error: {str(e)}")
            return None, None

    def send_email_with_tracking(self, subject: str, body: str, lead: VerifiedLead,
                                 smtp_config: SMTPConfig) -> bool:
        """
        Send email with embedded tracking pixel for open monitoring.
        """
        try:
            # Generate tracking pixel
            tracking_pixel = self.generate_tracking_pixel(lead.lead_id)
            self.logger.info(f"Tracking pixel: {tracking_pixel}")  # ← ADD THIS

            # Create HTML version with tracking
            html_body = f"""
            <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    {body.replace(chr(10), '<br>')}
                    {tracking_pixel}
                </body>
            </html>
            """

            self.logger.info(f"HTML body length: {len(html_body)}")  # ← ADD THIS

            # Setup SMTP connection
            connection = get_connection(
                host=smtp_config.host,
                port=smtp_config.port,
                username=smtp_config.username,
                password=smtp_config.password,
                use_tls=smtp_config.use_tls,
                use_ssl=False
            )

            # Create multipart email (plain text + HTML)
            email = EmailMultiAlternatives(
                subject=subject,
                body=body,
                from_email=smtp_config.username,
                to=[lead.email],
                connection=connection
            )
            email.attach_alternative(html_body, "text/html")
            email.send()

            # Update inbox usage counter
            self.inbox_usage[smtp_config.username] += 1

            return True

        except Exception as e:
            self.logger.error(f"Send failed to {lead.email}: {str(e)}")
            return False

    def process_lead(self, lead: VerifiedLead, smtp_config: SMTPConfig) -> bool:
        """
        Process single lead: generate email, send, update database.
        """
        # Generate personalized email
        subject, body = self.generate_personalized_email(lead)

        if not subject or not body:
            self.logger.error(f"✗ Skipped {lead.email} - generation failed")
            return False

        # Send email with tracking
        if self.send_email_with_tracking(subject, body, lead, smtp_config):
            # Update lead in database
            lead.sent = True
            lead.stage = 'first_touch'
            lead.date_sent = timezone.now()
            lead.email_provider_used = smtp_config.username
            lead.total_email_sent += 1
            lead.save()

            # Create outbound message record
            OutboundMessage.objects.create(
                lead=lead,
                subject_line=subject,
                body=body,
                stage='first_touch',
                sent=True,
                sent_at=timezone.now()
            )

            self.logger.info(f"✓ Sent to {lead.email} via {smtp_config.username}")
            return True

        return False

    def run_campaign(self, batch_size: int = 30, delay_range: Tuple[int, int] = (5, 10)) -> Dict[str, Any]:
        """
        Run outreach campaign with smart rotation and delays.

        Args:
            batch_size: Number of leads to process
            delay_range: (min, max) minutes to wait between sends

        Returns:
            Campaign metrics
        """
        start_time = datetime.now()
        self.logger.info("=" * 60)
        self.logger.info("STARTING OUTREACH CAMPAIGN")
        self.logger.info("=" * 60)

        # Fetch unsent leads
        leads = VerifiedLead.objects.filter(sent=False).order_by('-intent_score')[:batch_size]

        if not leads.exists():
            self.logger.warning("No unsent leads found")
            return self._build_metrics(0, 0, 0, start_time)

        self.logger.info(f"Processing {leads.count()} leads")

        successful = 0
        failed = 0

        for i, lead in enumerate(tqdm(leads, desc="Sending emails")):
            try:
                # Get next available inbox
                smtp_config = self.get_next_inbox()

                # Process lead
                if self.process_lead(lead, smtp_config):
                    successful += 1
                else:
                    failed += 1

                # Smart delay between sends (except last email)
                if (i + 1) % len(self.smtp_configs) == 0 and i < leads.count() - 1:
                    delay_minutes = random.uniform(delay_range[0], delay_range[1])
                    delay_seconds = int(delay_minutes * 60)

                    self.logger.info(
                        f"⏳ Full cycle complete. Waiting {delay_minutes:.1f} minutes before next rotation...")
                    time.sleep(delay_seconds)

            except Exception as e:
                self.logger.error(f"Error processing {lead.email}: {str(e)}")
                failed += 1

        return self._build_metrics(leads.count(), successful, failed, start_time)

    def _build_metrics(self, total: int, successful: int, failed: int, start_time: datetime) -> Dict[str, Any]:
        """Generate and log campaign metrics"""
        end_time = datetime.now()
        duration = end_time - start_time
        success_rate = (successful / total * 100) if total > 0 else 0

        metrics = {
            'total_processed': total,
            'successful_sends': successful,
            'failed_sends': failed,
            'success_rate': success_rate,
            'duration': str(duration),
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'inbox_usage': dict(self.inbox_usage)
        }

        # Log summary
        self.logger.info("=" * 60)
        self.logger.info("CAMPAIGN COMPLETED")
        self.logger.info("=" * 60)
        self.logger.info(f"Total Processed: {total}")
        self.logger.info(f"Successful: {successful} ({success_rate:.1f}%)")
        self.logger.info(f"Failed: {failed}")
        self.logger.info(f"Duration: {duration}")
        self.logger.info(f"\nInbox Usage:")
        for inbox, count in self.inbox_usage.items():
            self.logger.info(f"  {inbox}: {count} emails")

        return metrics


def load_smtp_configs() -> List[SMTPConfig]:
    """Load all SMTP configurations from environment"""
    load_dotenv()
    configs = []

    # Zoho accounts
    for i in range(1, 5):
        email = os.getenv(f"zoho_email_{i}" if i > 1 else "ZOHO_EMAIL")
        password = os.getenv(f"zoho_app_password_{i}" if i > 1 else "zoho_app_password")

        if email and password:
            configs.append(SMTPConfig(
                provider=f"zoho-{i}",
                host="smtp.zoho.com",
                port=587,
                use_tls=True,
                username=email,
                password=password,
                daily_limit=50
            ))

    # Gmail accounts
    gmail_email = os.getenv("GMAIL_EMAIL_2")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD_2")
    if gmail_email and gmail_password:
        configs.append(SMTPConfig(
            provider="gmail",
            host="smtp.gmail.com",
            port=587,
            use_tls=True,
            username=gmail_email,
            password=gmail_password,
            daily_limit=100
        ))

    if not configs:
        raise ValueError("No SMTP configs found in environment")

    return configs


def main():
    """Main execution"""
    try:
        # Load configs
        smtp_configs = load_smtp_configs()
        openai_api_key = os.getenv('OPENAI_API_KEY')
        tracking_domain = os.getenv('TRACKING_DOMAIN', 'https://yourdomain.com')

        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY not set")

        # Initialize engine
        engine = SmartOutreachEngine(
            openai_api_key=openai_api_key,
            smtp_configs=smtp_configs,
            tracking_domain=tracking_domain
        )

        # Run campaign
        metrics = engine.run_campaign(
            batch_size=30,
            delay_range=(5, 10)  # 5-10 minutes between sends
        )

        return metrics

    except Exception as e:
        logging.error(f"Campaign failed: {str(e)}")
        raise


if __name__ == "__main__":
    main()