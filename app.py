#app.py

import streamlit as st
from datetime import date, timedelta, datetime  

#import 확인하기
import os
import json
import re
from openai import OpenAI

# -----------------------------
# 1) 샘플 데이터셋(예시)
# -----------------------------
DATASET = {
    "museum": {
        "name": "한빛 시립박물관",
        "tagline": "시간을 걷는 전시, 이야기를 듣는 해설",
        "image_url": "https://images.unsplash.com/photo-1528909514045-2fa4ac7a08ba?auto=format&fit=crop&w=1600&q=80",
        "hours": "10:00 ~ 18:00 (월요일 휴관)",
        "location": "전주시",
        "phone": "063-000-0000",
    },
    "docent_services": [
        {
            "id": "DOC-001",
            "name": "상설전 해설 (60분)",
            "duration_min": 60,
            "capacity": 20,
            "price_per_person": 8000,
            "times": ["10:30", "13:30", "15:30"],
            "notes": "초등 고학년 이상 권장. 단체 예약 가능.",
        },
        {
            "id": "DOC-002",
            "name": "특별전 집중 해설 (90분)",
            "duration_min": 90,
            "capacity": 15,
            "price_per_person": 12000,
            "times": ["11:00", "14:00"],
            "notes": "전시 이해를 돕는 Q&A 시간이 포함됩니다.",
        },
        {
            "id": "DOC-003",
            "name": "어린이 가족 해설 (45분)",
            "duration_min": 45,
            "capacity": 12,
            "price_per_group": 30000,  # 그룹당 가격 예시(최대 4인)
            "times": ["10:00", "16:00"],
            "notes": "가족 단위(최대 4인) 권장. 어린이 눈높이 설명.",
        },
    ],
}

# -----------------------------
# 2) 유틸/상태
# -----------------------------
def init_state():
    #>역할: Streamlit이 rerun 될 때마다 상태가 날아가지 않도록 st.session_state 기본값 세팅
    
    #>세팅하는 상태
    #  chat: 채팅 메시지 리스트(assistant/user 역할과 content)
    #  reservations: 저장된 예약 목록(메모리 저장)
    #  draft: 왼쪽 폼에 연결된 “예약 초안”(자동 입력 대상)

    #>포인트
    #  Streamlit은 입력/버튼 누를 때마다 스크립트 전체가 다시 실행되므로, 상태는 session_state로 유지해야 합니다.

    if "reservations" not in st.session_state: #저장된 예약이 없는 경우
        st.session_state.reservations = []

    if "draft" not in st.session_state: #예약입력 폼 데이터가 없는 경우
        st.session_state.draft = {
            "name": "",
            "phone": "",
            "email": "",
            "visit_date": date.today(),
            "service_id": None,
            "time": None,
            "people": 1,
            "memo": "",
        }
        
        
    ######################여기 추가#############################
    if "chat" not in st.session_state: #최초 챗팅인 경우
        st.session_state.chat = [
            {
                "role": "assistant",
                "content": (
                    "안녕하세요. 한빛 시립박물관 해설 예약 도우미입니다.\n"
                    "왼쪽에서 프로그램/날짜/회차/인원을 선택하신 뒤,\n"
                    "오른쪽 채팅으로 ‘추천’, ‘시간 변경’, ‘가격 확인’, ‘예약해줘’를 요청하시면 안내해 드리겠습니다."
                ),
            }
        ]
    ######################여기 추가#############################

# -----------------------------
# 3) 예약 계산/검증/저장
# -----------------------------
def compute_price(draft: dict) -> int:
    #>역할: 현재 draft(초안)에 기반해 예상 금액 계산
    #>입력: draft (service_id, people 등을 참고)
    #>출력: 정수 금액(원)
    #>동작
    # 선택한 프로그램이 price_per_person이면 인당가격 * 인원
    # price_per_group이면 그룹당가격(인원은 제한 체크만 사용)

    # 예약 입력 창에서 선택된 해설 서비스와 일치하는 데이터셋 검색
    svc = next((x for x in DATASET["docent_services"] if x["id"] == draft.get("service_id")), None)
    if not svc: #일치 서비스가 없는 경우
        return 0

    people = max(int(draft.get("people", 1)), 1) #입력 인원 구하기(최소 한명)

    if "price_per_person" in svc: #svc에 price_per_person 있는 경우
        return svc["price_per_person"] * people #사람당 금액 만큼 인원 곱하여 반환
    if "price_per_group" in svc:  #svc에 price_per_group 있는 경우 
        return svc["price_per_group"] #그룹 금액 반환
    return 0



