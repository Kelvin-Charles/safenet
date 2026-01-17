import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Application configuration"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    FLASK_ENV = os.getenv('FLASK_ENV', 'production')
    
    # Database
    DB_HOST = os.getenv('DB_HOST', 'db')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_NAME = os.getenv('DB_NAME', 'radius')
    DB_USER = os.getenv('DB_USER', 'radius')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'radiuspassword')
    
    SQLALCHEMY_DATABASE_URI = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # FreeRADIUS
    RADIUS_SECRET = os.getenv('RADIUS_SECRET', 'testing123')
    
    # Admin
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@safenet.local')
    
    # Pagination
    ITEMS_PER_PAGE = 25
    
    # Supported vendors
    SUPPORTED_VENDORS = [
        ('standard', 'Standard RADIUS'),
        ('cisco', 'Cisco'),
        ('mikrotik', 'MikroTik'),
        ('tplink', 'TP-Link'),
        ('dlink', 'D-Link'),
        ('ubiquiti', 'UniFi / Ubiquiti'),
        ('aruba', 'Aruba'),
    ]
    
    # Common RADIUS attributes
    COMMON_ATTRIBUTES = [
        'Session-Timeout',
        'Idle-Timeout',
        'Acct-Interim-Interval',
        'Framed-IP-Address',
        'Framed-IP-Netmask',
        'Framed-Route',
        'Filter-Id',
        'Reply-Message',
    ]
    
    # Vendor-specific attributes
    VENDOR_ATTRIBUTES = {
        'cisco': [
            'Cisco-AVPair',
            'Cisco-Account-Info',
            'Cisco-Service-Info',
        ],
        'mikrotik': [
            'Mikrotik-Rate-Limit',
            'Mikrotik-Recv-Limit',
            'Mikrotik-Xmit-Limit',
            'Mikrotik-Group',
            'Mikrotik-Address-List',
        ],
        'ubiquiti': [
            'Ubiquiti-Data-Limit-Down',
            'Ubiquiti-Data-Limit-Up',
            'Ubiquiti-VLAN-ID',
        ],
        'aruba': [
            'Aruba-User-Role',
            'Aruba-Admin-Role',
        ],
    }


