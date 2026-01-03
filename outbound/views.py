from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from outbound.models import *
import logging
import json
from datetime import datetime

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt




logger = logging.getLogger(__name__)


def home(request):
    return HttpResponse("Genesis Engine running 🚀")


@csrf_exempt
def track_email_open(request, lead_id):
    """
    Tracking pixel endpoint - records when lead opens email.
    Returns a transparent 1x1 GIF.
    """
    try:
        # Find the lead by lead_id
        lead = VerifiedLead.objects.get(lead_id=lead_id)

        # Only update if not already marked as opened (track first open only)
        if not lead.opened:
            lead.opened = True
            lead.opened_date = timezone.now()
            lead.save()

            logger.info(f"✓ Email opened by {lead.email} ({lead.name})")

    except VerifiedLead.DoesNotExist:
        logger.warning(f"Tracking attempt for non-existent lead_id: {lead_id}")
    except Exception as e:
        logger.error(f"Tracking error for lead_id {lead_id}: {str(e)}")

    # Return a transparent 1x1 pixel GIF (even if tracking fails)
    # This prevents broken image icons in emails
    transparent_gif = (
        b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
        b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00'
        b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
        b'\x44\x01\x00\x3b'
    )

    return HttpResponse(transparent_gif, content_type='image/gif')



@csrf_exempt
@require_http_methods(["POST"])
def create_lead(request):
    print("🔵 /api/lead hit")
    print("Method:", request.method)
    print("Headers:", dict(request.headers))
    print("Raw body bytes:", request.body)

    try:
        # Parse JSON
        data = json.loads(request.body.decode("utf-8"))
        print("Parsed JSON:", data)

        company = data.get("company", "").strip()
        email = data.get("email", "").strip()
        description = data.get("description", "").strip()
        offer_expires = data.get("offer_expires")
        print("company:", company)
        print("email:", email)
        print("description:", description)
        print("offer_expires:", offer_expires)

        if not company:
            return JsonResponse({"error": "Company name is required"}, status=400)
        if not email:
            return JsonResponse({"error": "Email is required"}, status=400)

        offer_expires_date = None
        print("✅ Creating Lead in DB...")
        lead = WebsiteLead.objects.create(
            company_name=company,
            email=email,
            description=description,
        )
        print("✅ Lead created with ID:", lead.id)

        return JsonResponse(
            {
                "message": "Lead created",
                "id": lead.id,
            },
            status=201,
        )

    except Exception as e:
        import traceback
        print("🔥 EXCEPTION in create_lead:", e)
        traceback.print_exc()

        # Return full details in dev so your frontend .text() shows it
        return JsonResponse(
            {
                "error": "Server error",
                "detail": str(e),
                "traceback": traceback.format_exc(),
            },
            status=500,
        )