def validate_reservation(draft: dict) -> tuple[bool, str]:
    
    #>역할: “예약 저장” 전에 필수값/제약조건 검증
    #>입력: draft
    #>출력
    # True/False
    # 실패 시 사용자에게 보여줄 에러 메시지
    #>검증 항목
    # 이름/연락처/프로그램/회차 필수
    # 가족 해설(DOC-003 같은 그룹형) 인원 최대 4명
    # 인당형은 정원(capacity) 초과 금지
    # 선택한 시간(time)이 해당 프로그램 times 목록에 실제로 존재하는지 확인

    if not draft.get("name", "").strip(): #이름값이 없다면
        return False, "예약자 이름을 입력해 주세요."
    if not draft.get("phone", "").strip(): #연락처값이 없다면
        return False, "연락처를 입력해 주세요."
    if not draft.get("service_id"): #해설서비스값이 없다면
        return False, "해설 프로그램을 선택해 주세요."
    if not draft.get("time"): #선택회차값이 없다면
        return False, "해설 회차(시간)를 선택해 주세요."

    #선택된 서비스 데이터셋 가져오기
    svc = next((x for x in DATASET["docent_services"] if x["id"] == draft["service_id"]), None)
    if svc:
        if "price_per_group" in svc and int(draft["people"]) > 4: #그룹예약을 골랐고 4명 초과 선택한 경우
            return False, "가족 해설은 최대 4인까지 예약 가능합니다(예시)."
        if "price_per_person" in svc and int(draft["people"]) > int(svc["capacity"]): #선택 인원이 정원보다 큰 경우
            return False, f"정원을 초과했습니다. (정원: {svc['capacity']}명)"

        # 회차 유효성(서비스 times에 포함되는지)
        if draft["time"] not in svc["times"]: #선택 시간이 선택서비스에 유효하지 않는 경우
            return False, f"선택한 회차가 유효하지 않습니다. (가능 회차: {', '.join(svc['times'])})"

    return True, "" #전부 문제 없으면 true,"" 반환

def save_reservation(draft: dict) -> dict:
    #>역할: 예약 확정 저장(현재는 메모리 저장)
    #>입력: draft
    #>출력: 저장된 예약 record(dict)
    #>동작
    # saved_at를 기록
    # total_price 계산해서 함께 저장
    # st.session_state.reservations.append(record)
    #>포인트(확장 과제)
    # 여기만 바꾸면 CSV/DB/구글시트 저장으로 쉽게 확장 가능합니다.

    total = compute_price(draft)  #입력값 전달해서 총 금액 가져오기
    record = {
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "name": draft["name"],
        "phone": draft["phone"],
        "email": draft["email"],
        "visit_date": str(draft["visit_date"]),
        "service_id": draft["service_id"],
        "time": draft["time"],
        "people": int(draft["people"]),
        "memo": draft["memo"],
        "total_price": total,
    }
    st.session_state.reservations.append(record) #session에 예약 정보 record 딕셔너리 저장
    return record #예약 정보 딕셔너리 반환

#######################함수 추가 start#############################
# -----------------------------
# 5) 채팅 렌더링(최근 5개)
# -----------------------------
def render_chat_bubbles(max_visible: int = 5):
    #>역할: 화면에 채팅을 보여주되, 스크롤 폭발을 막기 위해 최근 5개만 노출
    #>동작
    # 5개 초과 메시지는 st.expander()에 숨김
    # assistant는 기본 st.chat_message("assistant")로 출력(아이콘 보임)
    # user는 st.columns([1,3])를 사용해 오른쪽에 배치(카톡 느낌)

    chat = st.session_state.chat  #채팅 정보 가져오기

    if len(chat) > max_visible: #최대 갯수 보다 채팅 갯수가 많은 경우
        old = chat[:-max_visible] #모든 챗팅 앞에서부터 뒤에 5개 전까지 리스트 반환
        with st.expander(f"이전 대화 보기 ({len(old)}개)", expanded=False): #이전 채팅 영역 만들기 ( expanded=False 처음에는 영역 접어서 표현)
            for msg in old: #이전 채팅 정보 반복 접근
                if msg["role"] == "assistant":  #role이 assistant인 경우
                    with st.chat_message("assistant"):  #message 아이콘 assistant로
                        st.markdown(msg["content"])     #대화 내용 출력
                else: #role이 user인 경우
                    l, r = st.columns([1, 3]) #영역 1/3 분할
                    with r:
                        with st.chat_message("user"):   #message 아이콘 user로
                          st.markdown(msg["content"]) #대화 내용 출력

    recent = chat[-max_visible:] #최근 5개 리스트
    for msg in recent:  #최근 5개 채팅 목록 반복 접근
        if msg["role"] == "assistant":  #role이 assistant인 경우
            with st.chat_message("assistant"):  #message 아이콘 assistant로
                st.markdown(msg["content"])    #대화 내용 출력
        else:   #role이 user인 경우
            l, r = st.columns([1, 3]) #영역 1/3 분할
            with r:
                with st.chat_message("user"): #message 아이콘 user로
                    st.markdown(msg["content"]) #대화 내용 출력
                    

