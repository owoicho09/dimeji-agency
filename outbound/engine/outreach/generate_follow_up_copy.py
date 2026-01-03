import os
import sys
import django
import random
import time
import json
from typing import Tuple, Optional, List
from datetime import timedelta
from django.utils import timezone
from django.db.models import Prefetch

# -------------------------
# Django setup
# -------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from system.models import Lead, LeadEmailCopy, FollowUp, EmailTemplate
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------
# Configuration
# -------------------------
FOLLOWUP_CADENCE = {1: 32, 2: 72, 3: 120}
MAX_GPT_RETRIES = 3
BATCH_SIZE = 50
GPT_MODEL = "gpt-4o-mini"
GPT_TEMPERATURE = 0.85
GPT_MAX_TOKENS = 300

# -------------------------
# Helper: Get Previous Email Context
# -------------------------
def get_email_history(lead: Lead, parent_email: LeadEmailCopy) -> List[dict]:
    print(f"📜 Fetching email history for lead: {lead.email}")
    history = []

    if parent_email:
        print(f"  → Adding initial email: {parent_email.subject}")
        history.append({
            "type": "initial",
            "subject": parent_email.subject,
            "body": parent_email.body,
            "sent_at": parent_email.sent_at
        })

    previous_followups = FollowUp.objects.filter(
        lead=lead, status__in=["sent", "ready"]
    ).order_by("followup_number")

    for fu in previous_followups:
        print(f"  → Adding previous follow-up #{fu.followup_number}: {fu.email_subject}")
        history.append({
            "type": f"follow_up_{fu.followup_number}",
            "subject": fu.email_subject,
            "body": fu.email_body,
            "sent_at": fu.sent_at or fu.scheduled_at
        })

    print(f"  → Total emails in history: {len(history)}")
    return history

# -------------------------
# GPT Prompt Builder (JSON output)
# -------------------------
def build_followup_prompt(
        lead: Lead,
        template_content: str,
        followup_number: int,
        email_history: List[dict]
) -> str:
    print(f"📝 Building GPT prompt for follow-up #{followup_number} for {lead.email}")
    stage_context = {
        1: "FIRST follow-up (32 hours after initial email). Different angle, brief and curious, reference company/website.",
        2: "SECOND follow-up (72 hours after first follow-up). Different approach, thoughtful question, genuine interest.",
        3: "FINAL follow-up (120 hours after second follow-up). Last gentle touchpoint, acknowledge previous outreach, easy out."
    }

    history_text = "\n".join(
        [f"{idx+1}. [{email['type']}] Subject: {email['subject']} | Body: {email['body']}"
         for idx, email in enumerate(email_history)]
    ) or "No previous emails."

    prompt = f"""
You are an expert B2B email copywriter.

Rules:
- Casual, human, 2-3 sentences max.
- Each follow-up must be distinct and fresh.
- Soft, non-pushy CTAs.
- Do NOT repeat previous email angles or phrasing.
- Output JSON ONLY. Do NOT add any text outside the JSON. Keys must be: "subject_line", "body" 
{{
  "subject_line": " ",
  "body": " "
}}

Follow-up stage info:
{stage_context[followup_number]}

Template guidance (adapt, don't copy):
{template_content}

Lead info:
- Name: {lead.first_name} {lead.last_name}
- Company: {lead.company}
- Website: {lead.website}
- Title: {lead.title}
- Description: {lead.seo_description}

Previous emails:
{history_text}

SUBJECT LINE GUIDANCE: - Make it catchy, intriguing, or curiosity-driven. - Include something personal about the lead or their company if possible. - Use different approaches each time: questions, numbers, insights, or bold statements. - Do NOT start every subject with 'Quick thought' or 'Quick check-in'. - Aim for 3-6 words maximum.

Output ONLY JSON with keys "subject_line" and "body":
{{
  "subject_line": " ",
  "body": " "
}}
No greetings or signatures, just the core message.
"""
    print(f"  → Prompt built (length {len(prompt)} characters)")
    return prompt

# -------------------------
# GPT JSON Parser
# -------------------------
def parse_email_response(raw_output: str) -> Tuple[Optional[str], Optional[str]]:
    print(f"💬 Parsing GPT response...")
    print(f"  → Raw output: {raw_output[:200]}...")  # truncate for readability
    try:
        data = json.loads(raw_output)
        subject = data.get("subject_line", "").strip()
        body = data.get("body", "").strip()
        if not subject or not body:
            print("  ❌ JSON parse: subject or body missing")
            return None, None
        print(f"  → Parsed subject: {subject}")
        print(f"  → Parsed body: {body[:60]}...")
        return subject, body
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
        return None, None

