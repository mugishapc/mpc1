class Config:
    SECRET_KEY = 'd29c234ca310aa6990092d4b6cd4c4854585c51e1f73bf4de510adca03f5bc4e'
    
    # Use Neon Postgres instead of SQLite
    SQLALCHEMY_DATABASE_URI = "postgresql://neondb_owner:npg_OKbEBdk7xT0h@ep-purple-sound-ads9sirl-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # File uploads
    UPLOAD_FOLDER = 'static/uploads'
    PROFILE_PICTURE_FOLDER = 'static/uploads/profile_pictures'
