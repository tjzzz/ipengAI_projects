"""
Routes package for AI Humanizer application.
"""

from .main import main_bp
from .auth import auth_bp
from .analysis import analysis_bp
from .rewrite import rewrite_bp
from .payment import payment_bp
from .download import download_bp
from .orders import orders_bp
from .activation import activation_bp

__all__ = ['main_bp', 'auth_bp', 'analysis_bp', 'rewrite_bp',
           'payment_bp', 'download_bp', 'orders_bp', 'activation_bp']