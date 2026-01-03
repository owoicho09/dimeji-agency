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
from system.models import Lead, FollowUp

# ----------------------------
EMAILS_PER_RUN = 10       # number of follow-ups to send per run
DELAY_BETWEEN_EMAILS = 60 # seconds between emails to avoid spam triggers
# ----------------------------

@shared_task
def send_followup_batch():
    print("="*60)
    print("🚀 Starting follow-up batch run…")
    print("="*60)

    followups_to_send = FollowUp.objects.filter(
        ready_for_followup=True,
        status='ready',
        lead__email_verified=True
    ).select_related("lead")[:EMAILS_PER_RUN]

    if not followups_to_send:
        print("No follow-ups ready to send.")
        return "No follow-ups"

    print(f"Found {len(followups_to_send)} follow-ups ready.")

    for i, followup in enumerate(followups_to_send):
        lead = followup.lead
        print("-"*50)
        print(f"Processing follow-up #{i+1}: {lead.email}")

        subject = followup.email_subject
        body = followup.email_body

        # Rotate SMTP account internally
        sender_used, success = smtp_client.send_email(
            subject=subject,
            body=body,
            to_email=lead.email
        )

        if success:
            print(f"✔ Follow-up sent successfully from {sender_used} to {lead.email}")

            # Mark follow-up as sent
            followup.status = 'sent'
            followup.sent_at = timezone.now()
            followup.save()

            # Update lead tracking
            lead.followup_sent = True
            lead.last_contacted = timezone.now()
            lead.email_provider_used = sender_used
            lead.save()
        else:
            print(f"❌ Failed sending follow-up to {lead.email}")
            lead.email_status = "followup_failed"
            lead.save()

        print(f"⏳ Waiting {DELAY_BETWEEN_EMAILS}s before next follow-up...")
        time.sleep(DELAY_BETWEEN_EMAILS)

    print("✅ Follow-up batch completed.")
    return "Follow-up batch done"


if __name__ == "__main__":
    print("Calling follow-up task manually...")
    send_followup_batch()
