import smtplib
import json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database import get_setting, get_connection


def get_email_config():
    return {
        'enabled': get_setting('notifications_enabled', '0') == '1',
        'smtp_host': get_setting('smtp_host', 'smtp.gmail.com'),
        'smtp_port': int(get_setting('smtp_port', '587') or '587'),
        'smtp_user': get_setting('smtp_user', ''),
        'smtp_password': get_setting('smtp_password', ''),
        'email_from': get_setting('email_from', '') or get_setting('smtp_user', ''),
        'email_to': get_setting('email_to', ''),
    }


def _send_raw(subject, html):
    cfg = get_email_config()
    if not cfg['smtp_user'] or not cfg['smtp_password'] or not cfg['email_to']:
        return False, 'Email not configured'
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = cfg['email_from']
        msg['To'] = cfg['email_to']
        msg.attach(MIMEText(html, 'html', 'utf-8'))
        with smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'], timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg['smtp_user'], cfg['smtp_password'])
            server.send_message(msg)
        return True, ''
    except Exception as e:
        return False, str(e)


def _fmt_price(value):
    try:
        value = int(value or 0)
    except (TypeError, ValueError):
        value = 0
    if value == 0:
        return 'Price on request'
    return f'{value:,}'.replace(',', ' ')


def _score_colors(score):
    if score >= 80:
        return '#4ade80', '#000'
    if score >= 60:
        return '#fbbf24', '#000'
    return '#f87171', '#000'


def _build_listing_block(listing):
    score = int(listing.get('score') or 0)
    score_bg, score_text = _score_colors(score)
    price = int(listing.get('price') or 0)
    price_formatted = _fmt_price(price)
    if price == 0:
        price_suffix = ''
    elif listing.get('listing_type') == 'rent':
        price_suffix = ' CZK/mo'
    elif listing.get('listing_type') == 'buy':
        price_suffix = ' CZK'
    else:
        price_suffix = ''

    title = listing.get('title') or 'Listing'
    locality = listing.get('locality') or ''
    url = listing.get('url') or '#'
    image_url = listing.get('image_url') or ''

    if image_url:
        image_cell = (
            '<div style="display:table-cell;width:120px;vertical-align:top;padding-right:16px">'
            f'<img src="{image_url}" width="120" height="80" '
            'style="object-fit:cover;border-radius:6px;display:block;background:#ddd" '
            'onerror="this.style.display=\'none\'"></div>'
        )
    else:
        image_cell = ''

    return (
        '<div style="border-bottom:1px solid #e5e5e5;padding:16px;display:table;width:100%;box-sizing:border-box">'
        f'{image_cell}'
        '<div style="display:table-cell;vertical-align:top">'
        f'<div style="font-weight:600;font-size:15px;margin-bottom:3px;color:#111">{title}</div>'
        f'<div style="color:#666;font-size:13px;margin-bottom:8px">{locality}</div>'
        '<div style="font-size:20px;font-weight:700;color:#111;margin-bottom:8px">'
        f'{price_formatted}{price_suffix}</div>'
        '<div>'
        f'<span style="background:{score_bg};color:{score_text};padding:3px 10px;'
        f'border-radius:999px;font-size:12px;font-weight:700">{score}/100</span>'
        f'<a href="{url}" style="margin-left:10px;color:#3b82f6;font-size:13px;'
        'text-decoration:none">View listing &rarr;</a>'
        '</div>'
        '</div>'
        '</div>'
    )


def _email_wrapper(title_line, subtitle, body_blocks):
    return (
        '<!DOCTYPE html>\n<html>\n'
        '<body style="margin:0;padding:20px;background:#f0f0f0;font-family:system-ui,-apple-system,sans-serif">'
        '<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,0.08)">'
        '<div style="background:#0d0d0d;padding:20px 24px">'
        '<div style="font-size:20px;font-weight:700;color:#fff;letter-spacing:-0.5px">FlatRadar</div>'
        f'<div style="font-size:13px;color:#888;margin-top:3px">{title_line}</div>'
        '</div>'
        '<div style="padding:0">'
        f'{body_blocks}'
        '</div>'
        '<div style="padding:16px 24px;background:#f9f9f9;border-top:1px solid #eee;'
        'font-size:12px;color:#999;text-align:center">'
        f'{subtitle} &middot; FlatRadar running locally on your machine'
        '</div>'
        '</div>'
        '</body>\n</html>'
    )


def send_new_matches(listings, profile):
    count = len(listings)
    plural_es = 'es' if count != 1 else ''
    plural_s = 's' if count != 1 else ''
    subject = f"FlatRadar: {len(listings)} new listing{'s' if len(listings) != 1 else ''} match{'es' if len(listings) == 1 else ''} your profile \"{profile['name']}\""
    title_line = f'{count} new listing{plural_s} match your profile "{profile["name"]}"'
    subtitle = datetime.now().strftime('%b %-d, %Y')

    ordered = sorted(listings, key=lambda x: int(x.get('score') or 0), reverse=True)
    shown = ordered[:10]
    body_blocks = ''.join(_build_listing_block(l) for l in shown)
    if len(ordered) > 10:
        subtitle = f'+ {len(ordered) - 10} more · {subtitle}'

    html = _email_wrapper(title_line, subtitle, body_blocks)
    return _send_raw(subject, html)


def send_price_drop(listing, old_price, new_price):
    locality = listing.get('locality') or listing.get('title') or 'Saved listing'
    subject = f'FlatRadar: Price drop – {locality}'
    title_line = 'Price drop on a saved listing'
    subtitle = datetime.now().strftime('%b %-d, %Y')

    old_fmt = f'{int(old_price or 0):,}'
    new_fmt = f'{int(new_price or 0):,}'
    diff = abs(int(old_price or 0) - int(new_price or 0))
    price_line = (
        '<div style="padding:12px 24px;background:#f0fdf4;border-bottom:1px solid #bbf7d0;'
        'font-size:14px;color:#166534">'
        f'&darr; Price dropped from <strong>{old_fmt} CZK</strong> '
        f'to <strong>{new_fmt} CZK</strong> '
        f'({diff:,} CZK less)'
        '</div>'
    )
    body_blocks = price_line + _build_listing_block(listing)
    html = _email_wrapper(title_line, subtitle, body_blocks)
    return _send_raw(subject, html)


def test_email():
    subject = 'FlatRadar: Test email'
    body_blocks = (
        '<div style="padding:24px;font-size:15px;color:#111">'
        'Your FlatRadar email notifications are working.'
        '</div>'
    )
    subtitle = datetime.now().strftime('%b %-d, %Y')
    html = _email_wrapper('Test email', subtitle, body_blocks)
    return _send_raw(subject, html)
