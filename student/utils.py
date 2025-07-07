# student/utils.py
import json
from django.utils import timezone
from django.db import connection
from .models import StudentAnswer
from accounts.models import Student
from teacher.models import ChasiSlide
from django.http import JsonResponse


def parse_correct_answer(answer_text):
    """Contents의 answer 필드에서 실제 정답을 추출하는 함수"""
    if not answer_text:
        return ''
    
    answer_text = answer_text.strip()
    
    # JSON 형태인지 확인
    if answer_text.startswith('{') and answer_text.endswith('}'):
        try:
            # JSON 파싱 시도
            answer_data = json.loads(answer_text)
            # 'answer' 키의 값을 문자열로 반환
            correct_answer = str(answer_data.get('answer', ''))
            print(f"JSON에서 파싱된 정답: '{correct_answer}'")
            return correct_answer
        except json.JSONDecodeError as e:
            print(f"JSON 파싱 실패: {e}")
            # JSON 파싱 실패시 원본 텍스트 반환
            return answer_text
    else:
        # 일반 텍스트
        return answer_text


def update_existing_answer(existing_answer, student_answer, correct_answer, is_correct):
    """기존 답안을 업데이트하는 함수"""
    try:
        answer_data = {
            'selected_answer': student_answer,
            'correct_answer': correct_answer,
            'answer_type': 'resubmit',
            'submitted_at': timezone.now().isoformat()
        }
        
        existing_answer.answer = answer_data
        existing_answer.is_correct = is_correct
        existing_answer.score = 100.0 if is_correct else 0.0
        existing_answer.submitted_at = timezone.now()
        existing_answer.feedback = '자동 채점 결과 (재제출)'
        existing_answer.save()
        
        print(f"기존 답안 업데이트 완료: {existing_answer.id}")
        return existing_answer
        
    except Exception as e:
        print(f"기존 답안 업데이트 실패: {e}")
        return None


def create_new_answer(student, slide, student_answer, correct_answer, is_correct):
    """
    새 답안을 생성하는 함수 - Django ORM만 사용하여 안전하게 생성
    """
    try:
        print("=== 새 답안 생성(ORM) 시작 ===")
        from django.utils import timezone

        answer_data = {
            'selected_answer': student_answer,
            'correct_answer': correct_answer,
            'answer_type': 'first_submit',
            'submitted_at': timezone.now().isoformat()
        }

        # **핵심 수정** : 다른 Raw SQL / FK 비활성화 로직 전부 제거하고 ORM만 사용
        student_answer_obj = StudentAnswer.objects.create(
            student=student,
            slide=slide,
            answer=answer_data,
            is_correct=is_correct,
            score=100.0 if is_correct else 0.0,
            feedback='자동 채점 결과'
        )

        print(f"ORM으로 생성 성공: {student_answer_obj.id}")
        return student_answer_obj

    except Exception as e:
        print(f"새 답안 생성 실패(ORM): {e}")
        import traceback
        print(traceback.format_exc())
        return None

def create_new_answer_0606(student, slide, student_answer, correct_answer, is_correct):
    """새 답안을 생성하는 함수 - 간단한 우회 방법"""
    try:
        print(f"=== 새 답안 생성 시작 ===")
        print(f"Student ID: {student.id}, ChasiSlide ID: {slide.id}")
        
        # 1단계: 외래키 존재 확인
        student_exists = Student.objects.filter(id=student.id).exists()
        slide_exists = ChasiSlide.objects.filter(id=slide.id).exists()
        
        print(f"Student 존재: {student_exists}, ChasiSlide 존재: {slide_exists}")
        
        if not student_exists or not slide_exists:
            print("ERROR: 외래키 객체가 존재하지 않음")
            return None
        
        # 2단계: 가장 간단한 방법으로 생성
        answer_data = {
            'selected_answer': student_answer,
            'correct_answer': correct_answer,
            'answer_type': 'first_submit',
            'submitted_at': timezone.now().isoformat()
        }
        
        try:
            # 방법 1: 외래키 제약조건 임시 비활성화 (SQLite)
            print("외래키 제약조건 임시 비활성화 시도...")
            return create_with_fk_disabled(student, slide, answer_data, is_correct)
        except Exception as e:
            print(f"외래키 비활성화 방법 실패: {e}")
            
        try:
            # 방법 2: 최소한의 필드만 사용
            print("최소 필드 방법 시도...")
            return create_with_minimal_fields(student.id, slide.id, answer_data, is_correct)
        except Exception as e:
            print(f"최소 필드 방법 실패: {e}")
            
        try:
            # 방법 3: 일반 ORM (마지막 시도)
            print("일반 ORM 방법 시도...")
            return create_answer_with_orm(student, slide, answer_data, is_correct)
        except Exception as e:
            print(f"일반 ORM 방법 실패: {e}")
            
        print("모든 방법 실패")
        return None
        
    except Exception as e:
        print(f"새 답안 생성 전체 실패: {e}")
        import traceback
        print(f"트레이스백: {traceback.format_exc()}")
        return None


