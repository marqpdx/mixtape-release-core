# earthlab/api/urls.py
from django.urls import path
from . import views

# parent: api/earthlab/

urlpatterns = [
    # Courses
    path('<slug:group_slug>/courses', views.list_or_create_courses),
    path('<slug:group_slug>/courses/<slug:course_slug>', views.course_detail),

    # Course Items (Outline)
    path('<slug:group_slug>/courses/<slug:course_slug>/items', views.add_course_item),
    path('<slug:group_slug>/courses/<slug:course_slug>/items/reorder', views.reorder_course_items),
    path('<slug:group_slug>/courses/<slug:course_slug>/items/<uuid:item_id>', views.remove_course_item),

    # Available content for picker
    path('<slug:group_slug>/available-content', views.list_available_content),

    # Course Runs
    path('<slug:group_slug>/courses/<slug:course_slug>/runs', views.list_or_create_runs),
    path('<slug:group_slug>/courses/<slug:course_slug>/runs/<uuid:run_id>', views.run_detail),
    path('<slug:group_slug>/courses/<slug:course_slug>/runs/<uuid:run_id>/enroll', views.enroll_in_run),
    path('<slug:group_slug>/courses/<slug:course_slug>/runs/<uuid:run_id>/progress', views.get_progress),
    path('<slug:group_slug>/courses/<slug:course_slug>/runs/<uuid:run_id>/mark-complete', views.mark_lesson_complete),

    # Lessons
    path('<slug:group_slug>/lessons', views.list_or_create_lessons),
    path('<slug:group_slug>/lessons/<slug:lesson_slug>', views.lesson_detail),
]
