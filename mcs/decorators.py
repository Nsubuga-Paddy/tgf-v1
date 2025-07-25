from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.safestring import mark_safe
from django.urls import reverse
from .models import ClubMembership

def project_required(project_name):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if request.user.is_authenticated:
                if request.user.profile.projects.filter(name=project_name).exists():
                    return view_func(request, *args, **kwargs)
                else:
                    support_url = reverse('support')
                    messages.error(
                        request,
                        mark_safe(
                            f"You currently do not have access to the '{project_name}' service. "
                            f"Please <a href='{support_url}' class='alert-link'>contact our support team</a> "
                            f"to request access or learn more."
                        )
                    )
            else:
                messages.error(request, "Please log in to continue.")
            return redirect('home')  # You can also redirect to a custom "Access Denied" page
        return _wrapped_view
    return decorator


def club_membership_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, club_id, *args, **kwargs):
        user_profile = request.user.profile
        if not ClubMembership.objects.filter(club_id=club_id, user_profile=user_profile, is_active=True).exists():
            messages.warning(request, "You do not have access to this club. Please contact support.")
            return redirect('home')
        return view_func(request, club_id, *args, **kwargs)
    return _wrapped_view