# -------------------------
# Generate Follow-Up Email
# -------------------------
def generate_followup_email(
        lead: Lead,
        parent_email: LeadEmailCopy,
        template_content: str,
        followup_number: int
) -> Tuple[Optional[str], Optional[str]]:
    email_history = get_email_history(lead, parent_email)
    prompt = build_followup_prompt(lead, template_content, followup_number, email_history)

    for attempt in range(MAX_GPT_RETRIES):
        print(f"  → GPT attempt {attempt+1}/{MAX_GPT_RETRIES}")
        try:
            response = client.chat.completions.create(
                model=GPT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=GPT_TEMPERATURE,
                max_tokens=GPT_MAX_TOKENS
            )
            raw = response.choices[0].message.content
            print(f"    → GPT raw response received (length {len(raw)})")
            subject, body = parse_email_response(raw)
            if subject and body:
                print(f"    ✅ GPT returned valid email")
                return subject, body
            else:
                print(f"    ⚠️ GPT parse failed, retrying...")
        except Exception as e:
            print(f"    ❌ GPT API error: {e}, retrying...")
            time.sleep(2 ** attempt)
    return None, None

# -------------------------
# Find Leads Ready for Follow-Up
# -------------------------
def get_leads_due_for_followup(followup_number: int, batch_size: int) -> List[tuple]:
    print(f"🔎 Fetching leads due for follow-up #{followup_number}")
    now = timezone.now()
    cutoff_time = now - timedelta(hours=FOLLOWUP_CADENCE[followup_number])
    leads_due = []

    if followup_number == 1:
        lead_emails = LeadEmailCopy.objects.filter(
            sent=True,
            sent_at__lte=cutoff_time,
            lead__email_verified=True,
        ).exclude(
            followup_emails__followup_number=1
        ).select_related('lead').prefetch_related(
            Prefetch('followup_emails', queryset=FollowUp.objects.all())
        )[:batch_size]

        for le in lead_emails:
            leads_due.append((le.lead, le))
        print(f"  → Found {len(lead_emails)} lead emails for follow-up #1")
    else:
        prev_num = followup_number - 1
        prev_followups = FollowUp.objects.filter(
            followup_number=prev_num,
            status='sent',
            sent_at__lte=cutoff_time,
            lead__email_verified=True
        ).exclude(
            lead__followups__followup_number=followup_number
        ).select_related('lead', 'parent_email')[:batch_size]

        for fu in prev_followups:
            leads_due.append((fu.lead, fu.parent_email))
        print(f"  → Found {len(prev_followups)} previous follow-ups for follow-up #{followup_number}")

    return leads_due

# -------------------------
# Main Execution
# -------------------------
def main(batch_size: int = BATCH_SIZE, dry_run: bool = False):
    now = timezone.now()
    total_created = 0

    print(f"\n{'='*60}")
    print(f"🚀 Starting Follow-Up Generation Run")
    print(f"{'='*60}")
    print(f"Timestamp: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Batch Size: {batch_size}\n")

    templates = list(EmailTemplate.objects.all())
    print(f"📝 Found {len(templates)} template(s)")
    if not templates:
        print("❌ No templates found")
        return

    for followup_number in sorted(FOLLOWUP_CADENCE.keys()):
        hours = FOLLOWUP_CADENCE[followup_number]
        print(f"\n{'─'*60}\n📧 Processing Follow-Up #{followup_number} (after {hours}h)\n{'─'*60}")

        leads_due = get_leads_due_for_followup(followup_number, batch_size)
        if not leads_due:
            print(f"✓ No leads due for follow-up #{followup_number}")
            continue

        print(f"Found {len(leads_due)} lead(s) ready for follow-up #{followup_number}")

        for idx, (lead, parent_email) in enumerate(leads_due, 1):
            print(f"\n  [{idx}/{len(leads_due)}] Processing: {lead.email} ({lead.company})")

            if dry_run:
                print(f"    → [DRY RUN] Would generate follow-up #{followup_number}")
                continue

            template = random.choice(templates)
            print(f"    → Selected template: {template.name}")
            print(f"    → Generating content with GPT...")
            subject, body = generate_followup_email(
                lead,
                parent_email,
                template.prompt,
                followup_number
            )

            if not subject or not body:
                print(f"    ❌ Failed to generate content for {lead.email}")
                continue

            try:
                FollowUp.objects.create(
                    lead=lead,
                    parent_email=parent_email,
                    template_type="follow_up",
                    followup_number=followup_number,
                    template=template,
                    email_subject=subject,
                    email_body=body,
                    scheduled_at=now,
                    ready_for_followup=True,
                    status="ready"
                )
                print(f"    ✅ Created follow-up #{followup_number}")
                print(f"       Subject: {subject[:60]}...")
                total_created += 1
            except Exception as e:
                print(f"    ❌ DB error: {e}")
                continue

    print(f"\n{'='*60}")
    print(f"✅ Follow-Up Generation Complete | Total created: {total_created}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate follow-up emails")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(batch_size=args.batch_size, dry_run=args.dry_run)
