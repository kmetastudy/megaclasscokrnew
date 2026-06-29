from django.contrib import admin
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from accounts.models import Class, School, Teacher
from teacher.models import Course, CourseAssignment


class CourseAssignmentAdminBulkAssignTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='password',
        )
        self.staff_user = User.objects.create_user(
            username='staff',
            email='staff@example.com',
            password='password',
            is_staff=True,
        )
        school = School.objects.create(name='A School', address='A', code='A001')
        target_school = School.objects.create(name='B School', address='B', code='B001')
        teacher_user = User.objects.create_user(username='teacher', password='password')
        teacher = Teacher.objects.create(user=teacher_user, school=school, employee_id='T001')

        self.course1 = Course.objects.create(subject_name='Course 1', target='Grade 1', teacher=teacher)
        self.course2 = Course.objects.create(subject_name='Course 2', target='Grade 1', teacher=teacher)
        self.class1 = Class.objects.create(school=target_school, grade=1, class_number=1, name='1-1')
        self.class2 = Class.objects.create(school=target_school, grade=1, class_number=2, name='1-2')

        self.url = reverse('admin:teacher_courseassignment_bulk_assign')

    def test_bulk_assign_view_requires_superuser(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)

    def test_bulk_assign_creates_missing_course_class_pairs_and_skips_existing(self):
        CourseAssignment.objects.create(course=self.course1, assigned_class=self.class1)
        self.client.force_login(self.superuser)

        response = self.client.post(
            self.url,
            {
                'courses': [self.course1.id, self.course2.id],
                'classes': [self.class1.id, self.class2.id],
                'due_date': '2026-07-01T09:30',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CourseAssignment.objects.count(), 4)
        self.assertEqual(
            set(CourseAssignment.objects.values_list('course_id', 'assigned_class_id')),
            {
                (self.course1.id, self.class1.id),
                (self.course1.id, self.class2.id),
                (self.course2.id, self.class1.id),
                (self.course2.id, self.class2.id),
            },
        )
        self.assertEqual(
            CourseAssignment.objects.filter(due_date__isnull=False).count(),
            3,
        )

    def test_create_bulk_assignments_reports_created_and_skipped_counts(self):
        CourseAssignment.objects.create(course=self.course1, assigned_class=self.class1)
        model_admin = admin.site._registry[CourseAssignment]

        created_count, skipped_count = model_admin.create_bulk_assignments(
            Course.objects.filter(id__in=[self.course1.id, self.course2.id]),
            Class.objects.filter(id__in=[self.class1.id, self.class2.id]),
            due_date=None,
        )

        self.assertEqual(created_count, 3)
        self.assertEqual(skipped_count, 1)
        self.assertEqual(CourseAssignment.objects.count(), 4)
