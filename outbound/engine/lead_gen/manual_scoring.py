import os
import sys
import django
from time import sleep
from collections import defaultdict
from django.db import transaction

# ------------------------------------------
# Django Setup
# ------------------------------------------
print("🔧 Initializing Django environment...")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

django.setup()
print("✅ Django ready.\n")

from system.models import Lead

# ------------------------------------------
# ICP PARAMETERS
# ------------------------------------------

TARGET_TITLES = [
    "founder", "co-founder", "owner",
    "managing partner", "principal",
    "partner", "ceo",
]

STRONG_KEYWORDS = [
    "marketing agency",
    "digital marketing agency",
    "creative agency",
    "branding agency",
    "seo agency",
    "paid ads agency",
    "lead generation agency",
    "b2b marketing agency",
    "growth agency",
    "consulting firm",
    "marketing consultancy",
]

MEDIUM_KEYWORDS = [
    "marketing",
    "advertising",
    "branding",
    "seo",
    "paid ads",
    "content marketing",
    "email marketing",
    "growth marketing",
    "client acquisition",
    "demand generation",
    "b2b",
    "consulting",
    "agency",
]

NEGATIVE_KEYWORDS = [
    "ecommerce", "shopify", "amazon", "dropshipping",
    "retail", "restaurant",
    "church", "ministry", "non-profit", "ngo",
    "school", "college", "university",
    "manufacturing", "wholesale",
    "real estate", "brokerage",
    "crypto", "nft", "token",
]

# ------------------------------------------
# Reset stuck leads
# ------------------------------------------
def reset_stuck_leads():
    count = Lead.objects.filter(processing=True).update(processing=False)
    print(f"🔄 Reset {count} stuck leads\n")

# ------------------------------------------
# Scoring + Intent Logic
# ------------------------------------------
def score_and_classify(lead):
    # ----- HARD GATES -----
    if not lead.employees or not (2 <= lead.employees <= 25):
        return False, "REJECTED", "Team size outside 2–25"

    if not lead.title or not any(t in lead.title.lower() for t in TARGET_TITLES):
        return False, "REJECTED", "Title not revenue-owning"

    if not lead.website and not lead.seo_description:
        return False, "REJECTED", "No website or description"

    text = " ".join(filter(None, [
        lead.company,
        lead.keywords,
        lead.seo_description,
    ])).lower()

    for bad in NEGATIVE_KEYWORDS:
        if bad in text:
            return False, "REJECTED", f"Negative signal: {bad}"

    # ----- POSITIVE SIGNALS -----
    strong_hits = [kw for kw in STRONG_KEYWORDS if kw in text]
    medium_hits = [kw for kw in MEDIUM_KEYWORDS if kw in text]

    if strong_hits:
        intent = "HIGH"
        reason = f"Strong intent: {', '.join(strong_hits[:2])}"
        return True, intent, reason

    if len(medium_hits) >= 2:
        intent = "MEDIUM"
        reason = f"Service signals: {', '.join(medium_hits[:3])}"
        return True, intent, reason

    return False, "LOW", "Weak service intent"

# ------------------------------------------
# Main Reprocessing Loop
# ------------------------------------------
def main(batch_size=100, sleep_sec=2):
    print("🚀 Starting FULL ICP reprocessing with intent segmentation...\n")
    reset_stuck_leads()

    total_leads = Lead.objects.count()
    processed = 0

    stats = defaultdict(int)

    last_id = 0
    print(f"📊 Total leads in database: {total_leads}\n")

    while True:
        leads = list(
            Lead.objects
            .filter(id__gt=last_id)
            .order_by("id")[:batch_size]
        )

        if not leads:
            break

        for lead in leads:
            last_id = lead.id

            try:
                with transaction.atomic():
                    locked = Lead.objects.select_for_update().get(id=lead.id)
                    if locked.processing:
                        continue
                    locked.processing = True
                    locked.save(update_fields=["processing"])

                icp, intent, reason = score_and_classify(lead)

                with transaction.atomic():
                    update = Lead.objects.select_for_update().get(id=lead.id)
                    update.score = icp
                    update.intent = intent
                    update.score_reason = reason
                    update.processing = False
                    update.save(
                        update_fields=["score", "intent", "score_reason", "processing"]
                    )

                processed += 1
                stats[intent] += 1

                print(
                    f"💾 [{processed}/{total_leads}] "
                    f"Lead {lead.id} | ICP={icp} | Intent={intent}"
                )

            except Exception as e:
                print(f"❌ Error on lead {lead.id}: {e}")
                Lead.objects.filter(id=lead.id).update(processing=False)

        sleep(sleep_sec)

    # ------------------------------------------
    # Final Report
    # ------------------------------------------
    print("\n" + "=" * 70)
    print("📈 ICP REPROCESSING SUMMARY")
    print("=" * 70)
    print(f"Total leads processed: {processed}")
    print(f"ICP MATCHED: {stats['HIGH'] + stats['MEDIUM']}")
    print(f"  ├─ HIGH intent:   {stats['HIGH']}")
    print(f"  ├─ MEDIUM intent: {stats['MEDIUM']}")
    print(f"NON-ICP / REJECTED: {stats['REJECTED'] + stats['LOW']}")
    print(f"  ├─ LOW intent:    {stats['LOW']}")
    print(f"  └─ REJECTED:      {stats['REJECTED']}")
    print("=" * 70)
    print("✅ Reprocessing complete. System ready for segmented outreach.\n")

# ------------------------------------------
# Entry
# ------------------------------------------
if __name__ == "__main__":
    main(batch_size=100, sleep_sec=2)
