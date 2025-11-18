import os
from datetime import datetime, timedelta, date as date_type
from typing import List, Optional, Literal, Dict, Any
import hashlib
import random

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr

from database import db, create_document, get_documents

app = FastAPI(title="Attendance Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------- Models -----------------------------
class OTPRequest(BaseModel):
    phone: str

class OTPVerify(BaseModel):
    phone: str
    code: str
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    course: Optional[str] = None
    semester: Optional[int] = Field(None, ge=1, le=8)

class RegisterEmail(BaseModel):
    name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    course: str
    semester: int = Field(..., ge=1, le=8)

class LoginEmail(BaseModel):
    email: EmailStr
    password: str

class SubjectIn(BaseModel):
    code: str
    name: str
    semester: int = Field(..., ge=1, le=8)

class AcademicEventIn(BaseModel):
    title: str
    date: date_type
    type: Literal["holiday", "event", "semester_start", "semester_end"] = "holiday"

class TeacherLeaveIn(BaseModel):
    subject_code: str
    date: date_type
    reason: Optional[str] = None

class StudentUpdate(BaseModel):
    name: Optional[str] = None
    semester: Optional[int] = Field(None, ge=1, le=8)
    course: Optional[str] = None
    subjects: Optional[List[str]] = None
    min_threshold: Optional[float] = Field(None, ge=0, le=1)

class AttendanceMark(BaseModel):
    student_id: str
    subject_code: str
    date: date_type
    sessions_held: int = 1
    attended_count: int = 0
    status: Literal["attended", "not_attended", "teacher_leave", "holiday", "mixed"] = "mixed"

# ----------------------------- Helpers -----------------------------

def now_utc() -> datetime:
    return datetime.utcnow()

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def ensure_db():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")


def get_student_by_email(email: str):
    ensure_db()
    return db.student.find_one({"email": email})


def get_student_by_phone(phone: str):
    ensure_db()
    return db.student.find_one({"phone": phone})


def serialize(doc: Dict[str, Any]):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    return doc

# ----------------------------- Basic -----------------------------
@app.get("/")
def root():
    return {"status": "ok", "service": "attendance-tracker"}

@app.get("/test")
def test_database():
    response = {
        "backend": "running",
        "database": "connected" if db is not None else "not_configured",
        "collections": []
    }
    if db is not None:
        try:
            response["collections"] = db.list_collection_names()
        except Exception as e:
            response["error"] = str(e)
    return response

# ----------------------------- Auth -----------------------------
@app.post("/auth/request-otp")
def request_otp(payload: OTPRequest):
    ensure_db()
    code = f"{random.randint(100000, 999999)}"
    expires = now_utc() + timedelta(minutes=5)
    db.otp.delete_many({"phone": payload.phone})
    create_document("otp", {"phone": payload.phone, "code": code, "expires_at": expires})
    return {"sent": True, "dev_code": code}

@app.post("/auth/verify-otp")
def verify_otp(payload: OTPVerify):
    ensure_db()
    rec = db.otp.find_one({"phone": payload.phone, "code": payload.code})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid code")
    if rec.get("expires_at") and rec["expires_at"] < now_utc():
        raise HTTPException(status_code=400, detail="Code expired")
    student = get_student_by_phone(payload.phone)
    if not student:
        doc = {
            "name": payload.name or "Student",
            "email": payload.email,
            "phone": payload.phone,
            "password_hash": hash_password(payload.password) if payload.password else None,
            "role": "student",
            "course": payload.course,
            "semester": payload.semester,
            "subjects": [],
            "min_threshold": 0.67,
        }
        new_id = create_document("student", doc)
        student = db.student.find_one({"_id": db.ObjectId(new_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"phone": payload.phone})
    db.otp.delete_many({"phone": payload.phone})
    return {"token": str(student.get("_id")), "student": serialize(student)}

@app.post("/auth/register-email")
def register_email(payload: RegisterEmail):
    ensure_db()
    if get_student_by_email(payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "password_hash": hash_password(payload.password),
        "role": "student",
        "course": payload.course,
        "semester": payload.semester,
        "subjects": [],
        "min_threshold": 0.67,
    }
    new_id = create_document("student", doc)
    s = db.student.find_one({"_id": db.ObjectId(new_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"email": payload.email})
    return {"token": str(s.get("_id")), "student": serialize(s)}

@app.post("/auth/login-email")
def login_email(payload: LoginEmail):
    ensure_db()
    s = get_student_by_email(payload.email)
    if not s or s.get("password_hash") != hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": str(s.get("_id")), "student": serialize(s)}

# ----------------------------- Metadata -----------------------------
@app.get("/semesters")
def semesters():
    return {"semesters": list(range(1, 9))}

@app.post("/admin/subjects")
def admin_add_subject(subj: SubjectIn):
    ensure_db()
    if db.subject.find_one({"code": subj.code}):
        raise HTTPException(status_code=400, detail="Subject code exists")
    create_document("subject", subj.model_dump())
    return {"ok": True}

@app.get("/subjects")
def list_subjects(semester: int = Query(..., ge=1, le=8)):
    ensure_db()
    items = list(db.subject.find({"semester": semester}))
    return {"subjects": [serialize(i) for i in items]}

@app.post("/admin/calendar")
def admin_add_calendar(event: AcademicEventIn):
    ensure_db()
    create_document("academiccalendar", event.model_dump())
    return {"ok": True}

@app.get("/calendar")
def get_calendar(frm: Optional[date_type] = None, to: Optional[date_type] = None):
    ensure_db()
    q: Dict[str, Any] = {}
    if frm or to:
        q["date"] = {}
        if frm:
            q["date"]["$gte"] = frm
        if to:
            q["date"]["$lte"] = to
    items = list(db.academiccalendar.find(q))
    return {"events": [serialize(i) for i in items]}

@app.post("/admin/teacher-leave")
def admin_teacher_leave(tl: TeacherLeaveIn):
    ensure_db()
    create_document("teacherleave", tl.model_dump())
    return {"ok": True}

@app.get("/teacher-leave")
def get_teacher_leave(subject_code: Optional[str] = None, d: Optional[date_type] = None):
    ensure_db()
    q: Dict[str, Any] = {}
    if subject_code:
        q["subject_code"] = subject_code
    if d:
        q["date"] = d
    items = list(db.teacherleave.find(q))
    return {"items": [serialize(i) for i in items]}

# ----------------------------- Student Profile -----------------------------
@app.put("/student/{student_id}")
def update_student(student_id: str, payload: StudentUpdate):
    ensure_db()
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    db.student.update_one({"_id": db.ObjectId(student_id) if hasattr(db, 'ObjectId') else {"id": student_id}}, {"$set": update})
    s = db.student.find_one({"_id": db.ObjectId(student_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"id": student_id})
    return {"student": serialize(s)}

@app.get("/student/{student_id}")
def get_student(student_id: str):
    ensure_db()
    s = db.student.find_one({"_id": db.ObjectId(student_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"id": student_id})
    if not s:
        raise HTTPException(status_code=404, detail="Not found")
    return {"student": serialize(s)}

# ----------------------------- Attendance -----------------------------

def is_holiday(d: date_type) -> bool:
    return db.academiccalendar.find_one({"date": d, "type": "holiday"}) is not None

def is_teacher_leave(subject_code: str, d: date_type) -> bool:
    return db.teacherleave.find_one({"subject_code": subject_code, "date": d}) is not None

@app.get("/attendance/day")
def attendance_day(student_id: str, d: date_type):
    ensure_db()
    # Auto-mark as holiday for past days with no status at end of day
    today = datetime.utcnow().date()
    s = db.student.find_one({"_id": db.ObjectId(student_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"id": student_id})
    subs = s.get("subjects", []) if s else []
    if d < today and not is_holiday(d):
        for code in subs:
            if not is_teacher_leave(code, d):
                q = {"student_id": student_id, "subject_code": code, "date": d}
                if not db.attendancerecord.find_one(q):
                    create_document("attendancerecord", {"student_id": student_id, "subject_code": code, "date": d, "sessions_held": 0, "attended_count": 0, "status": "holiday"})

    records = list(db.attendancerecord.find({"student_id": student_id, "date": d}))
    # Suggest defaults
    suggestions: Dict[str, str] = {}
    for code in subs:
        if is_holiday(d):
            suggestions[code] = "holiday"
        elif is_teacher_leave(code, d):
            suggestions[code] = "teacher_leave"
    return {
        "records": [serialize(r) for r in records],
        "suggestions": suggestions
    }

@app.post("/attendance/mark")
def attendance_mark(payload: AttendanceMark):
    ensure_db()
    # Normalize based on calendar and teacher leave if status not explicitly set
    if is_holiday(payload.date):
        payload.status = "holiday"
        payload.sessions_held = max(payload.sessions_held, 1)
        payload.attended_count = 0
    elif is_teacher_leave(payload.subject_code, payload.date):
        payload.status = "teacher_leave"
        payload.attended_count = 0
    # Upsert by (student_id, subject_code, date)
    q = {"student_id": payload.student_id, "subject_code": payload.subject_code, "date": payload.date}
    doc = db.attendancerecord.find_one(q)
    body = payload.model_dump()
    if doc:
        db.attendancerecord.update_one(q, {"$set": body})
    else:
        create_document("attendancerecord", body)
    return {"ok": True}

@app.get("/attendance/stats")
def attendance_stats(student_id: str, period: Literal["weekly", "monthly", "semester"] = "weekly"):
    ensure_db()
    today = datetime.utcnow().date()
    if period == "weekly":
        start = today - timedelta(days=today.weekday())
    elif period == "monthly":
        start = today.replace(day=1)
    else:
        # attempt to use academic calendar semester_start if present
        sem_start = db.academiccalendar.find_one({"type": "semester_start"}, sort=[("date", -1)])
        start = sem_start["date"] if sem_start else today.replace(day=1)
    q = {"student_id": student_id, "date": {"$gte": start, "$lte": today}}
    recs = list(db.attendancerecord.find(q))

    per_subject: Dict[str, Dict[str, float]] = {}
    total_attended = 0
    total_held = 0
    for r in recs:
        code = r["subject_code"]
        status = r.get("status")
        sessions = int(r.get("sessions_held", 1))
        attended = int(r.get("attended_count", 0))
        # holidays and teacher_leave don't count
        if status in ("holiday", "teacher_leave"):
            continue
        total_held += sessions
        total_attended += attended
        if code not in per_subject:
            per_subject[code] = {"attended": 0, "held": 0}
        per_subject[code]["attended"] += attended
        per_subject[code]["held"] += sessions

    subject_stats = []
    for code, vals in per_subject.items():
        pct = (vals["attended"] / vals["held"] * 100) if vals["held"] > 0 else 0.0
        subject_stats.append({"subject_code": code, "attended": vals["attended"], "held": vals["held"], "percentage": round(pct, 2)})

    overall_pct = (total_attended / total_held * 100) if total_held > 0 else 0.0
    # include threshold
    s = db.student.find_one({"_id": db.ObjectId(student_id)}) if hasattr(db, 'ObjectId') else db.student.find_one({"id": student_id})
    threshold = float(s.get("min_threshold", 0.67)) * 100 if s else 67.0
    alert = overall_pct < threshold

    return {
        "period": period,
        "from": start,
        "to": today,
        "overall": {"attended": total_attended, "held": total_held, "percentage": round(overall_pct, 2), "threshold": threshold, "alert": alert},
        "subjects": subject_stats
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
