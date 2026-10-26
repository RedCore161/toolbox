from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from . import clients, imaging
from .models import ImageJob, Transcription
from .serializers import (
    AnalyzeInput,
    EditInput,
    ImageJobSerializer,
    MatteInput,
    TranscribeInput,
    TranscriptionSerializer,
)


class NothingFound(APIException):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The model found nothing matching the query."


def _save_outputs(job: ImageJob, images: dict[str, Image.Image]) -> None:
    for name, img in images.items():
        path = default_storage.save(f"images/output/{job.pk}/{name}.png", ContentFile(imaging.to_png_bytes(img)))
        job.outputs[name] = path
    job.save(update_fields=["outputs"])


def _open(file) -> Image.Image:
    file.seek(0)
    image = Image.open(file)
    image.load()
    return image


def _matte(image_file, query: str) -> tuple[dict, Image.Image]:
    """Run promptable matting and return the raw result plus the combined alpha map."""
    result = clients.predict(image_file, "matting", query)
    masks = imaging.decode_masks(result.pop("masks"))
    if not masks:
        raise NothingFound(f"Nothing matching {query!r} found in the image.")
    return result, imaging.combined_alpha(masks)


class HealthView(APIView):
    def get(self, request):
        return Response({
            "backend": {"ok": True},
            "stt": clients.health(settings.STT_URL),
            "vision": clients.health(settings.VISION_URL),
        })


class TranscribeView(APIView):
    """POST audio (any format ffmpeg can read) -> text with word timings."""

    def post(self, request):
        data = TranscribeInput(data=request.data)
        data.is_valid(raise_exception=True)
        audio = data.validated_data["audio"]
        result = clients.transcribe(audio, data.validated_data.get("language", ""))
        transcription = Transcription.objects.create(
            audio=audio,
            language=result["language"],
            text=result["text"],
            words=result["words"],
            duration_s=result["duration_s"],
        )
        return Response(TranscriptionSerializer(transcription, context={"request": request}).data,
                        status=status.HTTP_201_CREATED)


class MatteView(APIView):
    """POST image + query -> alpha map, cutout (RGBA) and background mask."""

    def post(self, request):
        data = MatteInput(data=request.data)
        data.is_valid(raise_exception=True)
        image_file, query = data.validated_data["image"], data.validated_data["query"]

        result, alpha = _matte(image_file, query)
        image = _open(image_file)
        job = ImageJob.objects.create(kind=ImageJob.Kind.MATTE, source=image_file, task="matting",
                                      query=query, result=result)
        _save_outputs(job, {
            "alpha": alpha,
            "cutout": imaging.cutout(image, alpha),
            "background_mask": imaging.background_mask(alpha),
            "foreground_mask": imaging.threshold(alpha),
        })
        return Response(ImageJobSerializer(job, context={"request": request}).data, status=status.HTTP_201_CREATED)


class EditView(APIView):
    """POST image + query + operation -> edited image, using the matte of `query` as the subject."""

    def post(self, request):
        data = EditInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        image_file, op = v["image"], v["operation"]

        result, alpha = _matte(image_file, v["query"])
        image = _open(image_file)
        if op == "remove_background":
            edited = imaging.cutout(image, alpha)
        elif op == "replace_background":
            background = _open(v["background"]) if v.get("background") else None
            edited = imaging.replace_background(image, alpha, color=v.get("color"), background=background)
        elif op == "blur_background":
            edited = imaging.blur_background(image, alpha, radius=v["blur_radius"])
        else:
            edited = imaging.grayscale_background(image, alpha)

        params = {"operation": op, "color": v.get("color"), "blur_radius": v["blur_radius"]}
        job = ImageJob.objects.create(kind=ImageJob.Kind.EDIT, source=image_file, task="matting",
                                      query=v["query"], params=params, result=result)
        _save_outputs(job, {"edited": edited, "alpha": alpha})
        return Response(ImageJobSerializer(job, context={"request": request}).data, status=status.HTTP_201_CREATED)


class AnalyzeView(APIView):
    """POST image + task + query -> raw WeVisOne-VL output (boxes, text, masks as PNGs)."""

    def post(self, request):
        data = AnalyzeInput(data=request.data)
        data.is_valid(raise_exception=True)
        image_file, task, query = (data.validated_data[k] for k in ("image", "task", "query"))

        result = clients.predict(image_file, task, query)
        masks = imaging.decode_masks(result.pop("masks"))
        job = ImageJob.objects.create(kind=ImageJob.Kind.ANALYZE, source=image_file, task=task,
                                      query=query, result=result)
        if task == "segmentation":
            masks_out = {f"mask_{i}": imaging.threshold(imaging.combined_alpha([m])) for i, m in enumerate(masks)}
        else:
            masks_out = {f"mask_{i}": imaging.combined_alpha([m]) for i, m in enumerate(masks)}
        _save_outputs(job, masks_out)
        return Response(ImageJobSerializer(job, context={"request": request}).data, status=status.HTTP_201_CREATED)


class TranscriptionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Transcription.objects.all()
    serializer_class = TranscriptionSerializer


class ImageJobViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ImageJob.objects.all()
    serializer_class = ImageJobSerializer
