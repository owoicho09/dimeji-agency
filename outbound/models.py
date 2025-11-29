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
    #icp = models.ForeignKey(ICP, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50,blank=True, null=True)
    company = models.CharField(max_length=255,blank=True, null=True)
    address = models.CharField(max_length=255,blank=True, null=True)

    website = models.URLField(blank=True, null=True)
    linkedin_url = models.URLField(blank=True, null=True)
    verified = models.BooleanField(default=False)
    note = models.TextField(blank=True, null=True)

    intent_score = models.FloatField(default=0)
    fit_score = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    source = models.CharField(max_length=50,blank=True, null=True)
    lead_id = ShortUUIDField(unique=True, length=7, max_length=20)


    def __str__(self):
        return self.name




class WebsiteLead(models.Model):
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255)

    company_name = models.CharField(max_length=255)
    description = models.CharField(max_length=1000, null=True, blank=True)
    date = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.name



class VerifiedLead(models.Model):
    #icp = models.ForeignKey(ICP, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=50,blank=True, null=True)
    website = models.URLField(blank=True, null=True)

    company = models.CharField(max_length=255,blank=True, null=True)
    address = models.CharField(max_length=255,blank=True, null=True)
    lead_id = ShortUUIDField(unique=True, length=7, max_length=20)
    source = models.CharField(max_length=50,blank=True, null=True)

    personalization_note = models.TextField(blank=True, null=True)
    intent_score = models.FloatField(default=0)
    fit_score = models.FloatField(default=0)

    stage = models.CharField(max_length=50, choices=[('first_touch','First Touch'),('follow_up','Follow Up'),('nurture','Nurture')], blank=True, null=True )
    total_email_sent = models.FloatField(default=0)
    sent = models.BooleanField(default=False)
    date_sent = models.DateTimeField(blank=True, null=True)

    opened = models.BooleanField(default=False)
    opened_date = models.DateTimeField(blank=True, null=True)

    replied = models.BooleanField(default=False)

    email_provider_used = models.CharField(max_length=50, null=True, blank=True)


    def __str__(self):
        return self.name




class Campaign(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    start_date = models.DateTimeField(auto_now_add=True)
    end_date = models.DateTimeField(blank=True, null=True)

    campaign_id = ShortUUIDField(unique=True, length=7, max_length=20)

    def __str__(self):
        return f"{self.name} - {self.lead}"

class OutboundMessage(models.Model):
    lead = models.ForeignKey(VerifiedLead, on_delete=models.CASCADE)
    #campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    subject_line = models.CharField(max_length=100,blank=True, null=True)
    body = models.TextField(max_length=200,blank=True, null=True)
    stage = models.CharField(max_length=50, choices=[('first_touch','First Touch'),('follow_up','Follow Up'),('nurture','Nurture')])
    sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(blank=True, null=True)



class ResponseTracking(models.Model):
    message = models.ForeignKey(OutboundMessage, on_delete=models.CASCADE)
    open_status = models.BooleanField(default=False)
    replied = models.BooleanField(default=False)
    response_text = models.TextField(blank=True, null=True)
    response_time = models.DateTimeField(blank=True, null=True)



class NurtureSequence(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE)
    sequence_stage = models.IntegerField()
    message_text = models.TextField()
    completed = models.BooleanField(default=False)
    sent_at = models.DateTimeField(blank=True, null=True)
