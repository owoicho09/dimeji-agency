import os
import sys
import django
import random
import time
import json
from typing import Tuple, Optional

# ------------------------------------------
# Django Setup
# ------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from system.models import Lead, EmailTemplate, LeadEmailCopy
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ------------------------------------------
# Prompt Builder (JSON output)
# ------------------------------------------
def build_email_prompt(lead, template_content: str) -> str:
    return f"""
You are an expert B2B email copywriter.

Rules:
- Only write 2-3 sentences in the body.
- Do not include greetings or sign-offs.
- Do not repeat phrases from template.
- Be helpful, curious, and human.
- Output JSON ONLY. Do NOT add any text outside the JSON. Keys must be: "subject_line", "body" 
{{
  "subject_line": " ",
  "body": " "
}}

Template guidance (adapt per lead):
{template_content}

Lead info:
- Name: {lead.first_name} {lead.last_name}
- Company: {lead.company}
- Website: {lead.website}
- Title: {lead.title}
- Description: {lead.seo_description}
SUBJECT LINE GUIDANCE: - Make it catchy, intriguing, or curiosity-driven. - Include something personal about the lead or their company if possible. - Use different approaches each time: questions, numbers, insights, or bold statements. - Do NOT start every subject with 'Quick thought' or 'Quick check-in'. - Aim for 3-6 words maximum.
Output JSON ONLY with keys: subject, body. Example:
{{
  "subject_line": " ",
  "body": " "
}}
"""

# ------------------------------------------
# GPT JSON Parser
# ------------------------------------------
def parse_email_response(raw_output: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = json.loads(raw_output)
        subject = data.get("subject_line", "").strip()
        body = data.get("body", "").strip()
        if not subject or not body:
            return None, None
        return subject, body
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
        return None, None

# ------------------------------------------
# GPT Email Generator
# ------------------------------------------
def generate_personalized_email(
    lead,
    template_content: str,
    max_retries: int = 3
) -> Tuple[Optional[str], Optional[str]]:

    prompt = build_email_prompt(lead, template_content)

    for attempt in range(1, max_retries + 1):
        try:
            print(f"📤 GPT → {lead.first_name} {lead.last_name} (attempt {attempt})")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.85,
                max_tokens=250
            )
            raw = response.choices[0].message.content
            subject, body = parse_email_response(raw)
            if subject and body:
                print("✅ Email generated")
                return subject, body
            print("⚠️ Empty subject/body — retrying")
        except Exception as e:
            print(f"❌ GPT API error: {e}")
            time.sleep(2 ** attempt)
    return None, None

# ------------------------------------------
# Template Selector
# ------------------------------------------
def get_random_template() -> Optional[EmailTemplate]:
    templates = list(EmailTemplate.objects.all())
    if not templates:
        print("❌ No templates found in DB")
        return None
    template = random.choice(templates)
    print(f"🎨 Using template: {template.name}")
    return template

# ------------------------------------------
# Main Email Generation
# ------------------------------------------
def main(batch_size: int = 20):
    print("\n====================================================")
    print("🚀 HIGH-INTENT EMAIL GENERATION (JSON OUTPUT)")
    print("====================================================\n")

    leads = list(
        Lead.objects.filter(
            score=True,
            intent="MEDIUM",
            email_verified=True,
            ready_to_send=False
        ).order_by("id")[:batch_size]
    )
    if not leads:
        print("🎉 No HIGH-intent leads available.")
        return

    generated, skipped, failed = 0, 0, 0

    for lead in leads:
        print(f"→ Processing lead {lead.id} | {lead.company}")

        if LeadEmailCopy.objects.filter(lead=lead).exists():
            print("⚠️ Email already exists — skipping")
            lead.ready_to_send = True
            lead.save(update_fields=["ready_to_send"])
            skipped += 1
            continue

        template = get_random_template()
        if not template:
            failed += 1
            continue

        subject, body = generate_personalized_email(lead, template.prompt)
        if not subject or not body:
            print("❌ Generation failed")
            failed += 1
            continue

        LeadEmailCopy.objects.create(
            lead=lead,
            template_name=template.name,
            subject=subject,
            body=body,
            ready_to_send=True
        )
        lead.ready_to_send = True
        lead.save(update_fields=["ready_to_send"])
        generated += 1
        print("💾 Email saved\n")

    print("\n====================================================")
    print(f"✅ Generated: {generated} | ⚠️ Skipped: {skipped} | ❌ Failed: {failed}")
    print("====================================================\n")


if __name__ == "__main__":
    main(batch_size=20)
