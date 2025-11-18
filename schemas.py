"""
Database Schemas for Attendance App

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
"""
from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, EmailStr
from datetime import date, datetime

# Users
class Student(BaseModel):
    name: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password_hash: Optional[str] = None
    role: Literal["student", "admin", "teacher"] = "student"
    semester: Optional[int] = Field(None, ge=1, le=8)
    subjects: List[str] = []
    min_threshold: float = Field(0.67, ge=0, le=1)

# Master data managed by admin
class Subject(BaseModel):
    code: str
    name: str
    semester: int = Field(..., ge=1, le=8)

class SemesterSubjects(BaseModel):
    semester: int = Field(..., ge=1, le=8)
    subjects: List[Subject]

class AcademicCalendar(BaseModel):
    title: str
    date: date
    type: Literal["holiday", "event", "semester_start", "semester_end"] = "holiday"

class TeacherLeave(BaseModel):
    subject_code: str
    date: date
    reason: Optional[str] = None

class OTP(BaseModel):
    phone: str
    code: str
    expires_at: datetime

# Attendance
class AttendanceRecord(BaseModel):
    student_id: str
    subject_code: str
    date: date
    sessions_held: int = 1
    attended_count: int = 0
    status: Literal["attended", "not_attended", "teacher_leave", "holiday", "mixed"] = "mixed"

