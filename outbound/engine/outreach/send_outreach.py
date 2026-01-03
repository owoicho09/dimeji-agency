import os
import sys
import time
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
from system.models import Lead, LeadEmailCopy

# ----------------------------
EMAILS_PER_RUN = 10       # number of emails to send per run
DELAY_BETWEEN_EMAILS = 60 # seconds between emails to avoid spam triggers
# ----------------------------

@shared_task
def send_rotating_outreach_batch():
    print("="*60)
    print("🚀 Starting outreach batch run…")
    print("="*60)

    leads_to_send = LeadEmailCopy.objects.filter(
        ready_to_send=True,
        sent=False,
        lead__ready_to_send=True,
        lead__email_sent=False
    ).select_related("lead")[:EMAILS_PER_RUN]  # limit per run

    if not leads_to_send:
        print("No leads ready to send.")
        return "No leads"

    print(f"Found {len(leads_to_send)} leads ready.")

    for i, copy in enumerate(leads_to_send):
        lead = copy.lead
        print("-"*50)
        print(f"Processing lead #{i+1}: {lead.email}")

        subject = copy.subject
        body = copy.body

        # Rotate SMTP account internally
        sender_used, success = smtp_client.send_email(
            subject=subject,
            body=body,
            to_email=lead.email
        )

        # Send test email on each iteration
        smtp_client.send_email(
            subject="Test Email — Outreach System Health Check",
            body=f"Test OK from {sender_used}",
            to_email="michaelogaje033@gmail.com"
        )

        if success:
            print(f"✔ Email sent successfully from {sender_used} to {lead.email}")

            copy.sent = True
            copy.sent_at = timezone.now()
            copy.save()

            lead.email_sent = True
            lead.email_provider_used = sender_used
            lead.last_contacted = timezone.now()
            lead.save()
        else:
            print(f"❌ Failed sending to {lead.email}")
            lead.email_status = "send_failed"
            lead.save()

        print(f"⏳ Waiting {DELAY_BETWEEN_EMAILS}s before next email...")
        time.sleep(DELAY_BETWEEN_EMAILS)

    print("✅ Batch completed.")
    return "Batch done"


if __name__ == "__main__":
    print("Calling outreach task manually...")
    send_rotating_outreach_batch()
