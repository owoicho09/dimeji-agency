import os
import sys
import time
import random
from celery import shared_task
from django.utils import timezone
import django

print("🔧 Setting up Django environment...")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
sys.path.insert(0, PROJECT_ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

django.setup()
print("✅ Django setup complete.")

from system.agent.outreach.email_client import smtp_client

# ----------------------------
EMAILS_PER_RUN = 30       # emails to send per run
DELAY_BETWEEN_EMAILS = 1 # seconds
# ----------------------------

# Warmup inboxes



WARMUP_INBOXES = [
    "julia.mcgregus@smartemailers.com",
    "marion@reputationwarmup.com",
    "siobhan@reachsecret.com",
    "vincent.vanhoot@outreachrs.com",
    "maeva.bonnet@landininbox.com",
    "thomas@inboxdoctors.com",
    "samuel.moore@deliverabble.com",
    "sholto@emailreach.co",
    "klaus@teamtreet.com",
    "elie.djemoun@dopetaste.com",
    "lucas@outboundancy.com",
    "scarlett.burton@reeverflow.com",
    "felipe.hernandez.p@leadsflowtrain.com",
    "josh@mailreech.com",
    "louis.thornton@reevercorp.com",
    "leah@akunaoutreach.com",
    "rita.johnson2r@gmail.com",
    "steven.lester.925@gmail.com",
    "tom.maupard778@gmail.com",
    "debbie.bakos567@gmail.com",
    "pete.jenkins9422@gmail.com",
    "rob.thomson238@gmail.com",
    "marisa.fernandes5192@hotmail.com",
    "abhishek.baska6252@hotmail.com",
    "nick.downey.997@hotmail.com",
    "emma.pasano62@outlook.com",
    "laura.dufreisne75013@outlook.com",
    "eva.schokker43@outlook.com",
    "oliver.yikes43@yahoo.com",
    "an.chamberlain44@yahoo.com",
]


# Randomized subjects/bodies for warmup
SUBJECTS = [
    "Quick inbox test",
    "Warmup message",
    "Checking email",
    "Test email — ignore",
]

BODIES = [
    "Hey, just testing email delivery. Please ignore. mlrch-6e5679b4ab7182",
    "Warmup message. You can reply if you want. mlrch-6e5679b4ab7182",
    "Testing inbox deliverability. Thanks mlrch-6e5679b4ab7182",
]

# ----------------------------
@shared_task
def run_warmup_batch():
    print("="*60)
    print("🔥 Starting inbox warmup batch…")
    print("="*60)

    inbox_pool = WARMUP_INBOXES.copy()
    random.shuffle(inbox_pool)  # randomize inbox order

    for i in range(EMAILS_PER_RUN):
        to_email = inbox_pool[i % len(inbox_pool)]  # cycle if run > inbox count

        subject = random.choice(SUBJECTS)
        body = random.choice(BODIES)

        sender_used, success = smtp_client.send_email(
            subject=subject,
            body=body,
            to_email=to_email
        )

        if success:
            print(f"✔ Warmup email sent from {sender_used} → {to_email}")
        else:
            print(f"❌ Failed warmup email from {sender_used} → {to_email}")

        print(f"⏳ Waiting {DELAY_BETWEEN_EMAILS}s before next email…")
        time.sleep(DELAY_BETWEEN_EMAILS)

    print("✅ Warmup batch completed.")
    return "Batch done"


if __name__ == "__main__":
    print("Calling warmup task manually…")
    run_warmup_batch()