def create_with_fk_disabled(student, slide, answer_data, is_correct):
    """외래키 제약조건을 임시로 비활성화하고 생성"""
    from django.db import transaction
    
    with connection.cursor() as cursor:
        # SQLite 외래키 제약조건 비활성화
        cursor.execute("PRAGMA foreign_keys = OFF")
        
        try:
            with transaction.atomic():
                student_answer_obj = StudentAnswer.objects.create(
                    student_id=student.id,
                    slide_id=slide.id,
                    answer=answer_data,
                    is_correct=is_correct,
                    score=100.0 if is_correct else 0.0,
                    feedback='자동 채점 결과'
                )
                print(f"외래키 비활성화로 생성 성공: {student_answer_obj.id}")
                return student_answer_obj
        finally:
            # 외래키 제약조건 다시 활성화
            cursor.execute("PRAGMA foreign_keys = ON")


def create_with_minimal_fields(student_id, slide_id, answer_data, is_correct):
    """최소한의 필드만 사용해서 생성"""
    import json
    
    with connection.cursor() as cursor:
        # 가장 기본적인 INSERT
        cursor.execute("""
            INSERT INTO student_studentanswer 
            (student_id, slide_id, answer, is_correct, score, feedback, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, [
            student_id,
            slide_id,
            json.dumps(answer_data),
            is_correct,
            100.0 if is_correct else 0.0,
            '자동 채점 결과'
        ])
        
        # 생성된 ID 가져오기
        cursor.execute("SELECT last_insert_rowid()")
        answer_id = cursor.fetchone()[0]
        
        print(f"최소 필드로 생성 성공: {answer_id}")
        
        # ORM 객체로 반환
        return StudentAnswer.objects.get(id=answer_id)


def check_student_exists(student_id):
    """Student가 실제로 존재하는지 확인"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM student_student WHERE id = ?", [student_id])
            count = cursor.fetchone()[0]
            return count > 0
    except Exception as e:
        print(f"Student 존재 확인 실패: {e}")
        return False