# -----------------------------
# 4) 챗봇 컨텍스트/정규화/툴(함수 호출)
# -----------------------------
def build_context_for_llm() -> str:
    #>역할: LLM이 답변할 때 참고할 “요약 텍스트 컨텍스트” 생성
    #>포함
    # 박물관 정보
    # 해설 서비스 목록(회차/정원/가격/비고)
    # 현재 draft(왼쪽 폼 상태)
    # 저장된 예약 건수
    #>왜 필요?
    # 모델이 “어떤 프로그램이 있는지/회차가 뭔지/사용자가 지금 무엇을 선택했는지”를 알고 정확히 안내하게 됩니다.

    m = DATASET["museum"] #데이터셋에서 박물관 정보 가져오기
    services = DATASET["docent_services"] #해설 서비스 정보 가져오기

    service_lines = [] #해설 서비스 데이터 셋을 사용자 정보 문자열로 바꾼 원소 대입할 배열 선언
    for s in services:
        base = f"- {s['id']} | {s['name']} | 회차: {', '.join(s['times'])} | 정원: {s['capacity']}명" #해설 서비스별 기본 정보 문자열
        if "price_per_person" in s: #1인 당 금액인 경우
            base += f" | 1인 {s['price_per_person']:,}" #기본 정보에 1인당 금액 정보 추가
        if "price_per_group" in s:  #그룹 당 금액인 경우
            base += f" | 1그룹 {s['price_per_group']:,}(최대 4인 예시)" #기본 정보에 그룹당 금액 정보 추가
        base += f" | 비고: {s['notes']}"  #기본 정보에 notes 정보 추가
        service_lines.append(base)  # 기본 정보 문자열 들 배열에 원소 추가

    context = f"""
[박물관 정보]
- 이름: {m['name']}
- 운영시간: {m['hours']}
- 위치: {m['location']}
- 문의: {m['phone']}

[해설 서비스 목록]
{chr(10).join(service_lines)}

[현재 작성 중인 예약 초안(draft)]
{st.session_state.draft}

[이미 저장된 예약 건수]
{len(st.session_state.reservations)}건
""".strip() # 박물관과 해설 정보 데이터 셋 사용자 정보 문자열로 변환 /chr(10).join(service_lines) -> 원소 끝 개행 추가 char(10)->아스키 코드 줄바꿈
    return context  #반환


#>역할: OpenAI에게 “이런 형태로 예약 정보를 뽑아내라”는 함수(도구) 스키마
#>뽑는 값
# service, visit_date, time, people, name, phone, email, memo
#>포인트
# 모델이 자연어로 답하기만 하는 게 아니라,
# 예약 정보를 구조화된 JSON으로 뽑도록 유도합니다.
RESERVATION_TOOL = {
    "type": "function",
    "function": {
        "name": "fill_reservation_draft",
        "description": "사용자 대화에서 박물관 해설 예약 정보를 추출해 예약 초안(draft)을 채운다.",
        "parameters": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "해설 프로그램 id 또는 이름. 예: 'DOC-001' 또는 '상설전 해설'",
                },
                "visit_date": {
                    "type": "string",
                    "description": "YYYY-MM-DD 또는 '오늘','내일','모레'. 예: '2026-02-04', '내일'",
                },
                "time": {
                    "type": "string",
                    "description": "회차 시간. 예: '10:30', '14:00'",
                },
                "people": {"type": "integer", "description": "인원 수", "minimum": 1},
                "name": {"type": "string", "description": "예약자 이름(있으면)"},
                "phone": {"type": "string", "description": "연락처(있으면)"},
                "email": {"type": "string", "description": "이메일(있으면)"},
                "memo": {"type": "string", "description": "요청사항(있으면)"},
            },
            "required": [],
        },
    },
}

def normalize_service_id(service_text: str | None) -> str | None:
    
    #>역할: 사용자가 말한 “프로그램”을 내부 표준 ID(DOC-001)로 변환
    #>예
    # “DOC-002” → 그대로 반환
    # “상설전 해설” → DOC-001로 매핑(부분 일치)
    #>왜 필요?
    # 폼의 실제 값은 service_id로 저장되기 때문에, 이름을 입력받아도 ID로 바꿔야 합니다.
    
    if not service_text:  #매개값이 없다면
        return None
    s = service_text.strip()  #있다면 앞뒤 공백 제거

    m = re.search(r"(DOC-\d{3})", s.upper())  #해설 서비스 텍스트에서 서비스 아이디검색
    if m: #있다면
        return m.group(1) #찾은 아이디값 반환

    # 부분 일치(이름 기반)
    s_compact = s.replace(" ", "")  #공백들 제거
    for svc in DATASET["docent_services"]:  #해설 서비스 데이터 셋들 접근
        if svc["name"].replace(" ", "") in s_compact or s in svc["name"]: #해설 서비스의 이름이 포함되는 경우
            return svc["id"]  #해당 서비스 아이디 반환
    return None #없다면 None 반환


