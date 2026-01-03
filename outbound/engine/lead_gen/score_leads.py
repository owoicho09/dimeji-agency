import os
import sys
import django
import re
import json
from time import sleep
from django.db import transaction

# ------------------------------------------
# Django Setup
# ------------------------------------------
print("🔧 Setting up Django environment...")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

django.setup()
print("✅ Django setup complete.")

from system.models import Lead  # Adjust if your app name differs
from openai import OpenAI  # Using OpenAI / Genesis API

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ------------------------------------------
# ICP Prompt
# ------------------------------------------
ICP_PROMPT = """
You are an expert ICP evaluator for small marketing/growth/SEO agencies. Your task is to evaluate leads and decide if they are PERFECT ICP (~95% confidence) based on:

- Small agencies (1–20 employees)
- Solo/small teams
- Likely to benefit from automated lead gen
- Decision makers (owner/founder/CEO/co-founder)

Use ONLY these fields: keywords, SEO description, employee count.
Rules:
1. Use semantic reasoning. Don't rely only on keywords.
2. High confidence only. If unsure, return false.
3. Reject large teams, VC-funded, competitors, non-businesses, hobbyists, influencers, abstract services.
4. No hallucinations. Base judgement strictly on provided data.

Respond ONLY with a JSON array. Each object must contain:
{
    "icp": true|false,
    "reason": "Brief evidence from keywords, description, or employees (max 20 words)"
}
Do NOT include code blocks, markdown, explanations, or ellipses.
"""

# ------------------------------------------
# Utility to split list into batches
# ------------------------------------------
def batch_iterable(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]

# ------------------------------------------
# Function to score a batch of leads
# ------------------------------------------
def score_batch(leads):
    print(f"\n🔥 Scoring batch of {len(leads)} leads")

    combined_input = ICP_PROMPT + "\n\nLEADS:\n"
    for i, lead in enumerate(leads):
        lead_info = {
            "name": f"{lead.first_name} {lead.last_name}",
            "title": lead.title,
            "keywords": lead.keywords,
            "seo_description": lead.seo_description,
            "employees": lead.employees
        }
        combined_input += f"\nLead {i+1}: {json.dumps(lead_info)}"

    print("📤 Sending batch to GPT for scoring...")

    try:
        response = client.responses.create(
            model="gpt-4.1",
            input=combined_input,
            max_output_tokens=600
        )
        output = response.output_text
        print("RAW GPT OUTPUT (first 1000 chars):\n", output[:1000], "...")

        # Clean GPT output
        output_clean = output.strip()
        if output_clean.startswith("```"):
            output_clean = "\n".join(output_clean.split("\n")[1:])
        if output_clean.endswith("```"):
            output_clean = "\n".join(output_clean.split("\n")[:-1])
        output_clean = output_clean.strip()
        print("📌 Cleaned GPT output (first 500 chars):\n", output_clean[:500], "...")

        # Try direct JSON load
        try:
            results = json.loads(output_clean)
            print("✅ JSON parsed successfully.")
            return results
        except Exception as e:
            print("⚠️ Direct JSON parse failed:", e)
            match = re.search(r'\[.*\]', output_clean, re.DOTALL)
            if match:
                results = json.loads(match.group(0))
                print("✅ JSON parsed after fallback.")
                return results
            else:
                print("❌ No JSON array found. Skipping batch.")
                return []

    except Exception as e:
        print("❌ GPT API call failed:", e)
        return []

# ------------------------------------------
# Main scoring loop
# ------------------------------------------
def main(batch_size=10, sleep_sec=2):
    print("🚀 Starting ICP scoring process...")

    while True:
        # Use processing flag to avoid re-fetching same leads
        leads = list(Lead.objects.filter(score=False, processing=False)[:batch_size])
        if not leads:
            print("🎉 No more leads to score. Exiting.")
            break

        print(f"\n📦 Fetching {len(leads)} leads for scoring...")

        # Mark leads as processing
        with transaction.atomic():
            for lead in leads:
                lead.processing = True
                lead.save()

        results = score_batch(leads)

        if not results or len(results) != len(leads):
            print("⚠️ GPT results mismatch. Resetting processing flag and skipping batch.")
            with transaction.atomic():
                for lead in leads:
                    lead.processing = False
                    lead.save()
            sleep(sleep_sec)
            continue

        # Update DB with scoring
        with transaction.atomic():
            print("💾 Updating leads in DB with scoring results...")
            for lead, res in zip(leads, results):
                lead.score = res.get("icp", False)
                lead.score_reason = res.get("reason", "")
                lead.processing = False
                lead.save()
                print(f"   ➤ {lead.first_name} {lead.last_name} | ICP={lead.score} | Reason: {lead.score_reason}")

        print(f"✅ Batch of {len(leads)} leads scored and updated.")
        sleep(sleep_sec)

if __name__ == "__main__":
    main(batch_size=20, sleep_sec=3)
