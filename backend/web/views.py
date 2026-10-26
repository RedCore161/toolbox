from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import TemplateView


# The page posts to the API with fetch(); the cookie lets it send X-CSRFToken when a session (admin login) exists.
@method_decorator(ensure_csrf_cookie, name="dispatch")
class IndexView(TemplateView):
    template_name = "web/index.html"