def normalize_visit_date(text: str | None) -> date | None:
    #>역할: 날짜 표현을 표준 date로 변환
    #>지원
    # “오늘/내일/모레”
    # >“YYYY-MM-DD”
    #>왜 필요?
    # Streamlit selectbox 기본 값과 연동하려면 date 타입이 제일 안정적입니다.

    if not text:  #매개변수에 값이 없다면
        return None
    t = text.strip()  #있다면 공백 제거

    today = date.today()  #오늘 날짜객체 
    if t == "오늘": #매개변수에 값이 오늘 이 있는 경우
        return today  #오늘 날짜 반환
    if t == "내일": #매개변수에 값이 내일이 있는 경우
        return today + timedelta(days=1)  #오늘 날짜 +1 반환
    if t == "모레": #매개변수에 값이 모레가 있는 경우
        return today + timedelta(days=2)  #오늘 날짜에 +2 반환

    # YYYY-MM-DD
    try:
        return datetime.strptime(t, "%Y-%m-%d").date() # 오늘 내일 모레가 아닌 경우 날짜를 date로 변환
    except Exception:
        return None #변환 오류 시 None 반환

def normalize_time(text: str | None) -> str | None:
    #>역할: 시간 표현을 “HH:MM”로 정규화
    #>지원 예시
    # “14:00” → “14:00”
    # “14시” → “14:00”
    # “오후 2시 30분” → “14:30”
    #>왜 필요?
    # 서비스 회차(times)가 “10:30”, “14:00”처럼 정해져 있으므로 같은 포맷으로 맞춰야 비교가 됩니다.

    """'14시', '14:00', '오후 2시' 등 간단 대응"""
    if not text:  #매개값이 없는 경우
        return None
    t = text.strip()  #있다면 공백 제거

    # HH:MM 형태면 그대로
    if re.fullmatch(r"\d{1,2}:\d{2}", t): #매개값이 HH:MM 또는 H:MM 형식인 경우
        hh, mm = t.split(":") #:로 잘라내 hh,mm 각각 대입
        return f"{int(hh):02d}:{int(mm):02d}" #HH:MM 형식으로 반환

    # "14시", "14시 30분"
    m = re.search(r"(\d{1,2})\s*시(?:\s*(\d{1,2})\s*분)?", t) # 시, 분 문자열 형식인 경우 시 / 분 그룹 나누기
    if m:
        hh = int(m.group(1))  # 시 그룹 hh 대입
        mm = int(m.group(2)) if m.group(2) else 0 # 분 그룹이 있으면 mm 대입 없으면 0대입

        # 오후/저녁/밤 키워드가 있으면 12시간 보정
        if any(k in t for k in ["오후", "저녁", "밤"]) and hh < 12: #오후,저녁, 밤이 있는데 시간이 12시보다 작은 경우
            hh += 12  # 12 더하기 (24시 표현)
        return f"{hh:02d}:{mm:02d}" #HH:MM 형식 반환

    # "오후 2" 같은 형태
    m2 = re.search(r"(오전|오후)\s*(\d{1,2})(?::(\d{2}))?", t) #오전, 오후 HH:MM 형식 인 경우 오전오후/시/분 그룹 나누기
    if m2:
        ap = m2.group(1)  #오전 오후 ap 대입
        hh = int(m2.group(2)) # 시 그룹 hh 대입
        mm = int(m2.group(3)) if m2.group(3) else 0 # 분 그룹이 있으면 mm 대입 없으면 0대입
        if ap == "오후" and hh < 12:  #오후 인데 12보다 작은 경우
            hh += 12  #12 더하기
        if ap == "오전" and hh == 12: #오전인데 12시인 경우
            hh = 0  # 0 대입
        return f"{hh:02d}:{mm:02d}" #HH:MM 형식으로 반환

    return None #시간 형식이 안맞으면 None 반환


