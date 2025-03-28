from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, create_engine
from sqlalchemy.orm import relationship, sessionmaker, declarative_base
from datetime import datetime
import uuid
import os

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    reports = relationship("Report", back_populates="user")
    
    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, username={self.username})>"

class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True)
    report_id = Column(String(10), unique=True, nullable=False)
    report_type = Column(String(50), nullable=False)
    details = Column(Text, nullable=False)
    urgency = Column(String(50), nullable=False)
    photo_file_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    user_id = Column(Integer, ForeignKey('users.id'))
    user = relationship("User", back_populates="reports")
    
    def __repr__(self):
        return f"<Report(report_id={self.report_id}, type={self.report_type})>"
    
    @staticmethod
    def generate_report_id():
        return str(uuid.uuid4())[:8].upper()
