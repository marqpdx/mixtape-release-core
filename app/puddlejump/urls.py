from django.urls import include, path

urlpatterns = [
    path('', include('puddlejump.api.urls')),
]