def apply_to_draft(payload: dict) -> dict:
    #>역할: 모델이 뽑아준 JSON(payload)을 st.session_state.draft에 반영
    #>입력: tool이 반환한 payload(dict)
    #>출력: 변경된 항목만 모은 changed dict
    #>동작
    # service → service_id로 정규화 후 저장
    # visit_date/time/people 등도 정규화 후 저장
    # 이름/연락처 등 텍스트도 있으면 반영
    #>포인트
    # 이 함수 덕분에 “예약해줘” 한 마디로도 폼이 자동으로 채워집니다.

    draft = st.session_state.draft #입력 폼 draft에 저장
    changed = {}  #빈 딕셔너리 선언

    ############################# normalize_service_id() 함수 추가 #################################
    service_id = normalize_service_id(payload.get("service")) #매개 변수 payload에서 service 키값으로 service id 찾아 대입
    if service_id and service_id != draft.get("service_id"): #검색한 service id와 현재 선택된 service id가 다르다면
        draft["service_id"] = service_id  #입력 폼 service_id 변경
        changed["service_id"] = service_id  #변경 정보 삽입 "service_id" : 변경service id

    ############################# normalize_visit_date() 함수 추가 #################################
    d = normalize_visit_date(payload.get("visit_date")) #매개 변수 payload에서 visit_date 키 값으로 방문 날짜 찾아 d에 대입
    if d and d != draft.get("visit_date"):  #찾은 방문날짜와 현재 입력 폼 날짜가 다르다면
        draft["visit_date"] = d #찾은 방문 날짜로 입력 폼 날짜 변경
        changed["visit_date"] = str(d)  #변경 정보 삽입 "visit_date" : 변경날짜

    ############################# normalize_time() 함수 추가 #################################
    t = normalize_time(payload.get("time")) #매개 변수 payload에서 time 키 값으로 방문 시간 찾아 t에 대입
    if t and t != draft.get("time"):  #찾은 시간 정보와 입력 폼 시간이 다르다면
        draft["time"] = t #찾은 시간 정보로 입력 폼 변경
        changed["time"] = t #변경 정보 삽입 "tiem":변경 시간

    p = payload.get("people") #매개 변수 payload에서 people 키 값으로 인원 정보 찾아 p에 대입
    if isinstance(p, int) and p >= 1 and p != draft.get("people"): #p가 int 타입이고 1 이상이고 현재 입력 폼 인원과 다른 경우
        draft["people"] = p #입력 폼 인원 변경
        changed["people"] = p #변경 정보 삽입 "people" : 변경인원

    for k in ["name", "phone", "email", "memo"]:
        v = payload.get(k)  #payload에서 각 name,phone,email,meno 키 값 찾아 v 대입
        if isinstance(v, str) and v.strip():  #v 가 String이고 공백 제거 시 빈 문자열이 아니라면
            v = v.strip() # 공백 제거
            if v != draft.get(k): #입력 폼 name,phone,email,memo 값이 현재 payload에서 찾은 것과 다르다면
                draft[k] = v  #입력 폼 변경
                changed[k] = v  #변경 정보 삽입

    st.session_state.draft = draft #수정 정보 다시 입력폼에 적용
    return changed  #수정 정보 딕셔너리 반환

                    
