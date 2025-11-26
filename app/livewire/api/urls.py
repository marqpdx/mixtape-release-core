# livewire/api/urls.py

from django.urls import path

from livewire.api.views import exchange_ws_for_service_token, livewire_token

# base path: api/livewire/

urlpatterns = [

    path("token", livewire_token, name="livewire-token"),
    path("exchange", exchange_ws_for_service_token, name="exchange-ws-for-service-token"),

]