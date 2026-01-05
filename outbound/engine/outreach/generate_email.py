from django.http import JsonResponse
from .models import Lead, EmailTemplate, LeadEmailCopy
import random

import re


def fill_placeholders(text, lead):
    """Replaces {{field}} placeholders dynamically using Lead model fields."""

    def replace(match):
        field_name = match.group(1)
        return str(getattr(lead, field_name, "") or "")

    return re.sub(r"{{\s*(.*?)\s*}}", replace, text)


def generate_email_copies(request):

    templates = list(EmailTemplate.objects.all())
    if not templates:
        return JsonResponse({"error": "No email templates found"}, status=400)

    # leads without email copies
    leads = list(
        Lead.objects.filter(score=True, ready_to_send=False, email_verified=True)[:batch_size]
    )
    if not leads:
        return JsonResponse({"message": "All leads already have email copies."})

    generated_count = 0

    for lead in leads:

        template = random.choice(templates)

        # Fill placeholders
        subject_filled = fill_placeholders(template.subject, lead)
        body_filled = fill_placeholders(template.body, lead)

        if LeadEmailCopy.objects.filter(lead=lead).exists():
            print(f"⚠️ Email already exists for {lead.first_name} {lead.last_name}. Skipping...")
            lead.ready_to_send = True
            lead.save()
            continue

        # Save generated email copy
        LeadEmailCopy.objects.create(
            lead=lead,
            subject=subject_filled,
            body=body_filled,
            template_used=template,
            ready_to_send=True

        )

        generated_count += 1

    return JsonResponse({
        "message": f"Generated {generated_count} outreach emails.",
        "status": "success"
    })