def chat_and_maybe_fill_draft(user_message: str) -> tuple[str, dict]:
    #>역할
    # 일반 상담이면 일반 답변
    # 예약 의도가 있으면 fill_reservation_draft 툴 호출 → draft 자동 채움
    #>입력: 사용자 메시지 텍스트
    #>출력
    # 사용자에게 보여줄 답변 문자열
    # 변경된 필드 dict(changed)
    #>동작 흐름
    # system prompt에 “예약 의도가 있으면 도구 호출” 규칙을 명시
    # OpenAI 호출 시 tools=[RESERVATION_TOOL], tool_choice="auto"
    # tool_calls가 오면:
    #   arguments(JSON) 파싱
    #   apply_to_draft()로 폼 상태 갱신
    #   “왼쪽 폼 반영됨 / 부족한 정보는 무엇인지” 요약 안내문 생성
    # tool_calls가 없으면:
    #   그냥 일반 답변 반환
    #>포인트(강의용)
    # “LLM = 자연어 응답”이 아니라 “LLM = 구조화 추출 + UI 상태 업데이트”로 확장되는 부분입니다.

    # api_key = os.environ["OPENAI_API_KEY"]
    api_key = st.secrets["OPENAI_API_KEY"] #########streamlit cloud 배포시에는 변경
    if not api_key:
        return "OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다. 키를 설정한 뒤 다시 시도해 주세요.", {}

    client = OpenAI(api_key=api_key)  #OpenAI 사용 준비

    system_prompt = (
        "당신은 박물관 해설 예약 도우미입니다.\n"
        "사용자가 '예약해줘', '예약 진행', '내일 14시에 2명 예약'처럼 예약 의사를 보이면,\n"
        "가능한 예약 정보를 추출해서 fill_reservation_draft 도구를 호출하십시오.\n"
        "예약 의사가 명확하지 않으면 도구를 호출하지 말고 일반 안내/추천만 하십시오.\n"
        "도구 호출 시 누락된 정보는 비워두고, 무엇이 더 필요한지 질문하십시오.\n"
        "데이터셋에 없는 서비스/회차는 임의로 만들지 말고 가능한 선택지를 안내하십시오."
    ) #llm에게 주고자할 기본 정보

    ############### build_context_for_llm() 함수 추가 #################
    context = build_context_for_llm() #데이터 셋 정보 용 문자열 생성 후 context 대입 

    # 비용/지연 고려: 최근 히스토리만
    history = st.session_state.chat[-10:] #최근 10개 히스토리만 리스트에 저장

    messages = [{"role": "system", "content": system_prompt}] #llm에게 쥴 system 정보용 딕셔너리 셋팅
    messages.append({"role": "system", "content": f"참고 컨텍스트:\n{context}"}) #llm에게 줄 참고형 데이터 셋 정보  딕셔너리 셋팅
    for m in history: #최근 챗팅 정보 
        messages.append({"role": m["role"], "content": m["content"]}) #딕셔너리에 추가
    messages.append({"role": "user", "content": user_message})  #현재 사용자 질문 딕셔너리에 추가

    resp = client.chat.completions.create(
        model="gpt-4o-mini",  #사용할 모델 설정 4-mini가 비교적 빠름
        messages=messages,  #llm 전달 메시지
        ############### RESERVATION_TOOL 딕셔너리 추가 #################
        tools=[RESERVATION_TOOL], #모델이 호출할 수 있는 함수 목록 제공
        tool_choice="auto", #모델이 알아서 판단하여 함수 실생
        temperature=0.3, #출력의 랜덤성(창의성) 조절/값이 커질 수록 창의적(예측 어려움)
    ) # llm 요청

    msg = resp.choices[0].message #llm 응답 메시지 msg에 대입
    changed = {}  #변경 사항 담을 딕셔너리

    # 1) tool 호출이 있으면: draft 채우고, 우리가 요약 안내를 만든다
    if getattr(msg, "tool_calls", None):  #응답 msg에 tool_calls가 있다면   ######## getattr() 파이썬 내장함수
        for tc in msg.tool_calls: #tool_calls 갯수 만큼 반복
            if tc.function.name == "fill_reservation_draft":  #tool_calls가 fill_reservation_draft라면
                try:
                    payload = json.loads(tc.function.arguments or "{}") #tool_calls의 function하위 데이터 딕셔너리로 변환
                except Exception:
                    payload = {}  #변환하다 오류나면 빈 딕셔너리 대입
                    
                ############### apply_to_draft() 함수 추가 #################
                changed = apply_to_draft(payload) #얻어온 정보로 입력 폼 셋팅 함수 호출 후 변경 딕셔너리 changed 대입 

        draft = st.session_state.draft  #현재 입력 폼 얻어오기

        # 서비스/회차 유효성 확인(가능한 경우 안내)
        svc = next((x for x in DATASET["docent_services"] if x["id"] == draft.get("service_id")), None) #현재 입력 해설 서비스와 일치하는 데이터셋 얻기
        time_ok = True
        if svc and draft.get("time") and draft["time"] not in svc["times"]: #입력한 시간정보가 데이터셋에 포함되지 않는 경우
            time_ok = False

        lines = []
        if changed: #변경사항이 있다면
            lines.append("요청하신 내용으로 왼쪽 예약 폼에 정보를 반영했습니다.")
        else: #변경사항이 없다면
            lines.append("예약 요청은 확인했습니다. 다만, 폼에 반영할 정보가 부족합니다.")

        lines.append("")
        lines.append("현재 초안 상태:")
        lines.append(f"- 프로그램: {draft.get('service_id') or '미선택'}")
        lines.append(f"- 날짜: {draft.get('visit_date')}")
        lines.append(f"- 시간: {draft.get('time') or '미선택'}")
        lines.append(f"- 인원: {draft.get('people')}")
        lines.append("")  #예약 초안 정보 리스트 추가

        # 부족/오류 체크
        missing = []
        if not draft.get("service_id"): #입력 해설아이디가 없는 경우
            missing.append("프로그램")
        if not draft.get("time"): #입력 시간이 없는 경우
            missing.append("회차(시간)")
        if not draft.get("name"): #입력 이름이 없는 경우
            missing.append("이름")
        if not draft.get("phone"):  #입력 연락처가 없는 경우
            missing.append("연락처")

        if svc and not time_ok: #선택한 시스템 정보도 있는데 회차를 잘 못 선택한 경우
            lines.append(f"선택하신 회차({draft['time']})는 해당 프로그램에 없습니다.")
            lines.append(f"가능 회차: {', '.join(svc['times'])}")
            lines.append("시간을 다시 말씀해 주시거나, 왼쪽 폼에서 회차를 선택해 주세요.")
            lines.append("")

        if missing: # 추가 정보가 필요한 경우
            lines.append("추가로 필요한 정보:")
            lines.append("- " + ", ".join(missing))
            lines.append("채팅으로 알려주시거나, 왼쪽 폼에서 입력해 주세요.")
        else: #추가 정보가 필요 없는 경우 
            lines.append("왼쪽에서 내용을 최종 확인하신 뒤 **예약 저장** 버튼으로 확정하시면 됩니다.")

        return "\n".join(lines), changed #예약 정보 문자열과 변경사항 딕셔너리 반환

    # 2) tool 호출이 없으면: 모델의 일반 답변 사용
    content = (msg.content or "").strip() # 응답 msg의 content 또는 없다면 빈문자열 앞뒤공백 제어
    if not content: #content 없는 경우
        content = "원하시는 내용을 조금 더 구체적으로 말씀해 주세요. (예: ‘내일 14:00 특별전 2명 예약해줘’)"
    return content, changed # 응답 컨텐츠 와 변경사항 반환
                    
