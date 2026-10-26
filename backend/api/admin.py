from django.contrib import admin

from .models import ImageJob, Transcription


@admin.register(Transcription)
class TranscriptionAdmin(admin.ModelAdmin):
    list_display = ("id", "language", "text", "duration_s", "created_at")


@admin.register(ImageJob)
class ImageJobAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "task", "query", "created_at")
    list_filter = ("kind", "task")
