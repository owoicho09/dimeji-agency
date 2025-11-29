"""
Lead Scoring Script - Production Version

This script processes unverified leads using OpenAI's GPT model to score them
based on fit and intent, then creates verified lead records.

Usage:
    python score_leads.py [--batch-size BATCH_SIZE] [--icp-id ICP_ID] [--dry-run]
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass

from django.db import transaction
from django.db.models import QuerySet
from django.core.exceptions import ValidationError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Django setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "genesis_engine.settings")

import django

django.setup()

from openai import OpenAI, OpenAIError
from outbound.models import Lead, VerifiedLead, ICP


# Configuration
@dataclass
class Config:
    """Configuration for the lead scoring process"""
    batch_size: int = 10
    icp_id: int = 1
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2000
    max_retries: int = 3
    timeout: int = 60


# Logging setup
def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure logging with both file and console handlers"""
    log_dir = os.path.join(PROJECT_ROOT, 'logs')
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = os.path.join(log_dir, f'lead_scoring_{timestamp}.log')

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )

    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized. Log file: {log_file}")
    return logger


logger = setup_logging()


class LeadScoringError(Exception):
    """Base exception for lead scoring errors"""
    pass


class GPTProcessingError(LeadScoringError):
    """Exception raised when GPT processing fails"""
    pass


