# init_db.py - Run this to initialize your database
import os
from app import app, db

with app.app_context():
    db.drop_all()
    db.create_all()
    print("Database tables created successfully!")