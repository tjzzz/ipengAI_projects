"""
Main page routes — index, orders page, health check, SEO.
"""

from flask import Blueprint, render_template, session, jsonify, make_response
from datetime import datetime, timezone

main_bp = Blueprint('main', __name__)

SITE_URL = 'https://ipengai.cn'


@main_bp.route('/robots.txt')
def robots_txt():
    """Allow all crawlers, point to sitemap."""
    resp = make_response(f"""User-agent: *
Allow: /
Sitemap: {SITE_URL}/sitemap.xml
""")
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp


@main_bp.route('/sitemap.xml')
def sitemap_xml():
    """Simple sitemap listing all public pages."""
    pages = [
        {'loc': SITE_URL + '/', 'priority': '1.0'},
        {'loc': SITE_URL + '/orders', 'priority': '0.3'},
    ]
    urls = '\n'.join(
        f"""  <url>\n    <loc>{p['loc']}</loc>\n    <changefreq>weekly</changefreq>\n    <priority>{p['priority']}</priority>\n  </url>"""
        for p in pages
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{urls}
</urlset>"""
    resp = make_response(xml)
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp


@main_bp.route('/')
def index():
    """Landing page."""
    return render_template('index.html')


@main_bp.route('/orders')
def orders_page():
    """Order history page — requires login."""
    user_id = session.get('user_id')
    if not user_id:
        return render_template('orders.html', needs_login=True)
    return render_template('orders.html', needs_login=False)


@main_bp.route('/api/health')
def api_health():
    """Health check endpoint for monitoring and load balancers."""
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})