class LeadScorer:
    """Main class for lead scoring operations"""

    def __init__(self, config: Config, dry_run: bool = False):
        self.config = config
        self.dry_run = dry_run
        self.client: Optional[OpenAI] = None
        self.icp: Optional[ICP] = None

        self._initialize_openai_client()

    def _initialize_openai_client(self) -> None:
        """Initialize OpenAI client with API key validation"""
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise LeadScoringError("OPENAI_API_KEY not found in environment variables")

        try:
            self.client = OpenAI(api_key=api_key, timeout=self.config.timeout)
            logger.info("OpenAI client initialized successfully")
        except Exception as e:
            raise LeadScoringError(f"Failed to initialize OpenAI client: {e}")

    def fetch_icp(self) -> ICP:
        """Fetch and validate ICP configuration"""
        try:
            icp = ICP.objects.get(id=self.config.icp_id)
            logger.info(f"Fetched ICP: ID={icp.id}, Name={icp.name}, Industry={icp.industry}")

            # Validate ICP has required fields
            if not all([icp.name, icp.industry]):
                raise LeadScoringError(f"ICP {icp.id} is missing required fields")

            self.icp = icp
            return icp

        except ICP.DoesNotExist:
            raise LeadScoringError(f"ICP with ID {self.config.icp_id} not found")
        except Exception as e:
            raise LeadScoringError(f"Error fetching ICP: {e}")

    def fetch_leads(self) -> QuerySet:
        """Fetch batch of unverified leads with email"""
        try:
            leads = Lead.objects.filter(
                verified=False,
                email__isnull=False
            ).exclude(
                email__exact=''
            ).order_by('created_at')[:self.config.batch_size]

            lead_count = len(leads)
            logger.info(f"Fetched {lead_count} unverified leads for processing")

            return leads

        except Exception as e:
            raise LeadScoringError(f"Error fetching leads: {e}")

    def generate_prompt(self, leads: List[Lead]) -> str:
        """Generate GPT prompt for lead scoring"""
        leads_payload = [
            {
                "name": lead.name or "N/A",
                "email": lead.email,
                "website": lead.website or "N/A",
                "source": lead.source or "unknown"
            }
            for lead in leads
        ]

        prompt = f"""You are an AI scoring assistant for B2B lead qualification.

For each lead provided, analyze and score them against the following Ideal Customer Profile (ICP):

**ICP Details:**
- Name: {self.icp.name}
- Industry: {self.icp.industry}
- Location: {self.icp.location or 'Not specified'}
- Description: {self.icp.description or 'Not specified'}

**Your Task:**
1. Assign a **fit_score** (0-10): How well does this lead match the ICP criteria?
   - Consider industry alignment, company size indicators, location relevance
   - 0 = No match, 10 = Perfect match

2. Assign an **intent_score** (0-10): What's the likelihood they're ready to buy?
   - Consider website quality, business indicators, email domain credibility
   - 0 = No intent, 10 = High buying intent

3. Create a **personalization_note**: A brief, specific note for outreach (1-2 sentences)
   - Reference something specific about their business
   - Keep it professional and relevant

**Important:** Return ONLY a valid JSON array with no additional text, markdown, or formatting.

**Required JSON Format:**
[
  {{
    "name": "Full Name",
    "email": "email@example.com",
    "website": "https://website.com",
    "source": "google_maps",
    "fit_score": 7,
    "intent_score": 6,
    "personalization_note": "Specific note about the lead."
  }}
]

**Leads to Evaluate:**
{json.dumps(leads_payload, indent=2)}

Remember: Return ONLY the JSON array, nothing else."""

        logger.debug(f"Generated prompt for {len(leads)} leads")
        return prompt

    def call_gpt(self, prompt: str, retry_count: int = 0) -> List[Dict]:
        """Call GPT API with retry logic"""
        try:
            logger.info(f"Calling GPT API (attempt {retry_count + 1}/{self.config.max_retries})")

            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a B2B lead qualification expert. Return only valid JSON arrays with no additional formatting."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                response_format={"type": "json_object"} if "gpt-4" in self.config.model else None
            )

            gpt_result = response.choices[0].message.content.strip()
            logger.debug(f"Raw GPT response: {gpt_result[:200]}...")

            # Parse and validate response
            parsed_data = self._parse_gpt_response(gpt_result)
            logger.info(f"Successfully parsed {len(parsed_data)} leads from GPT response")

            return parsed_data

        except OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")

            if retry_count < self.config.max_retries - 1:
                logger.info(f"Retrying... ({retry_count + 1}/{self.config.max_retries})")
                return self.call_gpt(prompt, retry_count + 1)
            else:
                raise GPTProcessingError(f"GPT API failed after {self.config.max_retries} attempts: {e}")

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse GPT response as JSON: {e}")
            raise GPTProcessingError(f"Invalid JSON response from GPT: {e}")

        except Exception as e:
            logger.error(f"Unexpected error calling GPT: {e}")
            raise GPTProcessingError(f"Unexpected error: {e}")

    def _parse_gpt_response(self, response: str) -> List[Dict]:
        """Parse and validate GPT response"""
        # Remove markdown code fences if present
        if response.startswith("```"):
            lines = response.splitlines()
            response = "\n".join(lines[1:-1] if len(lines) > 2 else lines)

        # Extract JSON array
        start = response.find("[")
        end = response.rfind("]") + 1

        if start == -1 or end == 0:
            raise json.JSONDecodeError("No JSON array found in response", response, 0)

        json_str = response[start:end]
        data = json.loads(json_str)

        # Validate structure
        if not isinstance(data, list):
            raise ValueError("GPT response is not a list")

        # Validate each lead record
        for idx, lead in enumerate(data):
            required_fields = ["name", "email", "fit_score", "intent_score", "personalization_note"]
            missing_fields = [f for f in required_fields if f not in lead]

            if missing_fields:
                logger.warning(f"Lead {idx} missing fields: {missing_fields}")

            # Validate scores
            for score_field in ["fit_score", "intent_score"]:
                if score_field in lead:
                    score = lead[score_field]
                    if not isinstance(score, (int, float)) or not (0 <= score <= 10):
                        logger.warning(f"Invalid {score_field} for lead {idx}: {score}")
                        lead[score_field] = max(0, min(10, int(score))) if isinstance(score, (int, float)) else 0

        return data

    def save_verified_leads(self, leads_data: List[Dict], raw_leads: List[Lead]) -> Tuple[int, int]:
        """Save verified leads to database"""
        success_count = 0
        error_count = 0

        if self.dry_run:
            logger.info("DRY RUN MODE - No database changes will be made")
            for lead_data in leads_data:
                logger.info(
                    f"Would save: {lead_data['name']} - Fit: {lead_data['fit_score']}, Intent: {lead_data['intent_score']}")
            return len(leads_data), 0

        with transaction.atomic():
            for lead_data, raw_lead in zip(leads_data, raw_leads):
                try:
                    verified_lead = VerifiedLead.objects.create(
                        name=lead_data.get("name", raw_lead.name),
                        email=lead_data["email"],
                        website=lead_data.get("website") or raw_lead.website,
                        source=lead_data.get("source") or raw_lead.source,
                        fit_score=lead_data.get("fit_score", 0),
                        intent_score=lead_data.get("intent_score", 0),
                        personalization_note=lead_data.get("personalization_note", ""),
                    )

                    raw_lead.verified = True
                    raw_lead.save()

                    success_count += 1
                    logger.info(
                        f"Saved verified lead: {verified_lead.name} ({verified_lead.email}) - "
                        f"Fit: {verified_lead.fit_score}, Intent: {verified_lead.intent_score}"
                    )

                except ValidationError as e:
                    error_count += 1
                    logger.error(f"Validation error saving lead {lead_data.get('email')}: {e}")

                except Exception as e:
                    error_count += 1
                    logger.error(f"Error saving lead {lead_data.get('email')}: {e}")

        return success_count, error_count

    def process_batch(self) -> Dict[str, int]:
        """Main processing pipeline"""
        stats = {
            "total_processed": 0,
            "successful": 0,
            "failed": 0
        }

        try:
            # Fetch ICP
            self.fetch_icp()

            # Fetch leads
            raw_leads = self.fetch_leads()

            if not raw_leads:
                logger.info("No unverified leads found to process")
                return stats

            stats["total_processed"] = len(raw_leads)

            # Generate prompt and call GPT
            prompt = self.generate_prompt(raw_leads)
            verified_leads_data = self.call_gpt(prompt)

            # Validate data count matches
            if len(verified_leads_data) != len(raw_leads):
                logger.warning(
                    f"Mismatch: GPT returned {len(verified_leads_data)} leads "
                    f"but we sent {len(raw_leads)} leads"
                )

            # Save to database
            success_count, error_count = self.save_verified_leads(verified_leads_data, raw_leads)

            stats["successful"] = success_count
            stats["failed"] = error_count

        except LeadScoringError as e:
            logger.error(f"Lead scoring error: {e}")
            stats["failed"] = stats["total_processed"]

        except Exception as e:
            logger.exception(f"Unexpected error in batch processing: {e}")
            stats["failed"] = stats["total_processed"]

        return stats


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Process and score leads using GPT",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        '--batch-size',
        type=int,
        default=10,
        help='Number of leads to process in one batch'
    )

    parser.add_argument(
        '--icp-id',
        type=int,
        default=1,
        help='ID of the ICP to use for scoring'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Run without making database changes'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level'
    )

    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()

    # Update logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    logger.info("=" * 60)
    logger.info("Lead Scoring Script Started")
    logger.info(f"Batch Size: {args.batch_size}")
    logger.info(f"ICP ID: {args.icp_id}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info("=" * 60)

    try:
        # Create configuration
        config = Config(
            batch_size=args.batch_size,
            icp_id=args.icp_id
        )

        # Initialize scorer
        scorer = LeadScorer(config, dry_run=args.dry_run)

        # Process batch
        stats = scorer.process_batch()

        # Log results
        logger.info("=" * 60)
        logger.info("Lead Scoring Script Finished")
        logger.info(f"Total Processed: {stats['total_processed']}")
        logger.info(f"Successful: {stats['successful']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info("=" * 60)

        # Exit with appropriate code
        sys.exit(0 if stats['failed'] == 0 else 1)

    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()