from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("transcriptions", views.TranscriptionViewSet)
router.register("image-jobs", views.ImageJobViewSet)

urlpatterns = [
    path("health/", views.HealthView.as_view()),
    path("stt/transcribe/", views.TranscribeView.as_view()),
    path("vision/matte/", views.MatteView.as_view()),
    path("vision/edit/", views.EditView.as_view()),
    path("vision/analyze/", views.AnalyzeView.as_view()),
    *router.urls,
]
