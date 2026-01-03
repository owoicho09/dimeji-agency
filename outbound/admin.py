from django.contrib import admin
from .models import *

# Register your models here.


class LeadAdmin(admin.ModelAdmin):
    list_display = ('email','company','title','website', 'first_name', 'seo_description', 'country')
    list_filter = ('email_sent', 'score', 'email_verified','intent', 'country')  # Use custom filter class here
    search_fields = ('email',)  # Add any other fields you want to make searchable


class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('name','prompt','subject','body')



class LeadEmailCopyAdmin(admin.ModelAdmin):
    list_display = ('lead_email','template_name','subject','body','sent')
    search_fields = ('lead__email',)  # Add any other fields you want to make searchable
    list_filter = ('sent',)  # Use custom filter class here

    def lead_email(self, obj):
        return obj.lead.email


class WebsiteLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'description', 'date')
    ordering = ('-email',)


class VerifiedLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'fit_score', 'intent_score')
    search_fields = ('website','email')  # Add any other fields you want to make searchable
    ordering = ('-email',)


admin.site.register(WebsiteLead,WebsiteLeadAdmin)
admin.site.register(Lead,LeadAdmin)
admin.site.register(EmailTemplate,EmailTemplateAdmin)
admin.site.register(LeadEmailCopy,LeadEmailCopyAdmin)


#admin.site.register(VerifiedLead,VerifiedLeadAdmin)

#admin.site.register(Campaign)
#admin.site.register(OutboundMessage)
#admin.site.register(ResponseTracking)


