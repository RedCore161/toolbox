from django.core.files.storage import default_storage
from rest_framework import serializers

from .models import ImageJob, Transcription

VISION_TASKS = [
    "detection", "referring", "point", "count_box", "count_point",
    "ocr", "ocr_grounding", "segmentation", "matting",
]
EDIT_OPERATIONS = ["remove_background", "replace_background", "blur_background", "grayscale_background"]


# --- inputs -----------------------------------------------------------------

class TranscribeInput(serializers.Serializer):
    audio = serializers.FileField()
    language = serializers.CharField(required=False, allow_blank=True, max_length=16)


class MatteInput(serializers.Serializer):
    image = serializers.ImageField()
    query = serializers.CharField(max_length=500, default="the main subject")


class EditInput(MatteInput):
    operation = serializers.ChoiceField(EDIT_OPERATIONS)
    color = serializers.CharField(required=False, max_length=32, help_text="replace_background: CSS color")
    background = serializers.ImageField(required=False, help_text="replace_background: image")
    blur_radius = serializers.FloatField(required=False, default=12, min_value=1, max_value=100)


class AnalyzeInput(serializers.Serializer):
    image = serializers.ImageField()
    task = serializers.ChoiceField(VISION_TASKS)
    query = serializers.CharField(max_length=500, required=False, allow_blank=True, default="",
                                  help_text="detection: one label per line")


# --- outputs ----------------------------------------------------------------

class TranscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transcription
        fields = ["id", "audio", "language", "text", "words", "duration_s", "created_at"]


class ImageJobSerializer(serializers.ModelSerializer):
    output_urls = serializers.SerializerMethodField()

    class Meta:
        model = ImageJob
        fields = ["id", "kind", "task", "query", "params", "source", "result", "output_urls", "created_at"]

    def get_output_urls(self, job):
        request = self.context.get("request")
        urls = {name: default_storage.url(path) for name, path in job.outputs.items()}
        return {k: request.build_absolute_uri(v) for k, v in urls.items()} if request else urls
