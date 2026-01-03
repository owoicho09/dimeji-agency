from django.db import models
from shortuuid.django_fields import ShortUUIDField

# Create your models here.


from django.db import models

class ICP(models.Model):
    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Lead(models.Model):
    INTENT_CHOICES = [
        ("HIGH", "High Intent (Agency / Consultancy)"),
        ("MEDIUM", "Medium Intent (Service Business)"),
        ("LOW", "Low Intent (Weak Fit)"),
        ("REJECTED", "Rejected / Non-ICP"),
    ]
    # raw data from CSV
    first_name = models.CharField(max_length=255, null=True, blank=True)
    last_name = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    company = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    email_status = models.CharField(max_length=255, null=True, blank=True)
    seniority = models.CharField(max_length=255, null=True, blank=True)
    departments = models.CharField(max_length=255, null=True, blank=True)
    employees = models.IntegerField(null=True, blank=True)
    industry = models.CharField(max_length=255, null=True, blank=True)
    keywords = models.TextField(null=True, blank=True)
    person_linkedin = models.URLField(null=True, blank=True)
    company_linkedin = models.URLField(null=True, blank=True)
    website = models.URLField(null=True, blank=True)
    country = models.CharField(max_length=255, null=True, blank=True)
    technologies = models.TextField(null=True, blank=True)
    seo_description = models.TextField(null=True, blank=True)

    # scoring
    score = models.BooleanField(default=False)
    score_reason = models.TextField(null=True, blank=True)
    email_sent = models.BooleanField(default=False)
    followup_sent = models.BooleanField(default=False)
    email_provider_used = models.CharField(max_length=50, null=True, blank=True)
    processing = models.BooleanField(default=False)
    ready_to_send = models.BooleanField(default=False)

    email_verified = models.BooleanField(default=False)
    intent = models.CharField(
        max_length=10,
        choices=INTENT_CHOICES,
        default="REJECTED",
        db_index=True
    )
    # process tracking
    created_at = models.DateTimeField(auto_now_add=True)
    last_contacted = models.DateTimeField(null=True, blank=True)
    replied = models.BooleanField(default=False)
    bounce = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.first_name} {self.last_name} – {self.email}"



class EmailTemplate(models.Model):
    name = models.CharField(max_length=100)
    prompt = models.TextField()  # GPT prompt for generating body
    subject = models.CharField(max_length=255, null=True, blank=True)
    body = models.TextField()  # optional: fallback body
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class LeadEmailCopy(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="email_copies")
    template_name = models.CharField(max_length=100)  # which template was used
    subject = models.CharField(max_length=255)
    body = models.TextField()  # the generated email content
    ready_to_send = models.BooleanField(default=False)  # set True after generation
    sent = models.BooleanField(default=False)  # set True after email is sent
    sent_at = models.DateTimeField(null=True, blank=True)

    # metrics for tracking performance
    opened = models.BooleanField(default=False)
    clicked = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lead Email Copy"
        verbose_name_plural = "Lead Email Copies"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.lead.first_name} {self.lead.last_name} | Template: {self.template_name}"




class WebsiteLead(models.Model):
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255)

    company_name = models.CharField(max_length=255)
    description = models.CharField(max_length=1000, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.name




