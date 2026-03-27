from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Avg, Prefetch, F
from django.utils import timezone
from django.http import JsonResponse
from functools import wraps
from decimal import Decimal
from django.db import transaction
from django.views.decorators.http import require_POST

from accounts.models import Student
from teacher.models import (
    Course, CourseAssignment, Chapter, SubChapter, 
    Chasi, ChasiSlide, Contents, ContentType
)
from .models import StudentProgress, StudentAnswer, StudentNote,PhysicalResultType,StudentPhysicalResult
from datetime import datetime, timedelta


from .utils import *
from django.db import transaction # 트랜잭션 처리를 위해 추가

import json
from datetime import datetime, timedelta
from app_home.models import HealthHabitTracker, DailyReflection, TrackerEvaluation
from rolling.models import RollingAttempt, RollingEvaluation


def student_required(view_func):
    """학생 권한 필요한 뷰 데코레이터"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, '로그인이 필요합니다.')
            return redirect('accounts:login')
        
        if not hasattr(request.user, 'student'):
            messages.error(request, '학생만 접근 가능합니다.')
            return redirect('accounts:login')
        
        return view_func(request, *args, **kwargs)
    
    return login_required(_wrapped_view)


@login_required
def dashboard_view(request):
    """학생 대시보드 view"""
    student = request.user.student
    
    # 학생에게 할당된 모든 코스를 가져옵니다.
    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_student=student) | Q(assigned_class=student.school_class)
    ).distinct()
    
    # 할당된 코스 ID 목록을 가져옵니다.
    assigned_course_ids = assigned_courses.values_list('course_id', flat=True)

    # 통계 계산
    completed_slides = StudentProgress.objects.filter(student=student, is_completed=True).count()
    total_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject_id__in=assigned_course_ids).count()
    total_records = StudentPhysicalResult.objects.filter(student=student).count()

    stats = {
        'assigned_courses': len(assigned_course_ids),
        'completed_slides': completed_slides,
        'total_slides': total_slides,
        'progress_percent': int((completed_slides / total_slides) * 100) if total_slides > 0 else 0,
        'submitted_answers': StudentAnswer.objects.filter(student=student).count(),
        'total_records': total_records,
    }
    
    # 최근 활동 데이터
    recent_progress = StudentProgress.objects.filter(
        student=student, started_at__isnull=False
    ).select_related('slide__chasi').order_by('-started_at')[:3]

    recent_records = StudentPhysicalResult.objects.filter(
        student=student
    ).select_related('slide__chasi').order_by('-submitted_at')[:3]

    # ★★★ 주간 학습 패턴 실제 데이터 ★★★
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())  # 월요일
    
    weekly_labels = []
    weekly_minutes = []
    weekly_slides = []
    
    for i in range(7):
        current_date = start_of_week + timedelta(days=i)
        day_name = ['월', '화', '수', '목', '금', '토', '일'][i]
        weekly_labels.append(day_name)
        
        # 해당 날짜의 학습 활동
        daily_progress = StudentProgress.objects.filter(
            student=student,
            started_at__date=current_date
        )
        
        # 완료한 슬라이드 수
        completed_count = daily_progress.filter(is_completed=True).count()
        weekly_slides.append(completed_count)
        
        # 예상 학습 시간 (슬라이드당 15분으로 가정)
        study_minutes = daily_progress.count() * 15
        weekly_minutes.append(study_minutes)
    
    # 주간 통계 계산
    total_weekly_minutes = sum(weekly_minutes)
    total_weekly_hours = round(total_weekly_minutes / 60, 1)
    
    # 지난주 대비 개선율 (간단히 계산)
    last_week_progress = StudentProgress.objects.filter(
        student=student,
        started_at__date__gte=start_of_week - timedelta(days=7),
        started_at__date__lt=start_of_week
    ).count()
    this_week_progress = sum(weekly_slides)
    improvement_percentage = 0
    if last_week_progress > 0:
        improvement_percentage = int(((this_week_progress - last_week_progress) / last_week_progress) * 100)
    
    # 연속 학습 일수 계산
    consecutive_days = 0
    for i in range(7):
        check_date = today - timedelta(days=i)
        if StudentProgress.objects.filter(
            student=student,
            started_at__date=check_date
        ).exists():
            consecutive_days += 1
        else:
            break
    
    # ★★★ 오늘의 할 일 - 미학습 차시 3개 ★★★
    # 모든 활성화된 슬라이드 가져오기
    all_active_slides = ChasiSlide.objects.filter(
        chasi__sub_chapter__chapter__subject_id__in=assigned_course_ids,
        is_active=True,
        chasi__is_published=True
    ).select_related(
        'chasi__sub_chapter__chapter__subject',
        'content_type'
    ).order_by(
        'chasi__sub_chapter__chapter__chapter_order',
        'chasi__sub_chapter__sub_chapter_order',
        'chasi__chasi_order',
        'slide_number'
    )
    
    # 이미 시작한 슬라이드 ID 목록
    started_slide_ids = StudentProgress.objects.filter(
        student=student
    ).values_list('slide_id', flat=True)
    
    # 미학습 슬라이드 필터링
    not_started_slides = []
    for slide in all_active_slides:
        if slide.id not in started_slide_ids:
            not_started_slides.append(slide)
            if len(not_started_slides) >= 3:
                break
    
    # 오늘의 할 일 데이터 구성
    today_tasks = []
    for slide in not_started_slides:
        task = {
            'slide': slide,
            'course_name': slide.chasi.sub_chapter.chapter.subject.subject_name,
            'chasi_title': slide.chasi.chasi_title,
            'slide_title': slide.slide_title or f"슬라이드 {slide.slide_number}",
            'content_type': slide.content_type.type_name,
            'estimated_time': slide.estimated_time or 15,
        }
        today_tasks.append(task)
    
    context = {
        'stats': stats,
        'assigned_courses': assigned_courses.select_related('course', 'course__teacher')[:5],
        'recent_progress': recent_progress,
        'recent_records': recent_records,
        'chart_labels': json.dumps(weekly_labels),
        'chart_minutes': json.dumps(weekly_minutes),
        'chart_slides': json.dumps(weekly_slides),
        'total_weekly_hours': total_weekly_hours,
        'improvement_percentage': improvement_percentage,
        'consecutive_days': consecutive_days,
        'today_tasks': today_tasks,
    }
    
    return render(request, 'student/dashboard.html', context)


@login_required
def dashboard_view_0619(request):
    """학생 대시보드 view"""
    student = request.user.student
    
    # 학생에게 할당된 모든 코스를 가져옵니다.
    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_student=student) | Q(assigned_class=student.school_class)
    ).distinct()
    
    # 할당된 코스 ID 목록을 가져옵니다.
    assigned_course_ids = assigned_courses.values_list('course_id', flat=True)

    # 통계 계산
    completed_slides = StudentProgress.objects.filter(student=student, is_completed=True).count()
    total_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject_id__in=assigned_course_ids).count()
    total_records = StudentPhysicalResult.objects.filter(student=student).count()

    stats = {
        'assigned_courses': len(assigned_course_ids),
        'completed_slides': completed_slides,
        'total_slides': total_slides,
        'progress_percent': int((completed_slides / total_slides) * 100) if total_slides > 0 else 0,
        'submitted_answers': StudentAnswer.objects.filter(student=student).count(),
        'total_records': total_records,
    }
    
    # 최근 활동 데이터
    recent_progress = StudentProgress.objects.filter(
        student=student, started_at__isnull=False
    ).select_related('slide__chasi').order_by('-started_at')[:3]

    recent_records = StudentPhysicalResult.objects.filter(
        student=student
    ).select_related('slide__chasi').order_by('-submitted_at')[:3]

    context = {
        'stats': stats,
        'assigned_courses': assigned_courses.select_related('course', 'course__teacher')[:5],
        'recent_progress': recent_progress,
        'recent_records': recent_records,
    }
    
    return render(request, 'student/dashboard.html', context)


@login_required
@student_required
def dashboard_view_0608(request):
    """학생 대시보드"""
    student = request.user.student
    
    # 할당받은 코스들
    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_student=student) | Q(assigned_class=student.school_class)
    ).select_related('course', 'course__teacher')
    
    # 진행 상황
    my_progress = StudentProgress.objects.filter(student=student)
    
    # 전체 슬라이드 수 계산
    course_ids = assigned_courses.values_list('course_id', flat=True).distinct()
    total_slides = ChasiSlide.objects.filter(
        chasi__sub_chapter__chapter__subject__id__in=course_ids
    ).count()  # .count() 추가!
    
    # 완료한 슬라이드 수
    completed_slides = my_progress.filter(is_completed=True).count()
    
    # 진도율 계산
    if total_slides > 0:
        progress_percent = int((completed_slides / total_slides) * 100)
    else:
        progress_percent = 0
    
    # 통계 데이터
    stats = {
        'assigned_courses': assigned_courses.count(),
        'completed_slides': completed_slides,
        'total_slides': total_slides,
        'progress_percent': progress_percent,
        'submitted_answers': StudentAnswer.objects.filter(student=student).count(),
         # ★★★ 기록된 활동 통계 추가 ★★★
        'total_records': StudentPhysicalResult.objects.filter(student=student).count(),
    }
    
    # 최근 학습한 슬라이드
    recent_progress = StudentProgress.objects.filter(
        student=student, 
        started_at__isnull=False
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-started_at')[:5]

    # 주간 학습 데이터 계산
    today = timezone.now().date()
    start_of_week = today - timedelta(days=today.weekday())  # 월요일
    
    weekly_data = []
    day_names = ['월', '화', '수', '목', '금', '토', '일']
    
    for i in range(7):
        current_date = start_of_week + timedelta(days=i)
        
        # 해당 날짜에 완료한 슬라이드 수
        completed_count = StudentProgress.objects.filter(
            student=student,
            completed_at__date=current_date,
            is_completed=True
        ).count()
        
        weekly_data.append({
            'day': day_names[i],
            'count': completed_count,
            'percentage': min(completed_count * 5, 100)  # 20개를 100%로 가정
        })

    # ★★★ 최근 신체 기록 요약 추가 ★★★
    recent_records = StudentPhysicalResult.objects.filter(
        student=student
    ).select_related('slide__chasi').order_by('-submitted_at')[:3]
    
    context = {
        'stats': stats,
        'assigned_courses': assigned_courses[:5],
        'recent_progress': recent_progress,
        'weekly_data': weekly_data,
        'recent_records': recent_records, # 컨텍스트에 추가
    }
    
    return render(request, 'student/dashboard.html', context)


# ★★★ '내 기록' 상세 페이지 뷰 추가 ★★★
# views.py의 my_records_view 수정 버전
@login_required
def my_records_view(request):
    """학생의 모든 활동 기록을 보여주는 통합 페이지"""
    student = request.user.student
    
    # 1. physical_record 타입 기록 가져오기
    physical_records = StudentPhysicalResult.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-submitted_at')
    
    # physical_record 데이터 처리
    processed_physical_records = []
    for record in physical_records:
        # record 필드가 JSON 리스트 형태인 경우 처리
        if isinstance(record.record, list):
            attempts = []
            for idx, attempt_data in enumerate(record.record):
                # 밀리초를 시간 형식으로 변환
                ms = attempt_data.get('기록', 0)
                formatted_time = format_ms_to_time(ms) if ms else '기록 없음'
                
                attempts.append({
                    '회차': attempt_data.get('회차', idx + 1),
                    '기록': ms,
                    '기록_포맷': formatted_time,
                    '종류': attempt_data.get('종류', '달리기'),
                    '단위': attempt_data.get('단위', 'mili_second')
                })
            
            # 기록 향상도 계산 (2회차가 있는 경우)
            improvement = None
            if len(attempts) >= 2 and attempts[0]['기록'] and attempts[1]['기록']:
                diff = attempts[0]['기록'] - attempts[1]['기록']
                improvement_percent = round(abs(diff) / attempts[0]['기록'] * 100, 1)
                if diff > 0:
                    improvement = f"+{improvement_percent}% 향상"
                else:
                    improvement = f"-{improvement_percent}% 저하"
            
            processed_physical_records.append({
                'original': record,
                'processed_attempts': attempts,
                'has_multiple_attempts': len(attempts) > 1,
                'improvement_percentage': improvement
            })
    
    # 2. take-action (health_habit) 타입 기록 가져오기
    # HealthHabitTracker import 필요
    from app_home.models import HealthHabitTracker, DailyReflection, TrackerEvaluation
    
    health_habit_records = HealthHabitTracker.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'overall_evaluation'
    ).prefetch_related('reflections').order_by('-created_at')
    
    # health_habit 데이터 처리
    processed_health_habits = []
    for tracker in health_habit_records:
        # 각 약속별 완료율 계산
        promise_stats = tracker.get_promise_stats()
        completion_stats = tracker.get_completion_stats()
        
        # 작성한 소감 수 계산
        total_reflections = tracker.reflections.count()
        
        # 평가 정보
        has_evaluation = hasattr(tracker, 'overall_evaluation')
        evaluation_grade = None
        if has_evaluation:
            evaluation_grade = tracker.overall_evaluation.get_grade_display()
        
        # 약속 데이터를 템플릿에서 쉽게 사용할 수 있도록 리스트로 변환
        promises_list = []
        for i in range(1, 7):
            promise_text = tracker.promises.get(str(i), f'약속 {i}')
            promise_stat = promise_stats.get(i, {'completed_days': 0, 'rate': 0})
            
            promises_list.append({
                'number': i,
                'text': promise_text,
                'completed_days': promise_stat['completed_days'],
                'completion_rate': promise_stat['rate'],
                'color_class': get_promise_color_class(i)
            })
        
        processed_health_habits.append({
            'tracker': tracker,
            'promises_list': promises_list,  # 리스트로 변환된 약속 데이터
            'total_reflections': total_reflections,
            'completion_rate': completion_stats['completion_rate'],
            'has_evaluation': has_evaluation,
            'evaluation_grade': evaluation_grade,
            'is_submitted': tracker.is_submitted
        })
    
    # 3. rolling 타입 기록 가져오기
    # RollingAttempt import 필요
    from rolling.models import RollingAttempt, RollingEvaluation
    
    # 학생의 모든 rolling 시도 가져오기
    rolling_attempts = RollingAttempt.objects.filter(
        student=student
    ).order_by('attempt_number')
    
    # rolling 평가 정보 가져오기
    try:
        rolling_evaluation = RollingEvaluation.objects.get(student=student)
    except RollingEvaluation.DoesNotExist:
        rolling_evaluation = None
    
    # rolling 데이터 처리
    rolling_data = None
    if rolling_attempts.exists():
        success_count = rolling_attempts.filter(is_success=True).count()
        total_attempts = rolling_attempts.count()
        
        # 각 시도별 데이터
        attempts_list = []
        for attempt in rolling_attempts:
            attempts_list.append({
                'attempt_number': attempt.attempt_number,
                'is_success': attempt.is_success,
                'feedback': attempt.feedback,
                'created_at': attempt.created_at
            })
        
        rolling_data = {
            'total_attempts': total_attempts,
            'success_count': success_count,
            'success_rate': round((success_count / total_attempts * 100), 1) if total_attempts > 0 else 0,
            'attempts': attempts_list,
            'has_evaluation': rolling_evaluation is not None,
            'evaluation': rolling_evaluation
        }
    
    # 전체 통계 계산
    total_records = (
        len(processed_physical_records) + 
        len(processed_health_habits) + 
        (1 if rolling_data else 0)
    )
    
    context = {
        'physical_records': processed_physical_records,
        'health_habit_records': processed_health_habits,
        'rolling_data': rolling_data,
        'total_records': total_records,
        'has_physical': len(processed_physical_records) > 0,
        'has_health_habit': len(processed_health_habits) > 0,
        'has_rolling': rolling_data is not None
    }
    
    return render(request, 'student/my_records.html', context)


# 밀리초를 시간 형식으로 변환하는 헬퍼 함수
def format_ms_to_time(ms):
    """밀리초를 MM:SS.ms 형식으로 변환"""
    total_seconds = ms / 1000
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    hundredths = int((ms % 1000) / 10)
    return f"{minutes:02d}:{seconds:02d}.{hundredths:02d}"


# 약속 번호에 따른 색상 클래스 반환 헬퍼 함수
def get_promise_color_class(number):
    """약속 번호에 따른 Tailwind CSS 색상 클래스 반환"""
    color_map = {
        1: 'from-red-500 to-red-600',
        2: 'from-orange-500 to-orange-600',
        3: 'from-yellow-500 to-yellow-600',
        4: 'from-green-500 to-green-600',
        5: 'from-blue-500 to-blue-600',
        6: 'from-purple-500 to-purple-600'
    }
    return color_map.get(number, 'from-gray-500 to-gray-600')

@login_required
def my_records_view_0619(request):
    """학생의 모든 신체 활동 기록을 보여주는 페이지"""
    student = request.user.student
    records = StudentPhysicalResult.objects.filter(student=student).select_related(
        'slide__chasi__sub_chapter__chapter__subject'
    ).order_by('-submitted_at')

    context = {
        'records': records,
    }
    return render(request, 'student/my_records.html', context)




@login_required
@student_required
def course_list_view(request):
    """내 코스 목록"""
    student = request.user.student

    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).select_related('course', 'course__teacher')

    # 각 코스별 진도 계산
    course_data = []
    school_levels = set()
    targets = set()
    subjects = set()

    for assignment in assigned_courses:
        total_slides = ChasiSlide.objects.filter(
            chasi__sub_chapter__chapter__subject=assignment.course,
        ).count()

        completed_slides = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=assignment.course,
            is_completed=True
        ).count()

        progress_percent = 0
        if total_slides > 0:
            progress_percent = int((completed_slides / total_slides) * 100)

        target = assignment.course.target or ''
        subject = assignment.course.subject_name or ''

        # 학교급 추출
        school_level = ''
        if '초' in target:
            school_level = '초등학교'
        elif '중' in target:
            school_level = '중학교'
        elif '고' in target:
            school_level = '고등학교'

        if school_level:
            school_levels.add(school_level)
        if target:
            targets.add(target)
        if subject:
            subjects.add(subject)

        course_data.append({
            'assignment': assignment,
            'total_slides': total_slides,
            'completed_slides': completed_slides,
            'progress_percent': progress_percent,
            'school_level': school_level,
            'subject': subject,
        })

    context = {
        'course_data': course_data,
        'school_levels': sorted(school_levels),
        'targets': sorted(targets),
        'subjects': sorted(subjects),
    }

    return render(request, 'student/course_list.html', context)

# ====================================================================
# ★★★ 1. learning_course_view 수정 ★★★
# ====================================================================
@login_required
@student_required
def learning_course_view(request, course_id):
    """코스 학습 페이지 (통계 로직 수정)"""
    student = request.user.student
    course = get_object_or_404(Course, id=course_id)
    
    has_permission = CourseAssignment.objects.filter(
        course=course,
    ).filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).exists()
    
    if not has_permission:
        messages.error(request, '해당 코스에 접근 권한이 없습니다.')
        return redirect('student:course_list')
    
    chapters = course.chapters.all().order_by('chapter_order')
    
    all_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject=course, is_active=True)
    total_slides_count = all_slides.count()
    
    completed_slides_count = StudentProgress.objects.filter(
        student=student,
        slide__in=all_slides,
        is_completed=True
    ).count()
    
    in_progress_count = StudentProgress.objects.filter(
        student=student,
        slide__in=all_slides,
        is_completed=False,
        started_at__isnull=False
    ).count()

    overall_progress = int((completed_slides_count / total_slides_count) * 100) if total_slides_count > 0 else 0

    progress_qs = StudentProgress.objects.filter(student=student, slide__in=all_slides)
    progress_data = {progress.slide_id: progress for progress in progress_qs}
    
    # 답안 제출 정보도 가져오기 (선택사항)
    from .models import StudentAnswer
    answer_data = {}
    for slide_id in progress_data.keys():
        last_answer = StudentAnswer.objects.filter(
            student=student,
            slide_id=slide_id
        ).order_by('-submitted_at').first()
        if last_answer:
            answer_data[slide_id] = last_answer
    
    context = {
        'course': course,
        'chapters': chapters,
        'progress_data': progress_data,
        'answer_data': answer_data,  # 추가
        'overall_progress': overall_progress,
        'total_slides': total_slides_count,
        'completed_slides': completed_slides_count,
        'in_progress_count': in_progress_count,
    }
    
    return render(request, 'student/learning_course.html', context)

@login_required
@student_required
def learning_course_view_061906(request, course_id):
    """코스 학습 페이지 (통계 로직 수정)"""
    student = request.user.student
    course = get_object_or_404(Course, id=course_id)
    
    has_permission = CourseAssignment.objects.filter(
        course=course,
    ).filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).exists()
    
    if not has_permission:
        messages.error(request, '해당 코스에 접근 권한이 없습니다.')
        return redirect('student:course_list')
    
    chapters = course.chapters.all().order_by('chapter_order')
    
    all_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject=course, is_active=True)
    total_slides_count = all_slides.count()
    
    completed_slides_count = StudentProgress.objects.filter(
        student=student,
        slide__in=all_slides,
        is_completed=True
    ).count()
    
    # 진행중인 슬라이드 수 추가
    in_progress_count = StudentProgress.objects.filter(
        student=student,
        slide__in=all_slides,
        is_completed=False,
        started_at__isnull=False  # 시작은 했지만 완료하지 않은 것
    ).count()

    overall_progress = int((completed_slides_count / total_slides_count) * 100) if total_slides_count > 0 else 0

    progress_qs = StudentProgress.objects.filter(student=student, slide__in=all_slides)
    progress_data = {progress.slide_id: progress for progress in progress_qs}
    
    context = {
        'course': course,
        'chapters': chapters,
        'progress_data': progress_data,
        'overall_progress': overall_progress,
        'total_slides': total_slides_count,
        'completed_slides': completed_slides_count,
        'in_progress_count': in_progress_count,  # 추가
    }
    
    return render(request, 'student/learning_course.html', context)

@login_required
@student_required
def learning_course_view_0619(request, course_id):
    """코스 학습 페이지 (통계 로직 수정)"""
    student = request.user.student
    course = get_object_or_404(Course, id=course_id)
    
    has_permission = CourseAssignment.objects.filter(
        course=course,
    ).filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).exists()
    
    if not has_permission:
        messages.error(request, '해당 코스에 접근 권한이 없습니다.')
        return redirect('student:course_list')
    
    chapters = course.chapters.all().order_by('chapter_order')
    
    all_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject=course, is_active=True)
    total_slides_count = all_slides.count()
    
    completed_slides_count = StudentProgress.objects.filter(
        student=student,
        slide__in=all_slides,
        is_completed=True
    ).count()

    overall_progress = int((completed_slides_count / total_slides_count) * 100) if total_slides_count > 0 else 0

    progress_qs = StudentProgress.objects.filter(student=student, slide__in=all_slides)
    progress_data = {progress.slide_id: progress for progress in progress_qs}
    
    context = {
        'course': course,
        'chapters': chapters,
        'progress_data': progress_data,
        'overall_progress': overall_progress,
        'total_slides': total_slides_count,
        'completed_slides': completed_slides_count,
    }
    
    return render(request, 'student/learning_course.html', context)



@login_required
@student_required
def learning_course_view_0608(request, course_id):
    """코스 학습 페이지 (단순화 버전)"""
    try:
        student = request.user.student
        course = get_object_or_404(Course, id=course_id)
        
        # 권한 확인
        has_permission = CourseAssignment.objects.filter(
            course=course,
        ).filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        ).exists()
        
        if not has_permission:
            messages.error(request, '해당 코스에 접근 권한이 없습니다.')
            return redirect('student:course_list')
        
        # 간단한 쿼리로 데이터 가져오기
        chapters = course.chapters.all().order_by('chapter_order')
        # ★★★ [수정] 코스 전체의 슬라이드 수와 완료된 슬라이드 수를 효율적인 쿼리로 계산 ★★★
        all_slides = ChasiSlide.objects.filter(chasi__sub_chapter__chapter__subject=course, is_active=True)
        total_slides_count = all_slides.count()
        
        completed_slides_count = StudentProgress.objects.filter(
            student=student,
            slide__in=all_slides,
            is_completed=True
        ).count()

        overall_progress = int((completed_slides_count / total_slides_count) * 100) if total_slides_count > 0 else 0
        
        # 각 대단원의 데이터 확인 (디버깅용)
        for chapter in chapters:
            print(f"Chapter: {chapter.chapter_title}")
            for subchapter in chapter.subchapters.filter(subject=course).order_by('sub_chapter_order'):
                print(f"  SubChapter: {subchapter.sub_chapter_title}")
                for chasi in subchapter.chasis.filter(subject=course, is_published=True).order_by('chasi_order'):
                    print(f"    Chasi: {chasi.chasi_title}")
                    slides = chasi.teacher_slides.filter(is_active=True).order_by('slide_number')
                    print(f"      Slides: {slides.count()}")
                    total_slides += slides.count()
                    
                    # 완료된 슬라이드 계산
                    completed = StudentProgress.objects.filter(
                        student=student,
                        slide__in=slides,
                        is_completed=True
                    ).count()
                    completed_slides += completed
        
        # 진도율 계산
        overall_progress = int((completed_slides / total_slides * 100)) if total_slides > 0 else 0
        
        # 진도 데이터
        progress_qs = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course
        ).select_related('slide')
        
        progress_data = {}
        for progress in progress_qs:
            progress_data[progress.slide.id] = progress
        
        context = {
            'course': course,
            'chapters': chapters,
            'progress_data': progress_data,
            'overall_progress': overall_progress,
            'total_slides': total_slides,
            'completed_slides': completed_slides,
            'debug': True,  # 디버깅 모드
        }
        
        return render(request, 'student/learning_course.html', context)
        
    except Exception as e:
        import traceback
        print(f"Error: {str(e)}")
        print(traceback.format_exc())
        messages.error(request, f'오류가 발생했습니다: {str(e)}')
        return redirect('student:course_list')



@login_required
@student_required
def slide_view(request, slide_id):
    """슬라이드 학습 페이지"""
    try:
        student = request.user.student
        
        # 슬라이드 조회
        slide = get_object_or_404(
            ChasiSlide.objects.select_related(
                'chasi__sub_chapter__chapter__subject',
                'content',
                'content_type'
            ),
            id=slide_id
        )
        
        # 코스 가져오기
        course = slide.chasi.sub_chapter.chapter.subject
        
        # 권한 확인
        has_access = CourseAssignment.objects.filter(
            course=course
        ).filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        ).exists()
        
        if not has_access:
            messages.error(request, '해당 슬라이드에 접근 권한이 없습니다.')
            return redirect('student:course_list')
        
        # 진도 체크 및 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'view_count': 0}
        )
        
        # 처음 시작하는 경우
        if not progress.started_at:
            progress.started_at = timezone.now()
        
        # 조회수 증가
        progress.view_count = getattr(progress, 'view_count', 0) + 1
        progress.save()
        
        # 기존 답안 확인 - 가장 최근 답안
        existing_answer = StudentAnswer.objects.filter(
            student=student,
            slide=slide
        ).order_by('-submitted_at').first()

        # 🔧 기존 답안 JSON 처리 (간단한 버전)
        existing_answer_json = None
        if existing_answer and existing_answer.answer:
            try:
                # answer 필드가 문자열이면 그대로 사용, dict면 JSON으로 변환
                if isinstance(existing_answer.answer, str):
                    existing_answer_json = existing_answer.answer
                else:
                    existing_answer_json = json.dumps(existing_answer.answer)
                
                print(f"✅ 기존 답안 JSON 준비 완료: {existing_answer_json[:100]}...")
                
            except Exception as e:
                print(f"❌ 기존 답안 JSON 처리 실패: {e}")
                existing_answer_json = None

        # # 🔧 기존 답안 데이터 파싱 (JSON 파싱 오류 해결)
        # existing_answer_data = None
        # if existing_answer and existing_answer.answer:
        #     try:
        #         if isinstance(existing_answer.answer, str):
        #             existing_answer_data = json.loads(existing_answer.answer)
        #         elif isinstance(existing_answer.answer, dict):
        #             existing_answer_data = existing_answer.answer
        #         else:
        #             print(f"⚠️ 예상치 못한 답안 데이터 타입: {type(existing_answer.answer)}")
                    
        #         print(f"✅ 답안 데이터 파싱 성공: {slide.content_type.type_name}")
                
        #     except (json.JSONDecodeError, TypeError) as e:
        #         print(f"❌ 답안 데이터 파싱 실패: {e}")
        #         existing_answer_data = None

        # 이미 정답을 맞혔는지 여부를 확인
        is_already_correct = False
        if existing_answer and existing_answer.is_correct:
            is_already_correct = True
        
        # 노트 가져오기
        note = StudentNote.objects.filter(
            student=student,
            slide=slide
        ).first()

        # POST 요청 처리 - 문제가 없는 콘텐츠의 '완료' 버튼 처리
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'complete':
                # 문제가 없는 슬라이드의 진도 완료 처리
                if not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()
                    messages.success(request, '학습을 완료했습니다.')
                    
                # 다음 슬라이드로 이동
                next_slide = ChasiSlide.objects.filter(
                    chasi=slide.chasi,
                    slide_number__gt=slide.slide_number
                ).order_by('slide_number').first()
                
                if next_slide:
                    return redirect('student:slide_view', slide_id=next_slide.id)
                else:
                    return redirect('student:learning_course', course_id=course.id)
      
        # 이전/다음 슬라이드
        prev_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__lt=slide.slide_number
        ).order_by('-slide_number').first()
        
        next_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__gt=slide.slide_number
        ).order_by('slide_number').first()
        
        # 현재 슬라이드 위치
        total_slides_in_chasi = slide.chasi.teacher_slides.count()
        
        # 객관식 옵션 처리 - content의 meta_data 필드 확인
        options = []
        if slide.content_type.type_name == 'multiple-choice':
            if hasattr(slide.content, 'meta_data') and isinstance(slide.content.meta_data, dict):
                options = slide.content.meta_data.get('options', [])
        
        physical_result = None
        if slide.content_type.type_name == 'physical_record' and existing_answer:
            try:
                physical_result = StudentPhysicalResult.objects.filter(
                    student=student,
                    slide=slide
                ).first()
            except:
                pass

        # OX 퀴즈용 추가 데이터 처리
        ox_quiz_data = None
        if slide.content_type.type_name == 'ox-quiz':
            try:
                answer_data = json.loads(slide.content.answer)
                ox_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                ox_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }

        # Choice 퀴즈용 추가 데이터 처리
        choice_quiz_data = None
        if slide.content_type.type_name == 'choice':
            try:
                answer_data = json.loads(slide.content.answer)
                choice_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                choice_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }
        
        # drag 타입 특별 처리 - choice형과 동일한 구조
        drag_quiz_data = None
        if slide.content_type.type_name == 'drag':
            try:
                correct_answer_data = json.loads(slide.content.correct_answer)
                solution = correct_answer_data.get('solution', '')
                drag_quiz_data = {
                    'has_solution': bool(solution),
                    'solution': solution
                }
            except:
                drag_quiz_data = {'has_solution': False, 'solution': ''}
                
        # 🔧 line_matching 타입 특별 처리 (개선된 버전)
        line_quiz_data = None
        if slide.content_type.type_name == 'line_matching':
            try:
                correct_answer_data = json.loads(slide.content.answer)
                solution = correct_answer_data.get('solution', '')
                line_quiz_data = {
                    'has_solution': bool(solution),
                    'solution': solution,
                    'correct_answer': correct_answer_data.get('answer', {}),
                    'total_connections': len(correct_answer_data.get('answer', {}))
                }
                print(f"✅ line_matching 데이터 준비 완료: {line_quiz_data}")
            except Exception as e:
                print(f"❌ line_matching 데이터 파싱 실패: {e}")
                line_quiz_data = {
                    'has_solution': False, 
                    'solution': '',
                    'correct_answer': {},
                    'total_connections': 0
                }

        context = {
            'slide': slide,
            'progress': progress,
            'existing_answer': existing_answer,
            'existing_answer_data': existing_answer_json, 
            'existing_answer_json': existing_answer_json,  # 🔧 파싱된 답안 데이터 추가
            'note': note,
            'prev_slide': prev_slide,
            'next_slide': next_slide,
            'total_slides_in_chasi': total_slides_in_chasi,
            'options': options,
            'course': course,
            'is_already_correct': is_already_correct,
            'physical_result': physical_result,
            'ox_quiz_data': ox_quiz_data,
            'choice_quiz_data': choice_quiz_data,
            'drag_quiz_data': drag_quiz_data,
            'line_quiz_data': line_quiz_data,
        }
        
        return render(request, 'student/slide_view.html', context)
        
    except Exception as e:
        import traceback
        print(f"Error in slide_view: {str(e)}")
        print(traceback.format_exc())
        messages.error(request, f'오류가 발생했습니다: {str(e)}')
        return redirect('student:course_list')


@login_required
@student_required
def slide_view_0703(request, slide_id):
    """슬라이드 학습 페이지"""
    try:
        student = request.user.student
        
        # 슬라이드 조회
        slide = get_object_or_404(
            ChasiSlide.objects.select_related(
                'chasi__sub_chapter__chapter__subject',
                'content',
                'content_type'
            ),
            id=slide_id
        )
        
        # 코스 가져오기
        course = slide.chasi.sub_chapter.chapter.subject
        
        # 권한 확인
        has_access = CourseAssignment.objects.filter(
            course=course
        ).filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        ).exists()
        
        if not has_access:
            messages.error(request, '해당 슬라이드에 접근 권한이 없습니다.')
            return redirect('student:course_list')
        
        # 진도 체크 및 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'view_count': 0}
        )
        
        # 처음 시작하는 경우
        if not progress.started_at:
            progress.started_at = timezone.now()
        
        # 조회수 증가
        progress.view_count = getattr(progress, 'view_count', 0) + 1
        progress.save()
        
        # 기존 답안 확인 - 가장 최근 답안
        existing_answer = StudentAnswer.objects.filter(
            student=student,
            slide=slide
        ).order_by('-submitted_at').first()

        # 이미 정답을 맞혔는지 여부를 확인
        is_already_correct = False
        if existing_answer and existing_answer.is_correct:
            is_already_correct = True
        
        # 노트 가져오기
        note = StudentNote.objects.filter(
            student=student,
            slide=slide
        ).first()

        # POST 요청 처리 - 문제가 없는 콘텐츠의 '완료' 버튼 처리
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'complete':
                # 문제가 없는 슬라이드의 진도 완료 처리
                if not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()
                    messages.success(request, '학습을 완료했습니다.')
                    
                # 다음 슬라이드로 이동
                next_slide = ChasiSlide.objects.filter(
                    chasi=slide.chasi,
                    slide_number__gt=slide.slide_number
                ).order_by('slide_number').first()
                
                if next_slide:
                    return redirect('student:slide_view', slide_id=next_slide.id)
                else:
                    return redirect('student:learning_course', course_id=course.id)
      
        # 이전/다음 슬라이드
        prev_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__lt=slide.slide_number
        ).order_by('-slide_number').first()
        
        next_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__gt=slide.slide_number
        ).order_by('slide_number').first()
        
        # 현재 슬라이드 위치
        total_slides_in_chasi = slide.chasi.teacher_slides.count()
        
        # 객관식 옵션 처리 - content의 meta_data 필드 확인
        options = []
        if slide.content_type.type_name == 'multiple-choice':
            if hasattr(slide.content, 'meta_data') and isinstance(slide.content.meta_data, dict):
                options = slide.content.meta_data.get('options', [])
        
        physical_result = None
        if slide.content_type.type_name == 'physical_record' and existing_answer:
            try:
                physical_result = StudentPhysicalResult.objects.filter(
                    student=student,
                    slide=slide
                ).first()
            except:
                pass

        # OX 퀴즈용 추가 데이터 처리
        ox_quiz_data = None
        if slide.content_type.type_name == 'ox-quiz':
            try:
                answer_data = json.loads(slide.content.answer)
                ox_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                ox_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }

        # Choice 퀴즈용 추가 데이터 처리
        choice_quiz_data = None
        if slide.content_type.type_name == 'choice':
            try:
                answer_data = json.loads(slide.content.answer)
                choice_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                choice_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }
        
        # drag 타입 특별 처리 - choice형과 동일한 구조
        drag_quiz_data = None
        if slide.content_type.type_name == 'drag':
            try:
                correct_answer_data = json.loads(slide.content.correct_answer)
                solution = correct_answer_data.get('solution', '')
                drag_quiz_data = {
                    'has_solution': bool(solution),
                    'solution': solution
                }
            except:
                drag_quiz_data = {'has_solution': False, 'solution': ''}
        line_quiz_data = None
        if slide.content_type.type_name == 'line_matching':
            try:
                correct_answer_data = json.loads(slide.content.answer)
                solution = correct_answer_data.get('solution', '')
                line_quiz_data = {
                    'has_solution': bool(solution),
                    'solution': solution
                }
            except:
                line_quiz_data = {'has_solution': False, 'solution': ''}

        context = {
            'slide': slide,
            'progress': progress,
            'existing_answer': existing_answer,
            'note': note,
            'prev_slide': prev_slide,
            'next_slide': next_slide,
            'total_slides_in_chasi': total_slides_in_chasi,
            'options': options,
            'course': course,
            'is_already_correct': is_already_correct,
            'physical_result': physical_result,
            'ox_quiz_data': ox_quiz_data,
            'choice_quiz_data': choice_quiz_data,
            'drag_quiz_data': drag_quiz_data,
            'line_quiz_data': line_quiz_data,  # 이 줄 추가
        }
        
        return render(request, 'student/slide_view.html', context)
        
    except Exception as e:
        import traceback
        print(f"Error in slide_view: {str(e)}")
        print(traceback.format_exc())
        messages.error(request, f'오류가 발생했습니다: {str(e)}')
        return redirect('student:course_list')


@login_required
@student_required
def slide_view_0703(request, slide_id):
    """슬라이드 학습 페이지"""
    try:
        student = request.user.student
        
        # 슬라이드 조회
        slide = get_object_or_404(
            ChasiSlide.objects.select_related(
                'chasi__sub_chapter__chapter__subject',
                'content',
                'content_type'
            ),
            id=slide_id
        )
        
        # 코스 가져오기
        course = slide.chasi.sub_chapter.chapter.subject
        
        # 권한 확인
        has_access = CourseAssignment.objects.filter(
            course=course
        ).filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        ).exists()
        
        if not has_access:
            messages.error(request, '해당 슬라이드에 접근 권한이 없습니다.')
            return redirect('student:course_list')
        
        # 진도 체크 및 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'view_count': 0}
        )
        
        # 처음 시작하는 경우
        if not progress.started_at:
            progress.started_at = timezone.now()
        
        # 조회수 증가
        progress.view_count = getattr(progress, 'view_count', 0) + 1
        progress.save()
        
        # 기존 답안 확인 - 가장 최근 답안
        existing_answer = StudentAnswer.objects.filter(
            student=student,
            slide=slide
        ).order_by('-submitted_at').first()

         # ★★★ 추가된 로직 ★★★
        # 이미 정답을 맞혔는지 여부를 확인
        is_already_correct = False
        if existing_answer and existing_answer.is_correct:
            is_already_correct = True
        
        # 노트 가져오기
        note = StudentNote.objects.filter(
            student=student,
            slide=slide
        ).first()

        # ★★★ POST 요청 처리 - 문제가 없는 콘텐츠의 '완료' 버튼 처리 ★★★
        if request.method == 'POST':
            action = request.POST.get('action')
            
            if action == 'complete':
                # 문제가 없는 슬라이드의 진도 완료 처리
                if not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()
                    messages.success(request, '학습을 완료했습니다.')
                    
                # 다음 슬라이드로 이동
                next_slide = ChasiSlide.objects.filter(
                    chasi=slide.chasi,
                    slide_number__gt=slide.slide_number
                ).order_by('slide_number').first()
                
                if next_slide:
                    return redirect('student:slide_view', slide_id=next_slide.id)
                else:
                    return redirect('student:learning_course', course_id=course.id)
      
        # 이전/다음 슬라이드
        prev_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__lt=slide.slide_number
        ).order_by('-slide_number').first()
        
        next_slide = ChasiSlide.objects.filter(
            chasi=slide.chasi,
            slide_number__gt=slide.slide_number
        ).order_by('slide_number').first()
        
        # 현재 슬라이드 위치
        total_slides_in_chasi = slide.chasi.teacher_slides.count()
        
        # 객관식 옵션 처리 - content의 meta_data 필드 확인
        options = []
        if slide.content_type.type_name == 'multiple-choice':
            # content.meta_data가 딕셔너리인지 확인
            if hasattr(slide.content, 'meta_data') and isinstance(slide.content.meta_data, dict):
                options = slide.content.meta_data.get('options', [])
        
        physical_result = None
        if slide.content_type.type_name == 'physical_record' and existing_answer:
            try:
                from .models import StudentPhysicalResult
                physical_result = StudentPhysicalResult.objects.filter(
                    student=student,
                    slide=slide
                ).first()
            except:
                pass

        # OX 퀴즈용 추가 데이터 처리
        ox_quiz_data = None
        if slide.content_type.type_name == 'ox-quiz':
            try:
                # 정답 데이터 파싱
                answer_data = json.loads(slide.content.answer)
                ox_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                ox_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }

        # Choice 퀴즈용 추가 데이터 처리
        choice_quiz_data = None
        if slide.content_type.type_name == 'choice':
            try:
                # 정답 데이터 파싱
                answer_data = json.loads(slide.content.answer)
                choice_quiz_data = {
                    'correct_answer': answer_data.get('answer', ''),
                    'solution': answer_data.get('solution', ''),
                    'has_solution': bool(answer_data.get('solution', '').strip())
                }
            except (json.JSONDecodeError, AttributeError):
                choice_quiz_data = {
                    'correct_answer': slide.content.answer,
                    'solution': '',
                    'has_solution': False
                }
        # drag 타입 특별 처리 - choice형과 동일한 구조
        drag_quiz_data = None
        if slide.content_type.type_name == 'drag':
            try:
                correct_answer_data = json.loads(slide.content.correct_answer)
                solution = correct_answer_data.get('solution', '')
                drag_quiz_data = {
                    'has_solution': bool(solution),
                    'solution': solution
                }
            except:
                drag_quiz_data = {'has_solution': False, 'solution': ''}


        
        context = {
            'slide': slide,
            'progress': progress,
            'existing_answer': existing_answer,
            'note': note,
            'prev_slide': prev_slide,
            'next_slide': next_slide,
            'total_slides_in_chasi': total_slides_in_chasi,
            'options': options,
            'course': course,
            'is_already_correct': is_already_correct, # ★★★ 컨텍스트에 추가 ★★★
            'physical_result': physical_result,  # ★★★ 추가 ★★★
            'ox_quiz_data': ox_quiz_data,  # ★★★ OX 퀴즈 데이터 추가 ★★★
            'choice_quiz_data': choice_quiz_data,  # ★★★ Choice 퀴즈 데이터 추가 ★★★
            'drag_quiz_data': drag_quiz_data,
        }
        
        return render(request, 'student/slide_view.html', context)
        
    except Exception as e:
        import traceback
        print(f"Error in slide_view: {str(e)}")
        print(traceback.format_exc())
        messages.error(request, f'오류가 발생했습니다: {str(e)}')
        return redirect('student:course_list')


@login_required
@student_required
def progress_view(request):
    """학습 진도 현황"""
    student = request.user.student
    
    # 코스별 진도
    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).select_related('course')
    
    course_progress = []
    total_all_slides = 0
    total_all_completed = 0
    
    for assignment in assigned_courses:
        course = assignment.course
        
        # 전체 슬라이드 수
        total_slides = ChasiSlide.objects.filter(
            chasi__sub_chapter__chapter__subject=course
        ).count()
        
        # 완료한 슬라이드 수
        completed_slides = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            is_completed=True
        ).count()
        
        # 평균 점수
        avg_score_result = StudentAnswer.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            score__isnull=False
        ).aggregate(avg=Avg('score'))
        
        avg_score = avg_score_result['avg'] if avg_score_result['avg'] else 0
        
        # 진도율 계산
        progress_percent = 0
        if total_slides > 0:
            progress_percent = int((completed_slides / total_slides) * 100)
        
        # 진행 중인 슬라이드 수
        in_progress = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            is_completed=False,
            started_at__isnull=False
        ).count()
        
        # 미시작 슬라이드 수
        not_started = total_slides - completed_slides - in_progress
        
        # 전체 통계를 위한 누적
        total_all_slides += total_slides
        total_all_completed += completed_slides
        
        course_progress.append({
            'course': course,
            'total_slides': total_slides,
            'completed_slides': completed_slides,
            'in_progress': in_progress,
            'not_started': not_started,
            'progress_percent': progress_percent,
            'avg_score': round(float(avg_score), 1) if avg_score else 0,
            # 진도에 따른 색상 클래스 추가
            'progress_color': 'green' if progress_percent >= 80 else 'blue' if progress_percent >= 50 else 'yellow' if progress_percent > 0 else 'gray'
        })
    
    # 전체 진도율 계산
    overall_progress_percent = 0
    if total_all_slides > 0:
        overall_progress_percent = int((total_all_completed / total_all_slides) * 100)
    
    # 최근 학습 기록
    recent_activities = StudentProgress.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-started_at')[:20]
    
    # 학습 시간 계산 (실제로는 더 정교한 로직 필요)
    total_study_sessions = StudentProgress.objects.filter(
        student=student,
        completed_at__isnull=False
    ).count()
    
    # 평균 학습 시간 (분 단위로 가정)
    avg_session_time = 15  # 슬라이드당 평균 15분 가정
    total_study_hours = int((total_study_sessions * avg_session_time) / 60)
    
    # 완료한 코스 수
    completed_courses = 0
    for progress in course_progress:
        if progress['progress_percent'] == 100:
            completed_courses += 1
    
    # 평균 점수 계산
    all_scores = StudentAnswer.objects.filter(
        student=student,
        score__isnull=False
    ).aggregate(avg=Avg('score'))
    overall_avg_score = round(float(all_scores['avg']), 1) if all_scores['avg'] else 0
    
    context = {
        'course_progress': course_progress,
        'recent_activities': recent_activities,
        'total_study_time': total_study_hours,
        'overall_progress_percent': overall_progress_percent,
        'total_all_slides': total_all_slides,
        'total_all_completed': total_all_completed,
        'completed_courses': completed_courses,
        'total_courses': len(course_progress),
        'overall_avg_score': overall_avg_score,
    }
    
    return render(request, 'student/progress.html', context)

@login_required
@student_required
def progress_view_0608(request):
    """학습 진도 현황"""
    student = request.user.student
    
    # 코스별 진도
    assigned_courses = CourseAssignment.objects.filter(
        Q(assigned_class=student.school_class) | Q(assigned_student=student)
    ).select_related('course')
    
    course_progress = []
    for assignment in assigned_courses:
        course = assignment.course
        
        # 전체 슬라이드 수
        total_slides = ChasiSlide.objects.filter(
            chasi__sub_chapter__chapter__subject=course
        ).count()
        
        # 완료한 슬라이드 수
        completed_slides = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            is_completed=True
        ).count()
        
        # 평균 점수
        avg_score_result = StudentAnswer.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            score__isnull=False
        ).aggregate(avg=Avg('score'))
        
        avg_score = avg_score_result['avg'] if avg_score_result['avg'] else 0
        
        # 진도율 계산
        progress_percent = 0
        if total_slides > 0:
            progress_percent = int((completed_slides / total_slides) * 100)
        
        # 진행 중인 슬라이드 수
        in_progress = StudentProgress.objects.filter(
            student=student,
            slide__chasi__sub_chapter__chapter__subject=course,
            is_completed=False,
            started_at__isnull=False
        ).count()
        
        # 미시작 슬라이드 수
        not_started = total_slides - completed_slides - in_progress
        
        course_progress.append({
            'course': course,
            'total_slides': total_slides,
            'completed_slides': completed_slides,
            'in_progress': in_progress,
            'not_started': not_started,
            'progress_percent': progress_percent,
            'avg_score': round(float(avg_score), 1) if avg_score else 0,
        })
    
    # 최근 학습 기록
    recent_activities = StudentProgress.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-started_at')[:20]
    
    # 학습 통계
    total_study_time = StudentProgress.objects.filter(
        student=student,
        completed_at__isnull=False
    ).count()  # 실제로는 시간 계산 로직 필요
    
    context = {
        'course_progress': course_progress,
        'recent_activities': recent_activities,
        'total_study_time': total_study_time,
    }
    
    return render(request, 'student/progress.html', context)


##################### 신버전 0703 ########################
@login_required
@student_required
@require_POST
def check_answer(request):
    """
    학생 답안을 채점하고 저장하는 AJAX 뷰.
    drag 타입 처리 개선
    """
    try:
        # 1. 공통 데이터 가져오기
        content_id = request.POST.get('content_id')
        slide_id = request.POST.get('slide_id')

        if not all([content_id, slide_id]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터가 누락되었습니다.',
            }, status=400)

        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )
        content = slide.content
        content_type = slide.content_type.type_name

        print(f"🎯 채점 시작: {content_type} 타입, 학생: {student.id}, 슬라이드: {slide_id}")

        # StudentProgress 처리
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. drag 타입 처리
        if content_type == 'drag':
            return handle_drag_answer(request, student, slide, content, progress)
        
        # 3. 다른 타입들 처리 (기존 코드)
        elif content_type == 'ox-quiz':
            return handle_ox_quiz_answer(request, student, slide, content, progress)
        
        elif content_type == 'selection':
            return handle_selection_answer(request, student, slide, content, progress)
        
        elif content_type == 'choice':
            return handle_choice_answer(request, student, slide, content, progress)
        
        elif content_type in ['multiple-choice', 'short-answer']:
            return handle_simple_answer(request, student, slide, content, progress)
        
        elif content_type == 'line_matching':
            # return handle_line_matching_answer_improved(request, student, slide, content, progress)
            return handle_line_matching_answer(request, student, slide, content, progress)
        
        else:
            return JsonResponse({
                'status': 'error',
                'message': f"지원하지 않는 문제 유형입니다: {content_type}"
            }, status=400)

    except Exception as e:
        import traceback
        print(f"❌ check_answer 오류: {str(e)}")
        print(f"🔍 트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)


def handle_drag_answer(request, student, slide, content, progress):
    """드래그 타입 답안 처리 (개선된 버전)"""
    try:
        # 1. 학생 답안 파싱
        student_answer_json = request.POST.get('student_answer', '').strip()
        if not student_answer_json:
            return JsonResponse({
                'status': 'error',
                'message': '답안이 선택되지 않았습니다.'
            }, status=400)

        try:
            student_state = json.loads(student_answer_json)
            print(f"📝 학생 답안: {student_state}")
        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': '답안 형식이 올바르지 않습니다.'
            }, status=400)

        # 2. 정답 데이터 파싱
        try:
            correct_answer_data = json.loads(content.answer)
            correct_answer = correct_answer_data.get('answer', {})
            solution = correct_answer_data.get('solution', '')
            print(f"🎯 정답: {correct_answer}")
            print(f"💡 해설: {solution}")
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"❌ 정답 파싱 오류: {e}")
            return JsonResponse({
                'status': 'error',
                'message': '정답 데이터를 읽을 수 없습니다.'
            }, status=500)

        # 3. 채점 수행
        is_correct = grade_drag_answer(student_state, correct_answer)
        score = 100.0 if is_correct else 0.0
        
        print(f"📊 채점 결과: {'정답' if is_correct else '오답'} (점수: {score})")

        # 4. 답안 저장
        answer_data = {
            'selected_answer': student_state,
            'correct_answer': correct_answer,
            'solution': solution,
            'question_type': 'drag',
            'submitted_at': timezone.now().isoformat()
        }

        student_answer_obj, created = StudentAnswer.objects.update_or_create(
            student=student,
            slide=slide,
            defaults={
                'answer': answer_data,
                'is_correct': is_correct,
                'score': score,
                'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
            }
        )

        print(f"💾 답안 {'생성' if created else '업데이트'}: ID {student_answer_obj.id}")

        # 5. 정답인 경우 진도 완료 처리
        if is_correct and not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = timezone.now()
            progress.save()
            print(f"✅ 진도 완료 처리")

        # 6. 응답 데이터 구성
        response_data = {
            'status': 'success',
            'is_correct': is_correct,
            'correct_answer': correct_answer,
            'student_answer': student_state,
            'score': score,
            'solution': solution,
            'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
            'feedback': student_answer_obj.feedback,
            'answer_details': {
                'total_zones': len(correct_answer) if isinstance(correct_answer, dict) else 1,
                'correct_zones': sum(1 for k, v in correct_answer.items() 
                                   if k in student_state and str(student_state[k]) == str(v)) 
                                if isinstance(correct_answer, dict) else (1 if is_correct else 0)
            }
        }

        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(f"❌ handle_drag_answer 오류: {str(e)}")
        print(f"🔍 트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'드래그 답안 처리 중 오류가 발생했습니다: {str(e)}'
        }, status=500)


def grade_drag_answer(student_state, correct_answer):
    """
    드래그 답안 채점 함수 (개선된 버전)
    
    Args:
        student_state (dict): 학생이 제출한 답안 상태 {"zone1": "1", "zone2": "3"}
        correct_answer (dict): 정답 데이터 {"zone1": "1", "zone2": "3"}
    
    Returns:
        bool: 정답 여부
    """
    try:
        print(f"🔍 채점 시작:")
        print(f"   학생 답안: {student_state}")
        print(f"   정답: {correct_answer}")
        
        # 1. 기본 유효성 검사
        if not isinstance(student_state, dict) or not isinstance(correct_answer, dict):
            print(f"❌ 답안 형식 오류: 학생({type(student_state)}), 정답({type(correct_answer)})")
            return False
        
        # 2. 존(zone) 개수 확인
        if len(student_state) != len(correct_answer):
            print(f"❌ 답안 개수 불일치: 학생({len(student_state)}), 정답({len(correct_answer)})")
            return False
        
        # 3. 각 존별 정답 확인
        for zone_id, correct_value in correct_answer.items():
            if zone_id not in student_state:
                print(f"❌ 누락된 존: {zone_id}")
                return False
            
            student_value = str(student_state[zone_id]).strip()
            correct_value_str = str(correct_value).strip()
            
            if student_value != correct_value_str:
                print(f"❌ {zone_id}: '{student_value}' != '{correct_value_str}'")
                return False
            else:
                print(f"✅ {zone_id}: '{student_value}' == '{correct_value_str}'")
        
        print(f"🎉 전체 정답!")
        return True
        
    except Exception as e:
        print(f"❌ 채점 중 오류: {e}")
        return False


def handle_ox_quiz_answer(request, student, slide, content, progress):
    """OX 퀴즈 답안 처리"""
    student_answer_str = request.POST.get('student_answer', '').strip()
    if not student_answer_str:
        return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

    try:
        correct_answer_data = json.loads(content.answer)
        correct_answer = correct_answer_data.get('answer', '').strip()
        solution = correct_answer_data.get('solution', '')
    except (json.JSONDecodeError, AttributeError):
        correct_answer = content.answer.strip()
        solution = '자동 채점 완료'

    is_correct = (student_answer_str == correct_answer)
    score = 100.0 if is_correct else 0.0
    
    answer_data = {
        'selected_answer': student_answer_str,
        'correct_answer': correct_answer,
        'solution': solution,
        'question_type': 'ox-quiz'
    }

    student_answer_obj, created = StudentAnswer.objects.update_or_create(
        student=student,
        slide=slide,
        defaults={
            'answer': answer_data,
            'is_correct': is_correct,
            'score': score,
            'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
        }
    )

    if is_correct and not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = timezone.now()
        progress.save()

    return JsonResponse({
        'status': 'success',
        'is_correct': is_correct,
        'correct_answer': correct_answer,
        'student_answer': student_answer_str,
        'score': score,
        'solution': solution,
        'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
        'feedback': student_answer_obj.feedback,
    })


def handle_selection_answer(request, student, slide, content, progress):
    """선택형 퀴즈 답안 처리"""
    student_answer_str = request.POST.get('student_answer', '').strip()
    if not student_answer_str:
        return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

    try:
        correct_answer_data = json.loads(content.answer)
        correct_answer = correct_answer_data.get('answer', '').strip()
        solution = correct_answer_data.get('solution', '')
    except (json.JSONDecodeError, AttributeError):
        correct_answer = content.answer.strip()
        solution = '자동 채점 완료'

    is_correct = (student_answer_str == correct_answer)
    score = 100.0 if is_correct else 0.0
    
    answer_data = {
        'selected_answer': student_answer_str,
        'correct_answer': correct_answer,
        'solution': solution,
        'question_type': 'selection'
    }

    student_answer_obj, created = StudentAnswer.objects.update_or_create(
        student=student,
        slide=slide,
        defaults={
            'answer': answer_data,
            'is_correct': is_correct,
            'score': score,
            'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
        }
    )

    if is_correct and not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = timezone.now()
        progress.save()

    return JsonResponse({
        'status': 'success',
        'is_correct': is_correct,
        'correct_answer': correct_answer,
        'student_answer': student_answer_str,
        'score': score,
        'solution': solution,
        'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
        'feedback': student_answer_obj.feedback,
    })


def handle_choice_answer(request, student, slide, content, progress):
    """일반 선택형 퀴즈 답안 처리"""
    return handle_selection_answer(request, student, slide, content, progress)


def handle_simple_answer(request, student, slide, content, progress):
    """단순 답안 처리 (multiple-choice, short-answer)"""
    student_answer_str = request.POST.get('student_answer', '').strip()
    if not student_answer_str:
        return JsonResponse({'status': 'error', 'message': '답안이 입력되지 않았습니다.'}, status=400)

    correct_answer = parse_correct_answer(content.answer)
    is_correct = (student_answer_str == correct_answer)
    score = 100.0 if is_correct else 0.0
    
    answer_data = {
        'selected_answer': student_answer_str,
        'correct_answer': correct_answer,
    }

    student_answer_obj, created = StudentAnswer.objects.update_or_create(
        student=student,
        slide=slide,
        defaults={
            'answer': answer_data,
            'is_correct': is_correct,
            'score': score,
            'feedback': '자동 채점 완료',
        }
    )

    if is_correct and not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = timezone.now()
        progress.save()

    return JsonResponse({
        'status': 'success',
        'is_correct': is_correct,
        'correct_answer': correct_answer,
        'student_answer': student_answer_str,
        'score': score,
        'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
        'feedback': student_answer_obj.feedback,
    })


def handle_line_matching_answer(request, student, slide, content, progress):
    """선 매칭(line-matching) 타입 답안 처리 (다양한 채점 이벤트 지원)"""
    try:
        # 1. 학생 답안 파싱
        student_answer_json = request.POST.get('student_answer', '').strip()
        if not student_answer_json:
            return JsonResponse({
                'status': 'error',
                'message': '연결된 답안이 없습니다.'
            }, status=400)

        try:
            student_connections = json.loads(student_answer_json)
            print(f"📝 학생 연결: {student_connections}")
        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'message': '답안 형식이 올바르지 않습니다.'
            }, status=400)

        # 2. 정답 데이터 파싱
        try:
            correct_answer_data = json.loads(content.answer)
            correct_connections = correct_answer_data.get('answer', {})
            solution = correct_answer_data.get('solution', '')
            print(f"🎯 정답 연결: {correct_connections}")
            print(f"💡 해설: {solution}")
        except (json.JSONDecodeError, AttributeError) as e:
            print(f"❌ 정답 파싱 오류: {e}")
            return JsonResponse({
                'status': 'error',
                'message': '정답 데이터를 읽을 수 없습니다.'
            }, status=500)

        # 3. 다양한 채점 방식 수행
        grading_result = grade_line_matching_answer(student_connections, correct_connections)
        
        # 채점 결과 분석
        total_connections = len(correct_connections)
        correct_count = grading_result['correct_count']
        incorrect_count = grading_result['incorrect_count']
        missing_count = grading_result['missing_count']
        extra_count = grading_result['extra_count']
        
        # 점수 계산 (부분 점수 지원)
        if correct_count == total_connections and incorrect_count == 0 and extra_count == 0:
            # 완전 정답
            score = 100.0
            is_correct = True
            result_type = 'perfect'
        elif correct_count > 0:
            # 부분 정답 (정답 연결 비율에 따라 점수 부여)
            base_score = (correct_count / total_connections) * 80  # 80%까지는 정답 비율로
            penalty = (incorrect_count + extra_count) * 5  # 잘못된 연결당 5점 감점
            score = max(base_score - penalty, 0)
            is_correct = False
            result_type = 'partial'
        else:
            # 전체 오답
            score = 0.0
            is_correct = False
            result_type = 'incorrect'
        
        print(f"📊 채점 결과: 정답({correct_count}) 오답({incorrect_count}) 누락({missing_count}) 추가({extra_count})")
        print(f"📊 최종 점수: {score}점 ({'완전정답' if is_correct else result_type})")

        # 4. 답안 저장 (상세 정보 포함)
        answer_data = {
            'selected_answer': student_connections,
            'correct_answer': correct_connections,
            'solution': solution,
            'question_type': 'line-matching',
            'submitted_at': timezone.now().isoformat(),
            'grading_details': {
                'total_connections': total_connections,
                'correct_count': correct_count,
                'incorrect_count': incorrect_count,
                'missing_count': missing_count,
                'extra_count': extra_count,
                'result_type': result_type,
                'individual_results': grading_result['individual_results']
            }
        }

        student_answer_obj, created = StudentAnswer.objects.update_or_create(
            student=student,
            slide=slide,
            defaults={
                'answer': answer_data,
                'is_correct': is_correct,
                'score': score,
                'feedback': generate_line_feedback(grading_result, result_type, solution),
            }
        )

        print(f"💾 답안 {'생성' if created else '업데이트'}: ID {student_answer_obj.id}")

        # 5. 진도 완료 처리 (완전 정답이거나 부분 점수가 70점 이상일 때)
        if (is_correct or score >= 70) and not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = timezone.now()
            progress.save()
            print(f"✅ 진도 완료 처리 (점수: {score})")

        # 6. 응답 데이터 구성 (클라이언트에서 활용할 상세 정보 포함)
        response_data = {
            'status': 'success',
            'is_correct': is_correct,
            'score': score,
            'result_type': result_type,
            'correct_answer': correct_connections,
            'student_answer': student_connections,
            'solution': solution,
            'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
            'feedback': student_answer_obj.feedback,
            'grading_details': {
                'total_connections': total_connections,
                'correct_count': correct_count,
                'incorrect_count': incorrect_count,
                'missing_count': missing_count,
                'extra_count': extra_count,
                'accuracy_rate': round((correct_count / total_connections) * 100, 1) if total_connections > 0 else 0,
                'individual_results': grading_result['individual_results']
            },
            'encouragement': generate_encouragement_message(result_type, correct_count, total_connections)
        }

        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(f"❌ handle_line_matching_answer 오류: {str(e)}")
        print(f"🔍 트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'선 매칭 답안 처리 중 오류가 발생했습니다: {str(e)}'
        }, status=500)


def grade_line_matching_answer(student_connections, correct_connections):
    """
    선 매칭 답안 채점 함수 (상세한 분석 정보 제공)
    
    Args:
        student_connections (dict): 학생이 연결한 답안 {"left1": "right2", "left2": "right1"}
        correct_connections (dict): 정답 연결 {"left1": "right1", "left2": "right2"}
    
    Returns:
        dict: 상세한 채점 결과
    """
    try:
        print(f"🔍 선 매칭 채점 시작:")
        print(f"   학생 연결: {student_connections}")
        print(f"   정답 연결: {correct_connections}")
        
        # 채점 결과 초기화
        result = {
            'correct_count': 0,
            'incorrect_count': 0,
            'missing_count': 0,
            'extra_count': 0,
            'individual_results': {}
        }
        
        # 1. 정답 연결 검사
        for left_id, correct_right_id in correct_connections.items():
            if left_id in student_connections:
                student_right_id = student_connections[left_id]
                if student_right_id == correct_right_id:
                    # 정답 연결
                    result['correct_count'] += 1
                    result['individual_results'][left_id] = {
                        'status': 'correct',
                        'student_answer': student_right_id,
                        'correct_answer': correct_right_id
                    }
                    print(f"   ✅ {left_id} → {student_right_id} (정답)")
                else:
                    # 잘못된 연결
                    result['incorrect_count'] += 1
                    result['individual_results'][left_id] = {
                        'status': 'incorrect',
                        'student_answer': student_right_id,
                        'correct_answer': correct_right_id
                    }
                    print(f"   ❌ {left_id} → {student_right_id} (오답, 정답: {correct_right_id})")
            else:
                # 연결하지 않은 항목
                result['missing_count'] += 1
                result['individual_results'][left_id] = {
                    'status': 'missing',
                    'student_answer': None,
                    'correct_answer': correct_right_id
                }
                print(f"   ⭕ {left_id} (연결 안함, 정답: {correct_right_id})")
        
        # 2. 추가 연결 검사 (정답에 없는 연결)
        for left_id, student_right_id in student_connections.items():
            if left_id not in correct_connections:
                result['extra_count'] += 1
                result['individual_results'][left_id] = {
                    'status': 'extra',
                    'student_answer': student_right_id,
                    'correct_answer': None
                }
                print(f"   ➕ {left_id} → {student_right_id} (불필요한 연결)")
        
        print(f"📊 채점 완료: 정답({result['correct_count']}) 오답({result['incorrect_count']}) "
              f"누락({result['missing_count']}) 추가({result['extra_count']})")
        
        return result
        
    except Exception as e:
        print(f"❌ 선 매칭 채점 중 오류: {e}")
        return {
            'correct_count': 0,
            'incorrect_count': 0,
            'missing_count': 0,
            'extra_count': 0,
            'individual_results': {}
        }


def generate_line_feedback(grading_result, result_type, solution):
    """선 매칭 결과에 따른 피드백 생성"""
    correct_count = grading_result['correct_count']
    incorrect_count = grading_result['incorrect_count']
    missing_count = grading_result['missing_count']
    
    if result_type == 'perfect':
        feedback = "🎉 완벽합니다! 모든 연결이 정확해요!"
    elif result_type == 'partial':
        if correct_count > incorrect_count:
            feedback = f"👍 잘했어요! {correct_count}개 정답, {incorrect_count}개 오답입니다."
        else:
            feedback = f"💪 조금 더 힘내세요! {correct_count}개 정답, {incorrect_count}개 오답입니다."
            
        if missing_count > 0:
            feedback += f" {missing_count}개 항목이 연결되지 않았습니다."
    else:
        feedback = "🤔 다시 한번 생각해보세요! 올바른 연결을 찾아보세요."
    
    # 해설이 있으면 추가
    if solution:
        feedback += f"\n\n💡 해설: {solution}"
    
    return feedback


def generate_encouragement_message(result_type, correct_count, total_count):
    """결과에 따른 격려 메시지 생성"""
    if result_type == 'perfect':
        messages = [
            "🌟 완벽한 연결 실력이에요!",
            "🎯 매칭 마스터가 되셨네요!",
            "🏆 최고의 연결 감각입니다!",
            "✨ 완벽한 논리적 사고력이에요!"
        ]
    elif result_type == 'partial':
        if correct_count >= total_count * 0.7:  # 70% 이상
            messages = [
                "👏 훌륭한 시작이에요! 조금만 더!",
                "🌟 좋은 감각이 있어요!",
                "💪 실력이 늘고 있어요!",
                "🎯 거의 다 왔어요!"
            ]
        else:
            messages = [
                "💪 포기하지 마세요! 다시 도전!",
                "🌟 연습하면 더 잘할 수 있어요!",
                "🎯 차근차근 생각해보세요!",
                "✨ 다음엔 더 잘할 거예요!"
            ]
    else:
        messages = [
            "🤔 천천히 다시 생각해보세요!",
            "💪 포기하지 말고 다시 도전!",
            "🌟 연습이 실력을 만들어요!",
            "🎯 힌트를 활용해보세요!"
        ]
    
    import random
    return random.choice(messages)

###################### 신버전 0702 ########################
@login_required
@student_required
@require_POST
def check_answer_0703(request):
    """
    학생 답안을 채점하고 저장하는 AJAX 뷰.
    'ox-quiz' 유형 추가 지원
    """
    try:
        # 1. 공통 데이터 가져오기 및 객체 조회
        content_id = request.POST.get('content_id')
        slide_id = request.POST.get('slide_id')

        if not all([content_id, slide_id]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터(content_id, slide_id)가 누락되었습니다.',
            }, status=400)

        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )
        content = slide.content
        content_type = slide.content_type.type_name

        # 슬라이드와 콘텐츠 ID 일치 여부 확인
        if str(content.id) != content_id:
            return JsonResponse({
                'status': 'error',
                'message': '슬라이드와 콘텐츠 정보가 일치하지 않습니다.',
            }, status=400)
        
        # StudentProgress 가져오기 또는 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. 콘텐츠 유형에 따른 분기 처리
        
        # ----------------------------------------------------------------------
        #  ★★★★★  새로운 'ox-quiz' 유형 처리 (OX 퀴즈)  ★★★★★
        # ----------------------------------------------------------------------
        if content_type == 'ox-quiz':
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

            # 정답 파싱 (JSON 형태로 저장된 정답)
            try:
                correct_answer_data = json.loads(content.answer)
                correct_answer = correct_answer_data.get('answer', '').strip()
                solution = correct_answer_data.get('solution', '')
            except (json.JSONDecodeError, AttributeError):
                # JSON이 아닌 경우 문자열로 처리
                correct_answer = parse_correct_answer(content.answer)
                solution = '자동 채점 완료'

            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            # DB에 저장할 데이터 구조 (선택한 답안과 정답 모두 포함)
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
                'solution': solution,
                'question_type': 'ox-quiz',
                'answer_text': {
                    'selected': 'O (맞다)' if student_answer_str == '1' else 'X (틀리다)',
                    'correct': 'O (맞다)' if correct_answer == '1' else 'X (틀리다)'
                }
            }

            # DB에 저장
            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
                }
            )

            # 정답인 경우 StudentProgress 완료 처리
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            # 클라이언트에 상세한 응답 데이터 전송
            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': score,
                'solution': solution,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
                'answer_details': {
                    'selected_text': 'O (맞다)' if student_answer_str == '1' else 'X (틀리다)',
                    'correct_text': 'O (맞다)' if correct_answer == '1' else 'X (틀리다)',
                    'both_same': student_answer_str == correct_answer
                }
            }
            return JsonResponse(response_data)
        
# ----------------------------------------------------------------------
#  ★★★★★  새로운 'selection' 유형 처리 (선택형 퀴즈)  ★★★★★
# ----------------------------------------------------------------------
        elif content_type == 'selection':
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

            # 정답 파싱 (JSON 형태로 저장된 정답)
            try:
                correct_answer_data = json.loads(content.answer)
                correct_answer = correct_answer_data.get('answer', '').strip()
                solution = correct_answer_data.get('solution', '')
            except (json.JSONDecodeError, AttributeError):
                # JSON이 아닌 경우 문자열로 처리
                correct_answer = parse_correct_answer(content.answer)
                solution = '자동 채점 완료'

            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            # DB에 저장할 데이터 구조 (선택한 답안과 정답 모두 포함)
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
                'solution': solution,
                'question_type': 'selection',
                'answer_text': {
                    'selected': f"{student_answer_str}번 선택지",
                    'correct': f"{correct_answer}번 선택지"
                }
            }

            # DB에 저장
            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
                }
            )

            # 정답인 경우 StudentProgress 완료 처리
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            # 클라이언트에 상세한 응답 데이터 전송
            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': score,
                'solution': solution,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
                'answer_details': {
                    'selected_text': f"{student_answer_str}번 선택지",
                    'correct_text': f"{correct_answer}번 선택지",
                    'both_same': student_answer_str == correct_answer
                }
            }
            return JsonResponse(response_data)
        # views.py의 check_answer 함수에 추가
        elif content_type == 'choice':
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

            # 정답 파싱 (JSON 형태로 저장된 정답)
            try:
                correct_answer_data = json.loads(content.answer)
                correct_answer = correct_answer_data.get('answer', '').strip()
                solution = correct_answer_data.get('solution', '')
            except (json.JSONDecodeError, AttributeError):
                # JSON이 아닌 경우 문자열로 처리
                correct_answer = parse_correct_answer(content.answer)
                solution = '자동 채점 완료'

            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            # DB에 저장할 데이터 구조 (선택한 답안과 정답 모두 포함)
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
                'solution': solution,
                'question_type': 'choice',
                'answer_text': {
                    'selected': f"{student_answer_str}번 선택지",
                    'correct': f"{correct_answer}번 선택지"
                }
            }

            # DB에 저장
            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
                }
            )

            # 정답인 경우 StudentProgress 완료 처리
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            # 클라이언트에 상세한 응답 데이터 전송
            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': score,
                'solution': solution,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
                'answer_details': {
                    'selected_text': f"{student_answer_str}번 선택지",
                    'correct_text': f"{correct_answer}번 선택지",
                    'both_same': student_answer_str == correct_answer
                }
            }
            return JsonResponse(response_data)
        
        # drag 타입 처리 - choice형과 동일한 패턴
        elif content_type == 'drag':
            student_answer = request.POST.get('student_answer', '').strip()
            if not student_answer:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)
            # JSON 파싱
            if isinstance(student_answer, str):
                drag_state = json.loads(student_answer)
            else:
                drag_state = student_answer
            
            # 정답 데이터 파싱 (choice형과 동일한 구조)
            correct_answer_data = json.loads(slide.content.answer)
            correct_answer = correct_answer_data.get('answer', {})
            solution = correct_answer_data.get('solution', '')
            
            # 채점
            is_correct = check_drag_answer_logic(drag_state, correct_answer)
            
            # 답안 저장 (choice형과 동일한 구조)
            answer_data = {
                'selected_answer': drag_state,
                'correct_answer': correct_answer,
                'solution': solution
            }
            
            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': 100 if is_correct else 0
                }
            )
            
            return JsonResponse({
                'success': True,
                'is_correct': is_correct,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
                'score': student_answer_obj.score,
                'solution': solution
            })
                
        # 기존 다른 유형들 처리...
        # (multiple-choice, multi-choice, short-answer, multi-input 등)
        
    except Exception as e:
        import traceback
        print(f"ERROR: check_answer 뷰에서 예외 발생: {str(e)}")
        print(f"트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)


def check_drag_answer_logic(user_answer, correct_answer):
    """드래그 답안 채점 로직 - choice형과 동일한 구조"""
    try:
        # 빈칸채우기/매칭 타입
        if isinstance(correct_answer, dict):
            for zone_id, correct_value in correct_answer.items():
                if zone_id not in user_answer or str(user_answer[zone_id]) != str(correct_value):
                    return False
            return True
        # 단일 답안 타입
        else:
            return str(user_answer) == str(correct_answer)
    except:
        return False

# def check_drag_answer(user_state, correct_data, quiz_type):
#     """드래그 답안 채점 함수"""
#     try:
#         if quiz_type == 'fill-blank':
#             # 빈칸 채우기: 특정 존에 정답 아이템이 있는지 확인
#             for zone_id, correct_value in correct_data.items():
#                 if zone_id not in user_state or user_state[zone_id] != correct_value:
#                     return False
#             return True
            
#         elif quiz_type == 'sort':
#             # 정렬: 순서가 맞는지 확인
#             for order, correct_value in correct_data.items():
#                 if order not in user_state or user_state[order] != correct_value:
#                     return False
#             return True
            
#         elif quiz_type == 'match':
#             # 매칭: 매칭이 정확한지 확인
#             for left_id, correct_right_id in correct_data.items():
#                 if left_id not in user_state or user_state[left_id] != correct_right_id:
#                     return False
#             return True
            
#         return False
        
#     except Exception as e:
#         print(f"채점 오류: {e}")
#         return False

@login_required
@student_required
@require_POST
def check_answer_070220(request):
    """
    학생 답안을 채점하고 저장하는 AJAX 뷰.
    'ox-quiz' 유형 추가 지원
    """
    try:
        # 1. 공통 데이터 가져오기 및 객체 조회
        content_id = request.POST.get('content_id')
        slide_id = request.POST.get('slide_id')

        if not all([content_id, slide_id]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터(content_id, slide_id)가 누락되었습니다.',
            }, status=400)

        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )
        content = slide.content
        content_type = slide.content_type.type_name

        # 슬라이드와 콘텐츠 ID 일치 여부 확인
        if str(content.id) != content_id:
            return JsonResponse({
                'status': 'error',
                'message': '슬라이드와 콘텐츠 정보가 일치하지 않습니다.',
            }, status=400)
        
        # StudentProgress 가져오기 또는 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. 콘텐츠 유형에 따른 분기 처리
        
        # ----------------------------------------------------------------------
        #  ★★★★★  새로운 'ox-quiz' 유형 처리 (OX 퀴즈)  ★★★★★
        # ----------------------------------------------------------------------
        if content_type == 'ox-quiz':
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

            # 정답 파싱 (JSON 형태로 저장된 정답)
            try:
                correct_answer_data = json.loads(content.answer)
                correct_answer = correct_answer_data.get('answer', '').strip()
                solution = correct_answer_data.get('solution', '')
            except (json.JSONDecodeError, AttributeError):
                # JSON이 아닌 경우 문자열로 처리
                correct_answer = parse_correct_answer(content.answer)
                solution = '자동 채점 완료'

            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            # DB에 저장할 데이터 구조
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
                'solution': solution,
                'question_type': 'ox-quiz'
            }

            # DB에 저장
            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': solution if solution else ('정답입니다!' if is_correct else '오답입니다.'),
                }
            )

            # 정답인 경우 StudentProgress 완료 처리
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': score,
                'solution': solution,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
            }
            return JsonResponse(response_data)
        
        # 기존 다른 유형들 처리...
        # (multiple-choice, multi-choice, short-answer, multi-input 등)
        
    except Exception as e:
        import traceback
        print(f"ERROR: check_answer 뷰에서 예외 발생: {str(e)}")
        print(f"트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)


####################### 과거 0608==========================






@login_required
@student_required
@require_POST
def check_answer_0702(request):
    """
    학생 답안을 채점하고 저장하는 AJAX 뷰.
    'multiple-choice', 'multi-choice', 'short-answer', 'multi-input' 유형을 모두 처리합니다.
    """
    try:
        # 1. 공통 데이터 가져오기 및 객체 조회
        content_id = request.POST.get('content_id')
        slide_id = request.POST.get('slide_id')

        if not all([content_id, slide_id]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터(content_id, slide_id)가 누락되었습니다.',
            }, status=400)

        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )
        content = slide.content
        content_type = slide.content_type.type_name

        # 슬라이드와 콘텐츠 ID 일치 여부 확인
        if str(content.id) != content_id:
            return JsonResponse({
                'status': 'error',
                'message': '슬라이드와 콘텐츠 정보가 일치하지 않습니다.',
            }, status=400)
        
        # StudentProgress 가져오기 또는 생성
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. 콘텐츠 유형에 따른 분기 처리
        
        # ----------------------------------------------------------------------
        #  ★★★★★  새로운 'multi-choice' 유형 처리 (다중 선택)  ★★★★★
        # ----------------------------------------------------------------------
        if content_type == 'multi-choice':
            student_answer_json = request.POST.get('student_answer')
            if not student_answer_json:
                return JsonResponse({'status': 'error', 'message': '답안이 선택되지 않았습니다.'}, status=400)

            try:
                # 학생 답안 파싱 (JSON 문자열 -> 리스트)
                student_answers = json.loads(student_answer_json)
                if not isinstance(student_answers, list):
                    return JsonResponse({'status': 'error', 'message': '잘못된 답안 형식입니다.'}, status=400)
                
                # 정답 파싱 (정답도 콤마로 구분된 문자열 형태일 수 있음)
                correct_answer_str = parse_correct_answer(content.answer)
                # "1,2,3" 형태의 문자열을 리스트로 변환
                correct_answers = [ans.strip() for ans in correct_answer_str.split(',')]
                correct_answers.sort()  # 정렬하여 순서 무관하게 비교
                
                # 학생 답안도 문자열로 변환하고 정렬
                student_answers_str = [str(ans) for ans in student_answers]
                student_answers_str.sort()
                
                # 정답 여부 판단
                is_correct = (student_answers_str == correct_answers)
                score = 100.0 if is_correct else 0.0
                
                # DB에 저장할 데이터 구조
                answer_data = {
                    'selected_answers': student_answers_str,
                    'correct_answers': correct_answers,
                    'is_multiple': True
                }

                # DB에 저장
                student_answer_obj, created = StudentAnswer.objects.update_or_create(
                    student=student,
                    slide=slide,
                    defaults={
                        'answer': answer_data,
                        'is_correct': is_correct,
                        'score': score,
                        'feedback': '다중 선택 문제 자동 채점 완료',
                    }
                )

                # 정답인 경우 StudentProgress 완료 처리
                if is_correct and not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()

                response_data = {
                    'status': 'success',
                    'is_correct': is_correct,
                    'correct_answers': correct_answers,
                    'student_answers': student_answers_str,
                    'score': score,
                    'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'feedback': student_answer_obj.feedback,
                }
                return JsonResponse(response_data)

            except (json.JSONDecodeError, ValueError) as e:
                return JsonResponse({'status': 'error', 'message': f'답안 처리 중 오류 발생: {e}'}, status=400)

        # ----------------------------------------------------------------------
        #  ★★★★★  'multi-input' 유형 처리  ★★★★★
        # ----------------------------------------------------------------------
        elif content_type == 'multi-input':
            student_answer_json = request.POST.get('student_answer')
            if not student_answer_json:
                return JsonResponse({'status': 'error', 'message': '답안 데이터가 없습니다.'}, status=400)

            try:
                # 학생 답안과 정답 데이터 파싱
                student_answers = json.loads(student_answer_json)
                correct_answers_data = json.loads(content.answer)
                correct_answers = correct_answers_data.get('answer', {})

                results = {}
                correct_count = 0
                total_count = len(correct_answers)

                # 개별 문항 채점
                for key, correct_val in correct_answers.items():
                    user_val = student_answers.get(key, "").strip()
                    is_item_correct = (user_val == correct_val)
                    if is_item_correct:
                        correct_count += 1
                    results[key] = {'is_correct': is_item_correct, 'user_answer': user_val}

                # 최종 점수 및 상태 계산
                score = round((correct_count / total_count) * 100) if total_count > 0 else 0
                is_overall_correct = (score == 100)

                # DB에 저장할 데이터 구조 생성
                answer_data_to_save = {
                    'submitted_answers': student_answers,
                    'results': results,
                }

                # DB에 저장 (update_or_create)
                student_answer_obj, created = StudentAnswer.objects.update_or_create(
                    student=student,
                    slide=slide,
                    defaults={
                        'answer': answer_data_to_save,
                        'is_correct': is_overall_correct,
                        'score': score,
                        'feedback': 'multi-input 자동 채점 완료',
                    }
                )

                # 정답인 경우 StudentProgress 완료 처리
                if is_overall_correct and not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()

                # 클라이언트에 보낼 응답 데이터 구성
                response_data = {
                    'status': 'success',
                    'is_correct': is_overall_correct,
                    'score': score,
                    'results': results,
                    'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                }
                return JsonResponse(response_data)

            except (json.JSONDecodeError, KeyError) as e:
                return JsonResponse({'status': 'error', 'message': f'데이터 처리 중 오류 발생: {e}'}, status=400)

        # --------------------------------------------------------------------------
        #  ★★★★★  기존 'multiple-choice', 'short-answer' 유형 처리  ★★★★★
        # --------------------------------------------------------------------------
        elif content_type in ['multiple-choice', 'short-answer']:
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 입력되지 않았습니다.'}, status=400)

            correct_answer = parse_correct_answer(content.answer)
            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
            }

            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': '자동 채점 완료',
                }
            )

            # 정답인 경우 StudentProgress 완료 처리
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': student_answer_obj.score,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
            }
            return JsonResponse(response_data)
            
        else:
            # 지원하지 않는 문제 유형 처리
            return JsonResponse({'status': 'error', 'message': f"지원하지 않는 문제 유형입니다: {content_type}"}, status=400)

    # 3. 모든 예외에 대한 공통 처리
    except ChasiSlide.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '요청한 슬라이드를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        import traceback
        print(f"ERROR: check_answer 뷰에서 예외 발생: {str(e)}")
        print(f"트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)





@login_required
@student_required
@require_POST
def check_answer_0612(request):
    """
    학생 답안을 채점하고 저장하는 AJAX 뷰.
    'multiple-choice', 'short-answer', 'multi-input' 유형을 모두 처리합니다.
    """
    try:
        # 1. 공통 데이터 가져오기 및 객체 조회
        content_id = request.POST.get('content_id')
        slide_id = request.POST.get('slide_id')

        # student_answer는 유형에 따라 다르게 처리되므로 여기서는 검증하지 않음
        if not all([content_id, slide_id]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터(content_id, slide_id)가 누락되었습니다.',
            }, status=400)

        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )
        content = slide.content
        content_type = slide.content_type.type_name

        # 슬라이드와 콘텐츠 ID 일치 여부 확인
        if str(content.id) != content_id:
            return JsonResponse({
                'status': 'error',
                'message': '슬라이드와 콘텐츠 정보가 일치하지 않습니다.',
            }, status=400)
        
        # ★★★ StudentProgress 가져오기 또는 생성 ★★★
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. 콘텐츠 유형에 따른 분기 처리
        
        # ----------------------------------------------------------------------
        #  ★★★★★  새로운 'multi-input' 유형 처리  ★★★★★
        # ----------------------------------------------------------------------
        if content_type == 'multi-input':
            student_answer_json = request.POST.get('student_answer')
            if not student_answer_json:
                return JsonResponse({'status': 'error', 'message': '답안 데이터가 없습니다.'}, status=400)

            try:
                # 학생 답안과 정답 데이터 파싱
                student_answers = json.loads(student_answer_json)
                correct_answers_data = json.loads(content.answer)
                correct_answers = correct_answers_data.get('answer', {})

                results = {}
                correct_count = 0
                total_count = len(correct_answers)

                # 개별 문항 채점
                for key, correct_val in correct_answers.items():
                    user_val = student_answers.get(key, "").strip()
                    is_item_correct = (user_val == correct_val)
                    if is_item_correct:
                        correct_count += 1
                    results[key] = {'is_correct': is_item_correct, 'user_answer': user_val}

                # 최종 점수 및 상태 계산
                score = round((correct_count / total_count) * 100) if total_count > 0 else 0
                is_overall_correct = (score == 100)

                # DB에 저장할 데이터 구조 생성
                answer_data_to_save = {
                    'submitted_answers': student_answers,
                    'results': results,
                }

                # DB에 저장 (update_or_create)
                student_answer_obj, created = StudentAnswer.objects.update_or_create(
                    student=student,
                    slide=slide,
                    defaults={
                        'answer': answer_data_to_save,
                        'is_correct': is_overall_correct,
                        'score': score,
                        'feedback': 'multi-input 자동 채점 완료',
                    }
                )

                
                # ★★★ 정답인 경우 StudentProgress 완료 처리 ★★★
                if is_overall_correct and not progress.is_completed:
                    progress.is_completed = True
                    progress.completed_at = timezone.now()
                    progress.save()

                # 클라이언트에 보낼 응답 데이터 구성
                response_data = {
                    'status': 'success',
                    'is_correct': is_overall_correct,
                    'score': score,
                    'results': results,
                    'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                }
                return JsonResponse(response_data)

            except (json.JSONDecodeError, KeyError) as e:
                return JsonResponse({'status': 'error', 'message': f'데이터 처리 중 오류 발생: {e}'}, status=400)

        # --------------------------------------------------------------------------
        #  ★★★★★  기존 'multiple-choice', 'short-answer' 유형 처리  ★★★★★
        # --------------------------------------------------------------------------
        elif content_type in ['multiple-choice', 'short-answer']:
            student_answer_str = request.POST.get('student_answer', '').strip()
            if not student_answer_str:
                return JsonResponse({'status': 'error', 'message': '답안이 입력되지 않았습니다.'}, status=400)

            correct_answer = parse_correct_answer(content.answer)
            is_correct = (student_answer_str == correct_answer)
            score = 100.0 if is_correct else 0.0
            
            answer_data = {
                'selected_answer': student_answer_str,
                'correct_answer': correct_answer,
            }

            student_answer_obj, created = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': answer_data,
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': '자동 채점 완료',
                }
            )

            print(f"답안 {'생성' if created else '업데이트'} 완료: ID {student_answer_obj.id} (학생: {student.id}, 슬라이드: {slide.id})")
            # ★★★ 정답인 경우 StudentProgress 완료 처리 ★★★
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

            response_data = {
                'status': 'success',
                'is_correct': is_correct,
                'correct_answer': correct_answer,
                'student_answer': student_answer_str,
                'score': student_answer_obj.score,
                'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M:%S'),
                'feedback': student_answer_obj.feedback,
            }
            return JsonResponse(response_data)
            
        else:
            # 지원하지 않는 문제 유형 처리
            return JsonResponse({'status': 'error', 'message': f"지원하지 않는 문제 유형입니다: {content_type}"}, status=400)

    # 3. 모든 예외에 대한 공통 처리
    except ChasiSlide.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '요청한 슬라이드를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        import traceback
        print(f"ERROR: check_answer 뷰에서 예외 발생: {str(e)}")
        print(f"트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)
    


# ★★★★★ [추가] one-shot-submit 유형 답안 제출을 처리하는 AJAX 뷰 ★★★★★
@login_required
@student_required
@require_POST
def submit_answer(request):
    """
    'one-shot-submit' 유형의 학생 답안을 저장하는 AJAX 뷰.
    제출 즉시 100점을 부여합니다.
    """
    try:
        # 1. 데이터 가져오기 및 유효성 검사
        slide_id = request.POST.get('slide_id')
        student_answer_text = request.POST.get('student_answer_text', '').strip()

        if not all([slide_id, student_answer_text]):
            return JsonResponse({
                'status': 'error',
                'message': '필수 데이터(slide_id, 답안)가 누락되었습니다.',
            }, status=400)

        # 2. 객체 조회
        student = request.user.student
        slide = get_object_or_404(
            ChasiSlide.objects.select_related('content', 'content_type'),
            id=slide_id
        )

        # 3. 콘텐츠 유형 확인 (one-shot-submit 유형인지 확인)
        if slide.content_type.type_name != 'one_shot_submit':
            return JsonResponse({
                'status': 'error',
                'message': f'잘못된 문제 유형({slide.content_type.type_name})에 대한 요청입니다.',
            }, status=400)
        
         # ★★★ StudentProgress 가져오기 또는 생성 ★★★
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )
        
        # 4. DB에 저장할 데이터 구조 생성
        answer_data_to_save = {
            'submitted_text': student_answer_text,
        }

        # 5. DB에 저장 (update_or_create로 재제출 시에도 처리)
        # StudentAnswer 모델에 unique_together = ['student', 'slide'] 설정이 있으므로 이 방식이 안전합니다.
        student_answer_obj, created = StudentAnswer.objects.update_or_create(
            student=student,
            slide=slide,
            defaults={
                'answer': answer_data_to_save,
                'is_correct': True, # 제출 시 정답으로 처리
                'score': 100.0,      # 제출 시 100점 부여
                'feedback': 'one_shot_submit 형 제출완료',
            }
        )

        # ★★★ 제출 즉시 StudentProgress 완료 처리 ★★★
        if not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = timezone.now()
            progress.save()
        
        # 6. 클라이언트에 보낼 응답 데이터 구성
        response_data = {
            'status': 'success',
            'message': '답안이 성공적으로 제출되었습니다.',
            'submitted_text': student_answer_text,
            'score': student_answer_obj.score,
            'submitted_at': student_answer_obj.submitted_at.strftime('%Y-%m-%d %H:%M'),
        }
        return JsonResponse(response_data)

    except ChasiSlide.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '요청한 슬라이드를 찾을 수 없습니다.'}, status=404)
    except Exception as e:
        import traceback
        print(f"ERROR: submit_answer 뷰에서 예외 발생: {str(e)}")
        print(f"트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'서버 오류가 발생했습니다: {str(e)}',
        }, status=500)





# ★★★★★ [수정] physical_record 유형 제출 처리 View ★★★★★
@login_required
@student_required
@require_POST
def submit_physical_record(request):
    """
    'physical_record' 유형의 학생 실기 기록을 새로운 형식으로 저장하는 AJAX 뷰.
    """
    try:
        # 1. 데이터 가져오기 및 유효성 검사
        slide_id = request.POST.get('slide_id')
        attempt1_val = request.POST.get('attempt1_val', '').strip()
        attempt2_val = request.POST.get('attempt2_val', '').strip()

        if not all([slide_id, attempt1_val, attempt2_val]):
            return JsonResponse({'status': 'error', 'message': '모든 회차의 기록이 필요합니다.'}, status=400)

        student = request.user.student
        slide = get_object_or_404(ChasiSlide.objects.select_related('content__content_type'), id=slide_id)
        
         # ★★★ StudentProgress 가져오기 또는 생성 ★★★
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # 2. 시간(MM:SS.ms)을 밀리초(float)로 변환
        def convert_time_to_ms(time_str):
            try:
                parts = time_str.replace('.', ':').split(':')
                return float((int(parts[0]) * 60 + int(parts[1])) * 1000 + int(parts[2]) * 10)
            except (ValueError, IndexError): return None

        attempt1_ms = convert_time_to_ms(attempt1_val)
        attempt2_ms = convert_time_to_ms(attempt2_val)

        if attempt1_ms is None or attempt2_ms is None:
            return JsonResponse({'status': 'error', 'message': '잘못된 시간 형식입니다.'}, status=400)

        # 3. DB 저장을 하나의 트랜잭션으로 처리
        with transaction.atomic():
            # 3-1. 슬라이드 정보에서 측정 항목과 단위 조회
            slide_answer_data = json.loads(slide.content.answer or "{}")
            item_name = slide_answer_data.get('item', '기록') # 예: '달리기'
            
            try:
                # PhysicalResultType에서 종류와 단위 정보 가져오기
                result_type = PhysicalResultType.objects.get(type_name=item_name)
                unit = result_type.measure # 예: 'mili_second'
            except PhysicalResultType.DoesNotExist:
                # 해당 타입이 없으면 기본값 사용
                unit = 'mili_second'

            # 3-2. StudentAnswer 모델에 저장할 데이터 구성
            feedback_text = f"1차 시기: {attempt1_val}<br>2차 시기: {attempt2_val}"
            student_answer_obj, _ = StudentAnswer.objects.update_or_create(
                student=student, slide=slide,
                defaults={
                    'answer': {'item': item_name},
                    'is_correct': True, 'score': 100.0,
                    'feedback': feedback_text
                }
            )

            # 3-3. StudentPhysicalResult 모델에 저장할 JSON 리스트 생성
            record_list = [
                {"회차": 1, "기록": attempt1_ms, "단위": unit, "종류": item_name},
                {"회차": 2, "기록": attempt2_ms, "단위": unit, "종류": item_name}
            ]
            
            # StudentPhysicalResult.record 필드는 models.JSONField() 여야 합니다.
            physical_result_obj, _ = StudentPhysicalResult.objects.update_or_create(
                student=student, slide=slide,
                defaults={
                    'record': record_list,
                    'score': 100.0,
                    'writer': student.user.get_full_name()
                }
            )

            # ★★★ 기록 제출 시 StudentProgress 완료 처리 ★★★
            if not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()

        # 4. 클라이언트에 성공 응답 전송 (feedback 포함)
        return JsonResponse({
            'status': 'success',
            'message': '기록이 성공적으로 제출되었습니다.',
            'feedback': feedback_text
        })

    except Exception as e:
        import traceback
        return JsonResponse({'status': 'error', 'message': f'서버 오류: {traceback.format_exc()}'}, status=500)

# # 밀리초를 시간(MM:SS.ms)으로 변환하는 헬퍼 함수 (응답 시 사용)
# def format_ms_to_time(ms):
#     total_seconds = ms / 1000
#     minutes = int(total_seconds // 60)
#     seconds = int(total_seconds % 60)
#     hundredths = int((ms % 1000) / 10)
#     return f"{minutes:02d}:{seconds:02d}.{hundredths:02d}"


# ★★★★★ [수정] ordering 유형 답안 채점 View (로그 추가 및 로직 수정) ★★★★★
@login_required
@student_required
@require_POST
def check_ordering(request):
    """
    'ordering' 유형의 학생 답안을 채점하고 저장하는 AJAX 뷰.
    """
    try:
        # 1. 데이터 가져오기
        slide_id = request.POST.get('slide_id')
        user_order = request.POST.get('user_order', '').strip()

        if not all([slide_id, user_order]):
            return JsonResponse({'status': 'error', 'message': '필수 데이터가 누락되었습니다.'}, status=400)

        # 2. 객체 조회
        student = request.user.student
        slide = get_object_or_404(ChasiSlide.objects.select_related('content'), id=slide_id)
        
        # ★★★ StudentProgress 가져오기 또는 생성 ★★★
        progress, created = StudentProgress.objects.get_or_create(
            student=student,
            slide=slide,
            defaults={'started_at': timezone.now()}
        )

        # --- ★★★★★ 로그 추가 및 로직 수정 부분 시작 ★★★★★ ---

        # 로그 1: 클라이언트가 보낸 학생 답안 확인
        print(f"✅ User's Submitted Order: '{user_order}' (Type: {type(user_order)})")

        # 로그 2: 데이터베이스에서 가져온 원본 정답 데이터 확인

        raw_answer_from_db = slide.content.answer
        print(f"✅ Raw Answer from DB: '{raw_answer_from_db}' (Type: {type(raw_answer_from_db)})")
        
        # 3. JSON 문자열을 파싱하여 실제 정답 추출
        try:
            answer_data = json.loads(raw_answer_from_db)
            correct_answer = answer_data.get('answer', '').strip()
        except (json.JSONDecodeError, AttributeError):
            # JSON 형식이 아니거나 'answer' 키가 없는 경우에 대한 예외 처리
            correct_answer = raw_answer_from_db.strip()

        # 로그 3: 파싱 후 비교에 사용될 실제 정답 확인
        print(f"✅ Parsed Correct Answer: '{correct_answer}' (Type: {type(correct_answer)})")
        
        # 4. 정답 비교
        is_correct = (user_order == correct_answer)
        score = 100.0 if is_correct else 0.0

        # 로그 4: 최종 비교 결과 확인
        print(f"➡️ Comparing '{user_order}' == '{correct_answer}' -> Result: {is_correct}")
        
        # --- ★★★★★ 로그 추가 및 로직 수정 부분 끝 ★★★★★ ---
        
        # 5. DB에 학생 답안 저장
        with transaction.atomic():
            student_answer_obj, _ = StudentAnswer.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={
                    'answer': {'submitted_order': user_order},
                    'is_correct': is_correct,
                    'score': score,
                    'feedback': '정답입니다!' if is_correct else '순서가 틀렸습니다. 다시 시도해 보세요.'
                }
            )

            # ★★★ 정답인 경우 StudentProgress 완료 처리 ★★★
            if is_correct and not progress.is_completed:
                progress.is_completed = True
                progress.completed_at = timezone.now()
                progress.save()
            
        # 6. 클라이언트에 채점 결과 응답
        return JsonResponse({
            'status': 'success',
            'is_correct': is_correct
        })

    except Exception as e:
        import traceback
        # ... 기존과 동일한 예외 처리 ...
        return JsonResponse({'status': 'error', 'message': f'서버 오류: {traceback.format_exc()}'}, status=500)
    

@login_required
@student_required
def save_note_ajax(request, slide_id):
    """노트 저장 AJAX 처리"""
    if request.method == 'POST':
        student = request.user.student
        slide = get_object_or_404(ChasiSlide, id=slide_id)
        
        note_content = request.POST.get('note_content', '')
        
        if note_content.strip():
            note, created = StudentNote.objects.update_or_create(
                student=student,
                slide=slide,
                defaults={'content': note_content}
            )
            return JsonResponse({'status': 'success'})
        else:
            # 빈 내용이면 노트 삭제
            StudentNote.objects.filter(student=student, slide=slide).delete()
            return JsonResponse({'status': 'success'})
    
    return JsonResponse({'status': 'error'})


from django.core.paginator import Paginator
from django.db.models import Prefetch

# student/views.py의 my_answers_view 수정
# student/views.py의 my_answers_view 수정

# 먼저 파일 상단 또는 my_answers_view 위에 헬퍼 함수 추가
def get_slide_status(answer, progress):
    """슬라이드의 상태를 반환하는 헬퍼 함수"""
    if not progress or not progress.started_at:
        return 'not_started'
    elif answer:
        if answer.is_correct:
            return 'correct'
        elif answer.is_correct == False:
            return 'incorrect'
        else:
            return 'pending'
    elif progress.is_completed:
        return 'completed'
    else:
        return 'in_progress'


@login_required
@student_required
def my_answers_view(request):
    """내 답안 목록 (개선된 버전)"""
    student = request.user.student
    
    # 기본 쿼리
    answers = StudentAnswer.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type',
        'slide__content'
    ).order_by('-submitted_at')
    
    # 코스 필터링
    course_id = request.GET.get('course')
    if course_id:
        answers = answers.filter(slide__chasi__sub_chapter__chapter__subject_id=course_id)
    
    # 차시 필터링
    chasi_id = request.GET.get('chasi')
    if chasi_id:
        answers = answers.filter(slide__chasi_id=chasi_id)
    
    # 검색 기능
    search_query = request.GET.get('search')
    if search_query:
        answers = answers.filter(
            Q(slide__content__title__icontains=search_query) |
            Q(slide__chasi__chasi_title__icontains=search_query)
        )
    
    # 정답 여부 필터
    correct_filter = request.GET.get('correct')
    if correct_filter == 'true':
        answers = answers.filter(is_correct=True)
    elif correct_filter == 'false':
        answers = answers.filter(is_correct=False)
    
    # 통계 계산
    total_answers = answers.count()
    correct_answers = answers.filter(is_correct=True).count()
    incorrect_answers = answers.filter(is_correct=False).count()
    correct_rate = int((correct_answers / total_answers) * 100) if total_answers > 0 else 0
    
    # 테이블 뷰를 위한 전체 차시 데이터 준비
    all_chasis_data = []
    if course_id:
        # 선택된 코스의 모든 차시를 순서대로 가져오기
        all_chasis = Chasi.objects.filter(
            sub_chapter__chapter__subject_id=course_id,
            is_published=True
        ).select_related(
            'sub_chapter__chapter__subject'
        ).order_by(
            'sub_chapter__chapter__chapter_order',
            'sub_chapter__sub_chapter_order',
            'chasi_order'
        )
        
        # 각 차시별로 슬라이드와 답안 정보 수집
        for chasi in all_chasis:
            slides = ChasiSlide.objects.filter(
                chasi=chasi,
                is_active=True
            ).select_related('content_type', 'content').order_by('slide_number')
            
            chasi_info = {
                'chasi': chasi,
                'slides': []
            }
            
            for slide in slides:
                # 해당 슬라이드의 답안 찾기
                student_answer = StudentAnswer.objects.filter(
                    student=student,
                    slide=slide
                ).order_by('-submitted_at').first()
                
                # 진도 상태 확인
                progress = StudentProgress.objects.filter(
                    student=student,
                    slide=slide
                ).first()
                
                slide_info = {
                    'slide': slide,
                    'answer': student_answer,
                    'progress': progress,
                    'status': get_slide_status(student_answer, progress)  # self 제거
                }
                chasi_info['slides'].append(slide_info)
            
            all_chasis_data.append(chasi_info)
    
    # 페이지네이션 (리스트 뷰용)
    paginator = Paginator(answers, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # 코스 목록
    courses = Course.objects.filter(
        assignments__in=CourseAssignment.objects.filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        )
    ).distinct()
    
    # 차시 목록
    chasis = []
    if course_id:
        chasis = Chasi.objects.filter(
            sub_chapter__chapter__subject_id=course_id,
            is_published=True
        ).select_related(
            'sub_chapter__chapter'
        ).order_by(
            'sub_chapter__chapter__chapter_order',
            'sub_chapter__sub_chapter_order',
            'chasi_order'
        )
    
    # 필터 파라미터
    filter_params = {}
    if course_id:
        filter_params['course'] = course_id
    if chasi_id:
        filter_params['chasi'] = chasi_id
    if correct_filter:
        filter_params['correct'] = correct_filter
    if search_query:
        filter_params['search'] = search_query
    
    context = {
        'page_obj': page_obj,
        'answers': page_obj,
        'courses': courses,
        'chasis': chasis,
        'selected_course_id': course_id,
        'selected_chasi_id': chasi_id,
        'total_answers': total_answers,
        'correct_answers': correct_answers,
        'incorrect_answers': incorrect_answers,
        'correct_rate': correct_rate,
        'filter_params': filter_params,
        'all_chasis_data': all_chasis_data,  # 테이블 뷰용 데이터
    }
    
    return render(request, 'student/my_answers.html', context)

@login_required
@student_required
def my_answers_view_0619(request):
    """내 답안 목록"""
    student = request.user.student
    
    # 기본 쿼리
    answers = StudentAnswer.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type',
        'slide__content'
    ).order_by('-submitted_at')
    
    # 코스 필터링
    course_id = request.GET.get('course')
    if course_id:
        answers = answers.filter(slide__chasi__sub_chapter__chapter__subject_id=course_id)
    
    # 차시 필터링 (새로 추가)
    chasi_id = request.GET.get('chasi')
    if chasi_id:
        answers = answers.filter(slide__chasi_id=chasi_id)
    
    # 검색 기능
    search_query = request.GET.get('search')
    if search_query:
        answers = answers.filter(
            Q(slide__content__title__icontains=search_query) |
            Q(slide__chasi__chasi_title__icontains=search_query)
        )
    
    # 정답 여부 필터
    correct_filter = request.GET.get('correct')
    if correct_filter == 'true':
        answers = answers.filter(is_correct=True)
    elif correct_filter == 'false':
        answers = answers.filter(is_correct=False)
    
    # 통계 계산 (필터링 후의 결과로)
    total_answers = answers.count()
    correct_answers = answers.filter(is_correct=True).count()
    incorrect_answers = answers.filter(is_correct=False).count()
    
    # 정답률 계산
    if total_answers > 0:
        correct_rate = int((correct_answers / total_answers) * 100)
    else:
        correct_rate = 0
    
    # 페이지네이션
    paginator = Paginator(answers, 20)  # 페이지당 20개
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # 코스 목록 (필터용)
    courses = Course.objects.filter(
        assignments__in=CourseAssignment.objects.filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        )
    ).distinct()
    
    # 차시 목록 (선택된 코스가 있을 때만)
    chasis = []
    if course_id:
        chasis = Chasi.objects.filter(
            sub_chapter__chapter__subject_id=course_id,
            is_published=True
        ).select_related(
            'sub_chapter__chapter'
        ).order_by(
            'sub_chapter__chapter__chapter_order',
            'sub_chapter__sub_chapter_order',
            'chasi_order'
        )
    
    # 현재 필터 파라미터들을 유지하기 위한 딕셔너리
    filter_params = {}
    if course_id:
        filter_params['course'] = course_id
    if chasi_id:
        filter_params['chasi'] = chasi_id
    if correct_filter:
        filter_params['correct'] = correct_filter
    if search_query:
        filter_params['search'] = search_query
    
    context = {
        'page_obj': page_obj,
        'answers': page_obj,  # 템플릿 호환성을 위해 유지
        'courses': courses,
        'chasis': chasis,
        'selected_course_id': course_id,
        'selected_chasi_id': chasi_id,
        'total_answers': total_answers,
        'correct_answers': correct_answers,
        'incorrect_answers': incorrect_answers,
        'correct_rate': correct_rate,
        'filter_params': filter_params,
    }
    
    return render(request, 'student/my_answers.html', context)


@login_required
@student_required
def my_answers_view_0609(request):
    """내 답안 목록"""
    student = request.user.student
    
    # 기본 쿼리
    answers = StudentAnswer.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-submitted_at')
    
    # 필터링
    course_id = request.GET.get('course')
    if course_id:
        answers = answers.filter(slide__chasi__sub_chapter__chapter__subject_id=course_id)
    
    # 정답 여부 필터
    correct_filter = request.GET.get('correct')
    if correct_filter == 'true':
        answers = answers.filter(is_correct=True)
    elif correct_filter == 'false':
        answers = answers.filter(is_correct=False)
    
    # 통계 계산
    total_answers = answers.count()
    correct_answers = answers.filter(is_correct=True).count()
    incorrect_answers = answers.filter(is_correct=False).count()
    
    # 정답률 계산 (view에서 처리)
    if total_answers > 0:
        correct_rate = int((correct_answers / total_answers) * 100)
    else:
        correct_rate = 0
    
    # 코스 목록 - courseassignment를 assignments로 변경
    courses = Course.objects.filter(
        assignments__in=CourseAssignment.objects.filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        )
    ).distinct()
    
    context = {
        'answers': answers,
        'courses': courses,
        'total_answers': total_answers,
        'correct_answers': correct_answers,
        'incorrect_answers': incorrect_answers,
        'correct_rate': correct_rate,  # 정답률 추가
    }
    
    return render(request, 'student/my_answers.html', context)

@login_required
@student_required
def my_answers_view_0608(request):
    """내 답안 목록"""
    student = request.user.student
    
    # 기본 쿼리
    answers = StudentAnswer.objects.filter(
        student=student
    ).select_related(
        'slide__chasi__sub_chapter__chapter__subject',
        'slide__content_type'
    ).order_by('-submitted_at')
    
    # 필터링
    course_id = request.GET.get('course')
    if course_id:
        answers = answers.filter(slide__chasi__sub_chapter__chapter__subject_id=course_id)
    
    # 정답 여부 필터
    correct_filter = request.GET.get('correct')
    if correct_filter == 'true':
        answers = answers.filter(is_correct=True)
    elif correct_filter == 'false':
        answers = answers.filter(is_correct=False)
    
    # 통계 계산
    total_answers = answers.count()
    correct_answers = answers.filter(is_correct=True).count()
    incorrect_answers = answers.filter(is_correct=False).count()
    
    # 코스 목록 - courseassignment를 assignments로 변경
    courses = Course.objects.filter(
        assignments__in=CourseAssignment.objects.filter(
            Q(assigned_class=student.school_class) | Q(assigned_student=student)
        )
    ).distinct()
    
    context = {
        'answers': answers,
        'courses': courses,
        'total_answers': total_answers,
        'correct_answers': correct_answers,
        'incorrect_answers': incorrect_answers,
    }
    
    return render(request, 'student/my_answers.html', context)

@login_required
@student_required
def course_progress_api(request, course_id):
    """코스 진도 API"""
    student = request.user.student
    course = get_object_or_404(Course, id=course_id)
    
    # 전체 슬라이드 수
    total_slides = ChasiSlide.objects.filter(
        chasi__sub_chapter__chapter__subject=course
    ).count()
    
    # 완료한 슬라이드 수
    completed_slides = StudentProgress.objects.filter(
        student=student,
        slide__chasi__sub_chapter__chapter__subject=course,
        is_completed=True
    ).count()
    
    progress_percent = 0
    if total_slides > 0:
        progress_percent = int((completed_slides / total_slides) * 100)
    
    return JsonResponse({
        'total_slides': total_slides,
        'completed_slides': completed_slides,
        'progress_percent': progress_percent,
    })