def check_slide_exists(slide_id):
    """ChasiSlide가 실제로 존재하는지 확인"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM teacher_chasislide WHERE id = ?", [slide_id])
            count = cursor.fetchone()[0]
            return count > 0
    except Exception as e:
        print(f"ChasiSlide 존재 확인 실패: {e}")
        return False


def check_student_relations(student):
    """Student의 관련 객체들이 모두 존재하는지 확인"""
    try:
        print(f"Student 관계 확인:")
        print(f"  - User ID: {student.user.id if student.user else 'None'}")
        print(f"  - School Class ID: {student.school_class.id if student.school_class else 'None'}")
        
        # User 존재 확인
        if student.user:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM auth_user WHERE id = ?", [student.user.id])
                user_exists = cursor.fetchone()[0] > 0
                print(f"  - User 존재: {user_exists}")
        
        # Class 존재 확인 (테이블 이름은 실제에 맞게 수정 필요)
        if student.school_class:
            try:
                with connection.cursor() as cursor:
                    # 실제 Class 테이블 이름으로 수정 필요
                    cursor.execute("SELECT COUNT(*) FROM student_class WHERE id = ?", [student.school_class.id])
                    class_exists = cursor.fetchone()[0] > 0
                    print(f"  - Class 존재: {class_exists}")
            except Exception as e:
                print(f"  - Class 확인 실패: {e}")
        
    except Exception as e:
        print(f"Student 관계 확인 실패: {e}")


def create_answer_with_raw_sql(student_id, slide_id, answer_data, is_correct):
    """Raw SQL로 StudentAnswer 생성 시도"""
    try:
        import json
        from django.utils import timezone
        
        score = 100.0 if is_correct else 0.0
        now = timezone.now()
        
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO student_studentanswer 
                (student_id, slide_id, answer, submitted_at, is_correct, score, feedback)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                student_id,
                slide_id, 
                json.dumps(answer_data),
                now,
                is_correct,
                score,
                '자동 채점 결과'
            ])
            
            # 생성된 ID 가져오기
            cursor.execute("SELECT last_insert_rowid()")
            answer_id = cursor.fetchone()[0]
            
            print(f"Raw SQL로 생성 성공: {answer_id}")
            
            # ORM 객체로 반환
            return StudentAnswer.objects.get(id=answer_id)
            
    except Exception as e:
        print(f"Raw SQL 생성 실패: {e}")
        return None


def create_answer_with_orm(student, slide, answer_data, is_correct):
    """일반 ORM으로 StudentAnswer 생성 시도"""
    try:
        student_answer_obj = StudentAnswer.objects.create(
            student=student,
            slide=slide,
            answer=answer_data,
            is_correct=is_correct,
            score=100.0 if is_correct else 0.0,
            feedback='자동 채점 결과'
        )
        
        print(f"ORM으로 생성 성공: {student_answer_obj.id}")
        return student_answer_obj
        
    except Exception as e:
        print(f"ORM 생성 실패: {e}")
        return None


def debug_foreign_keys():
    """외래키 제약조건을 확인하는 함수"""
    try:
        with connection.cursor() as cursor:
            # SQLite 외래키 설정 확인
            cursor.execute("PRAGMA foreign_keys;")
            fk_status = cursor.fetchone()[0]
            print(f"Foreign Keys 활성화: {fk_status}")
            
            # StudentAnswer 테이블 외래키 확인
            cursor.execute("PRAGMA foreign_key_list(student_studentanswer);")
            fk_list = cursor.fetchall()
            print("StudentAnswer 외래키 목록:")
            for fk in fk_list:
                print(f"  {fk}")
                
            # 테이블 구조 확인
            cursor.execute("PRAGMA table_info(student_studentanswer);")
            table_info = cursor.fetchall()
            print("StudentAnswer 테이블 구조:")
            for column in table_info:
                print(f"  {column}")
                
    except Exception as e:
        print(f"외래키 디버깅 실패: {e}")


def fix_student_class_issue(student):
    """Student의 school_class 문제를 해결하는 함수"""
    try:
        if not student.school_class:
            print("Student에 school_class가 없음 - 기본값 설정 시도")
            
            # 기본 클래스 찾기 또는 생성
            from .models import Class  # 실제 Class 모델 import
            
            default_class = Class.objects.first()
            if not default_class:
                # 기본 클래스 생성
                default_class = Class.objects.create(
                    grade=1,
                    class_number=1,
                    school_name='기본학교',
                    # 다른 필수 필드들...
                )
                print(f"기본 클래스 생성: {default_class}")
            
            student.school_class = default_class
            student.save()
            print(f"Student school_class 수정 완료: {default_class}")
            
    except Exception as e:
        print(f"Student school_class 수정 실패: {e}")



# OX 퀴즈용 헬퍼 함수들
def parse_ox_answer(answer_string):
    """OX 퀴즈 답안 파싱 헬퍼 함수"""
    try:
        if isinstance(answer_string, str):
            # JSON 형태인지 확인
            if answer_string.strip().startswith('{'):
                answer_data = json.loads(answer_string)
                return answer_data.get('answer', ''), answer_data.get('solution', '')
            else:
                # 단순 문자열인 경우
                return answer_string.strip(), ''
        return str(answer_string), ''
    except:
        return str(answer_string), ''


def create_ox_quiz_content(question_text, correct_answer, solution=""):
    """OX 퀴즈 콘텐츠 생성 헬퍼 함수"""
    
    # HTML 템플릿
    page_html = f'''
    <div class="quiz-container p-2 flex items-start justify-center">
        <div class="question-box p-2 w-full max-w-2xl mx-auto relative">
            <!-- 문제 제목 -->
            <div class="text-center mb-8">
                <h1 class="question-text text-2xl md:text-3xl font-bold text-gray-800 mb-4">
                    {question_text}
                </h1>
                <div class="w-20 h-1 bg-gradient-to-r from-pink-500 to-purple-500 mx-auto rounded-full"></div>
            </div>
            <!-- 선택지 -->
            <div class="space-y-4 options-container">
                <div class="option-button bg-gray-50 border-2 border-gray-200 rounded-xl p-4 cursor-pointer flex items-center space-x-4 choice answer" data-clicked="1">
                    <div class="flex-shrink-0">
                        <div class="w-12 h-12 bg-blue-500 text-white rounded-full flex items-center justify-center font-bold text-2xl">O</div>
                    </div>
                    <div class="option-text text-lg md:text-xl font-semibold text-gray-700">맞다</div>
                </div>
                <div class="option-button bg-gray-50 border-2 border-gray-200 rounded-xl p-4 cursor-pointer flex items-center space-x-4 choice answer" data-clicked="2">
                    <div class="flex-shrink-0">
                        <div class="w-12 h-12 bg-red-500 text-white rounded-full flex items-center justify-center font-bold text-2xl">X</div>
                    </div>
                    <div class="option-text text-lg md:text-xl font-semibold text-gray-700">틀리다</div>
                </div>
            </div>
            <!-- 결과 표시 영역 -->
            <div class="text-center mt-8">
                <!-- 정답 GIF (평소에 숨김) -->
                <img id="right-gif" src="/static/img/jungoh/images/right.gif" alt="정답" class="result-gif mx-auto mb-4 hidden absolute top-10 left-10">
                
                <!-- 오답 GIF (평소에 숨김) -->
                <img id="wrong-gif" src="/static/img/jungoh/images/wrong.gif" alt="오답" class="result-gif mx-auto mb-4 hidden absolute top-10 left-10">
            </div>
        </div>
    </div>
    '''
    
    # 답안 JSON
    answer_json = {
        "answer": str(correct_answer),
        "solution": solution
    }
    
    return page_html, json.dumps(answer_json, ensure_ascii=False)



# views.py에 추가할 Line Matching 처리 개선

def handle_line_matching_answer_improved(request, student, slide, content, progress):
    """
    선 매칭(line-matching) 타입 답안 처리 (개선된 버전)
    진행률 동기화 및 연결선 가시성 문제 해결
    """
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

        # 3. ★★★ 개선된 채점 시스템 ★★★
        grading_result = grade_line_matching_comprehensive(student_connections, correct_connections)
        
        # 채점 결과 분석
        total_connections = len(correct_connections)
        correct_count = grading_result['correct_count']
        incorrect_count = grading_result['incorrect_count']
        missing_count = grading_result['missing_count']
        extra_count = grading_result['extra_count']
        
        # ★★★ 향상된 점수 계산 시스템 ★★★
        score_result = calculate_line_matching_score(grading_result, total_connections)
        
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
                'result_type': score_result['result_type'],
                'individual_results': grading_result['individual_results'],
                'accuracy_rate': score_result['accuracy_rate'],
                'completion_rate': score_result['completion_rate']
            }
        }

        student_answer_obj, created = StudentAnswer.objects.update_or_create(
            student=student,
            slide=slide,
            defaults={
                'answer': answer_data,
                'is_correct': score_result['is_correct'],
                'score': score_result['score'],
                'feedback': generate_enhanced_line_feedback(grading_result, score_result, solution),
            }
        )

        print(f"💾 답안 {'생성' if created else '업데이트'}: ID {student_answer_obj.id}")

        # 5. ★★★ 개선된 진도 완료 처리 ★★★
        should_complete_progress = (
            score_result['is_correct'] or 
            score_result['score'] >= 70 or 
            score_result['completion_rate'] >= 80
        )
        
        if should_complete_progress and not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = timezone.now()
            progress.save()
            print(f"✅ 진도 완료 처리 (점수: {score_result['score']}, 완료율: {score_result['completion_rate']}%)")

        # 6. ★★★ 향상된 응답 데이터 구성 ★★★
        response_data = {
            'status': 'success',
            'is_correct': score_result['is_correct'],
            'score': score_result['score'],
            'result_type': score_result['result_type'],
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
                'accuracy_rate': score_result['accuracy_rate'],
                'completion_rate': score_result['completion_rate'],
                'individual_results': grading_result['individual_results']
            },
            'progress_info': {
                'is_completed': progress.is_completed,
                'completion_criteria_met': should_complete_progress,
                'completion_threshold': 70
            },
            'encouragement': generate_contextual_encouragement(score_result, correct_count, total_connections),
            'next_actions': generate_next_action_suggestions(score_result, grading_result)
        }

        return JsonResponse(response_data)

    except Exception as e:
        import traceback
        print(f"❌ handle_line_matching_answer_improved 오류: {str(e)}")
        print(f"🔍 트레이스백: {traceback.format_exc()}")
        return JsonResponse({
            'status': 'error',
            'message': f'선 매칭 답안 처리 중 오류가 발생했습니다: {str(e)}'
        }, status=500)


def grade_line_matching_comprehensive(student_connections, correct_connections):
    """
    선 매칭 답안 종합 채점 함수 (세부 분석 포함)
    """
    try:
        print(f"🔍 종합 선 매칭 채점 시작:")
        print(f"   학생 연결: {student_connections}")
        print(f"   정답 연결: {correct_connections}")
        
        # 채점 결과 초기화
        result = {
            'correct_count': 0,
            'incorrect_count': 0,
            'missing_count': 0,
            'extra_count': 0,
            'individual_results': {},
            'connection_analysis': {}
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
                        'correct_answer': correct_right_id,
                        'feedback': '정확한 연결입니다!'
                    }
                    print(f"   ✅ {left_id} → {student_right_id} (정답)")
                else:
                    # 잘못된 연결
                    result['incorrect_count'] += 1
                    result['individual_results'][left_id] = {
                        'status': 'incorrect',
                        'student_answer': student_right_id,
                        'correct_answer': correct_right_id,
                        'feedback': f'올바른 연결은 {correct_right_id}입니다.'
                    }
                    print(f"   ❌ {left_id} → {student_right_id} (오답, 정답: {correct_right_id})")
            else:
                # 연결하지 않은 항목
                result['missing_count'] += 1
                result['individual_results'][left_id] = {
                    'status': 'missing',
                    'student_answer': None,
                    'correct_answer': correct_right_id,
                    'feedback': f'{correct_right_id}와 연결해야 합니다.'
                }
                print(f"   ⭕ {left_id} (연결 안함, 정답: {correct_right_id})")
        
        # 2. 추가 연결 검사 (정답에 없는 연결)
        for left_id, student_right_id in student_connections.items():
            if left_id not in correct_connections:
                result['extra_count'] += 1
                result['individual_results'][left_id] = {
                    'status': 'extra',
                    'student_answer': student_right_id,
                    'correct_answer': None,
                    'feedback': '이 연결은 필요하지 않습니다.'
                }
                print(f"   ➕ {left_id} → {student_right_id} (불필요한 연결)")
        
        # 3. 연결 패턴 분석
        result['connection_analysis'] = analyze_connection_patterns(
            student_connections, correct_connections, result
        )
        
        print(f"📊 종합 채점 완료: 정답({result['correct_count']}) 오답({result['incorrect_count']}) "
              f"누락({result['missing_count']}) 추가({result['extra_count']})")
        
        return result
        
    except Exception as e:
        print(f"❌ 종합 선 매칭 채점 중 오류: {e}")
        return {
            'correct_count': 0,
            'incorrect_count': 0,
            'missing_count': 0,
            'extra_count': 0,
            'individual_results': {},
            'connection_analysis': {}
        }


def calculate_line_matching_score(grading_result, total_connections):
    """
    선 매칭 점수 계산 (향상된 알고리즘)
    """
    correct_count = grading_result['correct_count']
    incorrect_count = grading_result['incorrect_count']
    missing_count = grading_result['missing_count']
    extra_count = grading_result['extra_count']
    
    # 기본 점수 계산
    if total_connections == 0:
        return {
            'score': 0,
            'is_correct': False,
            'result_type': 'no_questions',
            'accuracy_rate': 0,
            'completion_rate': 0
        }
    
    # 정확도 계산
    accuracy_rate = (correct_count / total_connections) * 100
    
    # 완성도 계산 (전체 연결 중 시도한 비율)
    attempted_connections = correct_count + incorrect_count
    completion_rate = (attempted_connections / total_connections) * 100
    
    # 점수 계산 로직
    if correct_count == total_connections and incorrect_count == 0 and extra_count == 0:
        # 완전 정답
        score = 100
        is_correct = True
        result_type = 'perfect'
    elif correct_count > 0:
        # 부분 정답
        base_score = (correct_count / total_connections) * 80  # 기본 80점까지
        
        # 오답 및 추가 연결 감점
        penalty = (incorrect_count + extra_count) * 3  # 오답당 3점 감점
        
        # 미완성 감점
        incompletion_penalty = missing_count * 2  # 누락당 2점 감점
        
        # 최종 점수
        score = max(base_score - penalty - incompletion_penalty, 0)
        
        is_correct = score >= 80  # 80점 이상을 정답으로 인정
        result_type = 'excellent' if score >= 90 else 'good' if score >= 70 else 'partial'
    else:
        # 전체 오답
        score = 0
        is_correct = False
        result_type = 'incorrect'
    
    return {
        'score': round(score, 1),
        'is_correct': is_correct,
        'result_type': result_type,
        'accuracy_rate': round(accuracy_rate, 1),
        'completion_rate': round(completion_rate, 1)
    }


def analyze_connection_patterns(student_connections, correct_connections, grading_result):
    """
    연결 패턴 분석 (학습 분석용)
    """
    analysis = {
        'common_mistakes': [],
        'strength_areas': [],
        'improvement_suggestions': [],
        'difficulty_level': 'medium'
    }
    
    # 공통 실수 패턴 분석
    mistake_patterns = {}
    for left_id, details in grading_result['individual_results'].items():
        if details['status'] == 'incorrect':
            mistake_key = f"{left_id}_to_{details['student_answer']}"
            if mistake_key not in mistake_patterns:
                mistake_patterns[mistake_key] = {
                    'count': 0,
                    'description': f"{left_id}을(를) {details['student_answer']}와 연결"
                }
            mistake_patterns[mistake_key]['count'] += 1
    
    # 실수 빈도 순으로 정렬
    sorted_mistakes = sorted(mistake_patterns.items(), key=lambda x: x[1]['count'], reverse=True)
    analysis['common_mistakes'] = [mistake[1]['description'] for mistake in sorted_mistakes[:3]]
    
    # 강점 영역 분석
    correct_areas = [
        details['correct_answer'] for details in grading_result['individual_results'].values()
        if details['status'] == 'correct'
    ]
    analysis['strength_areas'] = correct_areas[:3]
    
    # 개선 제안
    if grading_result['missing_count'] > 0:
        analysis['improvement_suggestions'].append("모든 항목을 연결해보세요.")
    
    if grading_result['incorrect_count'] > grading_result['correct_count']:
        analysis['improvement_suggestions'].append("각 항목의 특징을 더 자세히 살펴보세요.")
    
    if grading_result['extra_count'] > 0:
        analysis['improvement_suggestions'].append("불필요한 연결을 피하고 정확한 매칭에 집중하세요.")
    
    # 난이도 평가
    total_items = len(correct_connections)
    if total_items <= 3:
        analysis['difficulty_level'] = 'easy'
    elif total_items <= 6:
        analysis['difficulty_level'] = 'medium'
    else:
        analysis['difficulty_level'] = 'hard'
    
    return analysis


def generate_enhanced_line_feedback(grading_result, score_result, solution):
    """
    향상된 선 매칭 피드백 생성
    """
    feedback_parts = []
    
    # 메인 피드백
    if score_result['result_type'] == 'perfect':
        feedback_parts.append("🎉 완벽합니다! 모든 연결이 정확해요!")
    elif score_result['result_type'] == 'excellent':
        feedback_parts.append("⭐ 훌륭해요! 거의 완벽한 연결입니다!")
    elif score_result['result_type'] == 'good':
        feedback_parts.append("👍 잘했어요! 좋은 이해도를 보여주고 있습니다!")
    elif score_result['result_type'] == 'partial':
        feedback_parts.append("💪 부분적으로 맞았어요! 조금 더 노력해보세요!")
    else:
        feedback_parts.append("🤔 다시 한번 생각해보세요! 천천히 도전해보세요!")
    
    # 상세 분석
    correct_count = grading_result['correct_count']
    total_count = len(grading_result['individual_results'])
    
    if total_count > 0:
        feedback_parts.append(f"📊 {correct_count}/{total_count} 연결이 정확합니다.")
    
    # 정확도 정보
    if score_result['accuracy_rate'] > 0:
        feedback_parts.append(f"🎯 정확도: {score_result['accuracy_rate']}%")
    
    # 개선 제안
    if 'improvement_suggestions' in grading_result.get('connection_analysis', {}):
        suggestions = grading_result['connection_analysis']['improvement_suggestions']
        if suggestions:
            feedback_parts.append("💡 개선 제안:")
            for suggestion in suggestions[:2]:  # 최대 2개만
                feedback_parts.append(f"• {suggestion}")
    
    # 해설 추가
    if solution:
        feedback_parts.append(f"📖 해설: {solution}")
    
    return "\n".join(feedback_parts)


def generate_contextual_encouragement(score_result, correct_count, total_count):
    """
    맥락적 격려 메시지 생성
    """
    encouragement_messages = {
        'perfect': [
            "🌟 완벽한 매칭 실력이에요!",
            "🎯 논리적 사고력이 뛰어나네요!",
            "🏆 최고의 연결 감각입니다!",
            "✨ 모든 관계를 정확히 파악했어요!"
        ],
        'excellent': [
            "👏 거의 완벽해요! 훌륭합니다!",
            "🌟 뛰어난 이해력이에요!",
            "💪 정말 잘하고 있어요!",
            "🎯 논리적 연결 능력이 좋아요!"
        ],
        'good': [
            "👍 좋은 시작이에요!",
            "🌟 계속 발전하고 있어요!",
            "💪 꾸준히 노력하고 있네요!",
            "🎯 점점 더 나아지고 있어요!"
        ],
        'partial': [
            "💪 포기하지 마세요! 할 수 있어요!",
            "🌟 연습하면 더 잘할 수 있어요!",
            "🎯 차근차근 생각해보세요!",
            "✨ 다음엔 더 잘할 거예요!"
        ],
        'incorrect': [
            "🤔 천천히 다시 생각해보세요!",
            "💪 포기하지 말고 다시 도전!",
            "🌟 연습이 실력을 만들어요!",
            "🎯 힌트를 활용해보세요!"
        ]
    }
    
    messages = encouragement_messages.get(score_result['result_type'], encouragement_messages['partial'])
    
    import random
    return random.choice(messages)


def generate_next_action_suggestions(score_result, grading_result):
    """
    다음 행동 제안 생성
    """
    suggestions = []
    
    if score_result['result_type'] == 'perfect':
        suggestions.append("다음 문제로 진행하세요!")
        suggestions.append("비슷한 유형의 문제에 도전해보세요!")
    elif score_result['result_type'] in ['excellent', 'good']:
        suggestions.append("틀린 부분을 다시 확인해보세요!")
        suggestions.append("해설을 읽고 이해를 더 깊게 해보세요!")
    else:
        suggestions.append("힌트를 활용해서 다시 시도해보세요!")
        suggestions.append("각 항목의 특징을 천천히 살펴보세요!")
        suggestions.append("관련 학습 자료를 복습해보세요!")
    
    return suggestions[:3]  # 최대 3개 제안

