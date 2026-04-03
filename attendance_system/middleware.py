from django.shortcuts import redirect
from django.urls import reverse


class AdminNoCacheAndRedirectMiddleware:
    """Middleware to ensure admin pages are not cached by browsers and
    to redirect already-authenticated staff away from the admin login page.

    Behavior:
    - If an authenticated staff user requests the admin login page, redirect
      them to the admin index so "back" doesn't show a stale login form.
    - For any response under `/admin/`, add no-cache headers to prevent
      browsers from showing a cached login page when navigating back.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # If a logged-in staff user hits the admin login page, redirect to admin index
        if path.startswith('/admin/login') and getattr(request, 'user', None) is not None:
            try:
                is_auth = request.user.is_authenticated
                is_staff = request.user.is_staff
            except Exception:
                is_auth = False
                is_staff = False
            if is_auth and is_staff:
                return redirect(reverse('admin:index'))

        response = self.get_response(request)

        # Prevent caching of admin pages so back/forward behaves correctly across browsers
        if path.startswith('/admin/'):
            response['Cache-Control'] = 'no-cache, no-store, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

        return response
