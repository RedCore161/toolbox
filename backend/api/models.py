from django.db import models


class Transcription(models.Model):
    audio = models.FileField(upload_to="audio/%Y/%m/")
    language = models.CharField(max_length=16)
    text = models.TextField(blank=True)
    words = models.JSONField(default=list, blank=True)
    duration_s = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.language}: {self.text[:60]}"


class ImageJob(models.Model):
    class Kind(models.TextChoices):
        MATTE = "matte"
        EDIT = "edit"
        ANALYZE = "analyze"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    source = models.ImageField(upload_to="images/source/%Y/%m/")
    task = models.CharField(max_length=32)
    query = models.CharField(max_length=500, blank=True)
    params = models.JSONField(default=dict, blank=True)
    # Raw model output: response text, boxes, latency.
    result = models.JSONField(default=dict, blank=True)
    # name -> storage path of generated files (alpha, cutout, background, edited, mask_0, ...).
    outputs = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}/{self.task}: {self.query}"
