from django.urls import path
from . import views

urlpatterns = [
    # placeholder route
    path('', views.index, name='index'),
    path('track/open/<str:lead_id>/', views.track_email_open, name='track_email_open'),
    path("lead", views.create_lead, name="create_lead"),  # matches your fetch("/api/lead")

]
