# outbound/serializers.py
from rest_framework import serializers
from .models import *



class ICPSerializer(serializers.ModelSerializer):
    class Meta:
        model = ICP
        fields = '__all__'

class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = '__all__'

class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = '__all__'

class OutboundMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboundMessage
        fields = '__all__'

class ResponseTrackingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResponseTracking
        fields = '__all__'

class NurtureSequenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NurtureSequence
        fields = '__all__'