#######################함수 추가 end#############################


# -----------------------------
# 6) UI
# -----------------------------
def main():
    #>역할: 페이지 전체 레이아웃을 구성하고, 폼/챗봇 입력을 연결
    #>구성
    # st.set_page_config(...)
    # init_state()
    # left, right = st.columns(...)
    # left: 이미지 카드 + 예약 폼 + 저장/초기화 + 예약 목록
    # right: 채팅 출력(render_chat_bubbles) + 입력(st.chat_input)
    #>가장 중요한 포인트
    # st.chat_input으로 메시지 입력 → chat_and_maybe_fill_draft 호출
    # draft가 바뀌면 왼쪽 폼에 즉시 반영되도록 st.rerun() 사용

    st.set_page_config(page_title="박물관 해설 예약", layout="wide")

    init_state()    #####################여기 init_state() 함수 수정하기#######################
   
    draft = st.session_state.draft

    m = DATASET["museum"]
     
    st.title("박물관 해설 서비스 예약 시스템")
    st.caption("")

    left, right = st.columns([1, 1.2], gap="large")

    # ---- 왼쪽: 이미지 + 예약 폼
    with left:
        st.markdown(
            f"""
            <div style="padding:16px;border-radius:16px;border:1px solid #eee;">
              <div style="font-size:22px;font-weight:700;margin-bottom:6px;">{m['name']}</div>
              <div style="color:#555;margin-bottom:10px;">{m['tagline']}</div>
              <img src="{m['image_url']}" style="width:100%;border-radius:14px;object-fit:cover;max-height:260px;" />
              <div style="margin-top:10px;color:#444;font-size:14px;line-height:1.6;">
                <b>운영시간</b>: {m['hours']}<br/>
                <b>위치</b>: {m['location']}<br/>
                <b>문의</b>: {m['phone']}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.write("")
        st.subheader("해설 예약 폼")

        c1, c2 = st.columns(2)
        with c1:
            draft["name"] = st.text_input("예약자 이름", value=draft["name"], placeholder="홍길동")
        with c2:
            draft["phone"] = st.text_input("연락처", value=draft["phone"], placeholder="010-0000-0000")

        draft["email"] = st.text_input("이메일(선택)", value=draft["email"], placeholder="example@email.com")

        # 날짜 선택(다음 14일)
        today = date.today()
        days = [today + timedelta(days=i) for i in range(14)]
        
        default_idx = days.index(draft["visit_date"]) if draft["visit_date"] in days else 0 #14일치 중 선택된 날짜가 있다면 인덱스 반환 없다면 0
        
        draft["visit_date"] = st.selectbox(
            "방문 날짜",  #초기 옵션
            options=days, #옵션 목록
            index=default_idx,  #초기 선택이 있는 경우 
            format_func=lambda d: d.strftime("%Y-%m-%d (%a)"),  #date 리스트 날짜 포맷으로 변경
        )

        # 서비스 선택
        svc_labels = ["선택하세요"] + [f"{s['name']} ({s['id']})" for s in DATASET["docent_services"]] #해설 서비스 옵션 목록 리스트 작성
        
        current_label = "선택하세요" #현재 라벨
        if draft["service_id"]: #선택 서비스가 있는 경우
            found = next((x for x in DATASET["docent_services"] if x["id"] == draft["service_id"]), None) #일치하는 서비스 찾기
            if found: #찾았으면
                current_label = f"{found['name']} ({found['id']})"  #현재 라밸 변경


        picked_svc = st.selectbox("해설 프로그램", svc_labels, index=svc_labels.index(current_label)) #해설 프로그램 콤보 박스 출력 옵션은 svc_labels, 선택 인덱스는 current_label과 일치하는 인덱스 / 이후 항목 선택시 picked_svc에 대입
        
        if picked_svc != "선택하세요": # 선택항목이 "선택하세요"가 아니면
            draft["service_id"] = picked_svc.split("(")[-1].replace(")", "").strip() #선택 항목에서 service_id 분리하여 저장
        else:
            draft["service_id"] = None  # 선택하세요 인 경우 None 저장
        
        # 서비스별 회차/정원/가격 힌트
        times = []
        capacity = None
        notes = ""
        price_hint = ""
        is_group = False

        if draft["service_id"]: #선택항목이 있는 경우 선택 예시 정보 와 선택 회차, 인원 정보 항목 데이터 셋팅
            svc = next((x for x in DATASET["docent_services"] if x["id"] == draft["service_id"]), None)
            if svc:
                times = svc["times"]
                capacity = svc["capacity"]
                notes = svc["notes"]
                if "price_per_person" in svc:
                    price_hint = f"1인 {svc['price_per_person']:,}" # currency : 금액 포맷팅
                elif "price_per_group" in svc:
                    price_hint = f"1그룹 {svc['price_per_group']:,}(최대 4인 예시)"
                    is_group = True
        
        t1, t2 = st.columns(2)
        with t1:
            draft["time"] = st.selectbox(
                "회차(시간)",
                options=["선택하세요"] + times,
                index=0 if draft["time"] not in times else (times.index(draft["time"]) + 1), #시간 정보가 없으면 선택하세요 지정 있으면 인덱스+1 해서 선택 (0번은 '선택하세요')
            )
            
            if draft["time"] == "선택하세요":
                draft["time"] = None  # 선택 시간이 선택하세요 이면 time -> None
                
        with t2:
            if is_group:    #그룹 신청 인 경우 
                draft["people"] = st.number_input(
                    "인원(최대 4인)",
                    min_value=1,
                    max_value=4,
                    value=min(int(draft["people"]), 4), #입력 인원이 4보다 커도 4명으로 컷팅
                    step=1,
                    key="abc"
                )
            else:    #그룹 신청 아닌 경우 
                max_people = int(capacity) if capacity is not None else 20 #정원이 None이면 20 아니면 정원 값
                draft["people"] = st.number_input(
                    "인원",
                    min_value=1,
                    max_value=max_people,
                    value=min(int(draft["people"]), max_people),
                    step=1,
                    key="abc1"
                )
        if draft["service_id"]: # 선택 서비스 있으면 안내 창 출력
            st.info(f"정원: {capacity}명 / 가격: {price_hint}\n\n비고: {notes}")
        
        draft["memo"] = st.text_area("요청사항(선택)", value=draft["memo"])

        total = compute_price(draft)  #총 금액 가져오기    compute_price() 함수 추가하기!!!!!
        st.markdown(f"### 예상 결제금액: **{total:,}**")
        b1, b2 = st.columns(2)
        with b1:
            if st.button("예약 저장", use_container_width=True): #  use_container_width=True ->버튼을 부모 컨테이너 너비 맞춤 / 버튼 출력 클릭 시 if 실행
                ok, msg = validate_reservation(draft) # 유효성 검사
                if not ok: #유효성 검사 false 경우
                    st.error(msg) #에러 msg 처리
                else: #유효성 검사 true 경우
                    saved = save_reservation(draft) #예약 저장 후 딕셔너리 반환
                    st.success("예약이 저장되었습니다.")
                    summary = (
                        f"예약 저장 완료\n"
                        f"- 날짜: {saved['visit_date']}\n"
                        f"- 프로그램: {saved['service_id']}\n"
                        f"- 시간: {saved['time']}\n"
                        f"- 인원: {saved['people']}\n"
                        f"- 금액: {saved['total_price']:,}"
                    )
            
        with b2:
            if st.button("초안 초기화", use_container_width=True):
                st.session_state.draft = {
                    "name": "",
                    "phone": "",
                    "email": "",
                    "visit_date": date.today(),
                    "service_id": None,
                    "time": None,
                    "people": 1,
                    "memo": "",
                }
                st.rerun()

        with st.expander("저장된 예약 보기"): #아코디언 출력 
            if not st.session_state.reservations: #예약 정보 없을 시
                st.caption("아직 저장된 예약이 없습니다.")
            else: #예약 정보 출력
                st.dataframe(st.session_state.reservations, use_container_width=True)

    # ---- 오른쪽: 챗봇(최근 5개 + 입력 하단 + 예약해줘 → 폼 채움)
    with right:
        st.subheader("해설 예약 도우미 챗봇")
        
        ##############################여기부터#############################
        ####################render_chat_bubbles() 함수 추가######################
        render_chat_bubbles(max_visible=5) # 이전 채팅 내용 렌더링
        ##############################여기까지#############################

        user_text = st.chat_input("예) 내일 14:00 특별전 2명 예약해줘 / 상설전 예약 가능해?")

        ##############################여기부터#############################
        if user_text: #사용자가 입력하는 경우
            st.session_state.chat.append({"role": "user", "content": user_text})

            with st.chat_message("assistant"):
                with st.spinner("답변 생성 중..."):  # Streamlit에서 “지금 처리 중입니다 ⏳” 라는 로딩 표시를 보여주는 UI입니다.
                    ####################chat_and_maybe_fill_draft() 함수 추가######################
                    answer, _changed = chat_and_maybe_fill_draft(user_text)
                    st.markdown(answer) #답변 오면 출력

            st.session_state.chat.append({"role": "assistant", "content": answer}) #채팅 이력에 추가

            # draft가 채워졌을 수 있으니 폼 반영을 위해 rerun
            st.rerun()
        ##############################여기까지#############################

if __name__ == "__main__":  #직접 실행 시 main 호출
    main()