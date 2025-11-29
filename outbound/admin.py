from django.contrib import admin
from .models import *

# Register your models here.




class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'phone', 'source')
    search_fields = ('website','email')  # Add any other fields you want to make searchable
    ordering = ('-email',)


class WebsiteLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'description', 'date')
    ordering = ('-email',)


class VerifiedLeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'fit_score', 'intent_score')
    search_fields = ('website','email')  # Add any other fields you want to make searchable
    ordering = ('-email',)


admin.site.register(WebsiteLead,WebsiteLeadAdmin)


#admin.site.register(VerifiedLead,VerifiedLeadAdmin)

#admin.site.register(Campaign)
#admin.site.register(OutboundMessage)
#admin.site.register(ResponseTracking)


