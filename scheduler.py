import json
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import config
import notifier

_scheduler = None


def _listing_matches_profile(listing, profile):
    # Listing type
    if profile['listing_type'] != 'both':
        if listing['listing_type'] != profile['listing_type']:
            return False

    # Price ceiling
    if profile['price_max'] > 0 and listing['price'] > 0:
        if listing['price'] > profile['price_max']:
            return False

    # Size floor
    if profile['size_min'] > 0 and listing['size_m2'] > 0:
        if listing['size_m2'] < profile['size_min']:
            return False

    # Location
    districts = json.loads(profile.get('districts', '[]'))
    if districts:
        locality = (listing.get('locality') or '').lower()
        if not any(d.lower() in locality for d in districts):
            return False

    # Room types
    room_types = json.loads(profile.get('room_types', '[]'))
    if room_types and listing.get('room_type'):
        if listing['room_type'] not in room_types:
            return False

    return True


def _dedup_listings(listings):
    """
    Removes near-duplicate listings across sources.
    Keeps the first occurrence (sreality results come first, highest trust).
    Match key: listing_type + price bucketed to nearest 2000 CZK + size bucketed to nearest 5 m2.
    Only deduplicates if both price and size are non-zero.
    """
    seen_keys = set()
    result = []
    for listing in listings:
        price = listing.get('price', 0)
        size = listing.get('size_m2', 0)
        if price > 0 and size > 0:
            key = (
                listing.get('listing_type', ''),
                (price // 2000) * 2000,
                (size // 5) * 5,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
        result.append(listing)
    return result


_state = {
    'running': False,
    'last_run': None,
    'next_run': None,
    'last_run_count': 0,
}


def _log_notification(conn, listing_hash_id, profile_id, notification_type, success, error):
    conn.execute(
        'INSERT INTO notifications_log '
        '(listing_hash_id, profile_id, notification_type, channel, sent_at, success, error_message) '
        'VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)',
        (listing_hash_id, profile_id, notification_type, 'email', 1 if success else 0, error or None),
    )
    conn.commit()


def _notify_new_matches(conn):
    from database import get_setting
    interval = int(get_setting('scheduler_interval_minutes', '20'))
    # Use 1.5× the interval as the window to avoid missing listings on slow runs
    window_minutes = max(interval * 2, 60)

    profiles = conn.execute('SELECT * FROM profiles WHERE active = 1 AND notify_email = 1').fetchall()
    for profile in profiles:
        threshold = profile['score_threshold'] or 0
        rows = conn.execute(
            f"""
            SELECT l.*, COALESCE(ls.score, 0) AS score,
                   COALESCE(ls.score_breakdown, '{{}}') AS score_breakdown
            FROM listings l
            JOIN listing_scores ls
              ON ls.listing_hash_id = l.hash_id AND ls.profile_id = ?
            WHERE l.active = 1
              AND l.first_seen_at >= datetime('now', '-{window_minutes} minutes')
              AND ls.score >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM notifications_log nl
                  WHERE nl.listing_hash_id = l.hash_id
                    AND nl.profile_id = ?
                    AND nl.notification_type = 'new_match'
              )
            """,
            (profile['id'], threshold, profile['id']),
        ).fetchall()
        if not rows:
            continue

        eligible = [dict(l) for l in rows if _listing_matches_profile(dict(l), dict(profile))]
        if not eligible:
            continue

        ok, err = notifier.send_new_matches(eligible, dict(profile))
        for listing in eligible:
            _log_notification(conn, listing['hash_id'], profile['id'], 'new_match', ok, err)


def _notify_price_drops(conn):
    saved = conn.execute('SELECT listing_hash_id FROM saved_listings').fetchall()
    for row in saved:
        hash_id = row['listing_hash_id']
        history = conn.execute(
            'SELECT price FROM price_history WHERE listing_hash_id = ? '
            'ORDER BY recorded_at DESC, id DESC LIMIT 2',
            (hash_id,),
        ).fetchall()
        if len(history) < 2:
            continue
        new_price = history[0]['price']
        old_price = history[1]['price']
        if new_price is None or old_price is None or new_price >= old_price:
            continue

        already = conn.execute(
            """
            SELECT 1 FROM notifications_log
            WHERE listing_hash_id = ? AND notification_type = 'price_drop'
              AND sent_at >= datetime('now', '-7 days')
            LIMIT 1
            """,
            (hash_id,),
        ).fetchone()
        if already:
            continue

        listing_row = conn.execute('SELECT * FROM listings WHERE hash_id = ?', (hash_id,)).fetchone()
        if not listing_row:
            continue

        ok, err = notifier.send_price_drop(dict(listing_row), old_price, new_price)
        _log_notification(conn, hash_id, None, 'price_drop', ok, err)


def _should_notify() -> bool:
    from database import get_setting
    freq = get_setting('notification_frequency', 'daily')
    last = get_setting('last_notification_sent', '')
    if not last:
        return True
    from datetime import datetime, timezone
    try:
        last_dt = datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_dt
        if freq == 'daily':
            return delta.total_seconds() >= 86400
        elif freq == '3days':
            return delta.total_seconds() >= 259200
        elif freq == 'weekly':
            return delta.total_seconds() >= 604800
        return True
    except Exception:
        return True


def _send_notifications(conn):
    if not notifier.get_email_config()['enabled']:
        return
    if _should_notify():
        try:
            _notify_new_matches(conn)
        except Exception as e:
            print(f'new-match notification error: {e}')
        from database import set_setting
        set_setting('last_notification_sent', datetime.utcnow().isoformat())
    try:
        _notify_price_drops(conn)
    except Exception as e:
        print(f'price-drop notification error: {e}')


def _record_run(run):
    try:
        from database import get_connection as _gc
        _rc = _gc()
        _rc.execute('''
            INSERT INTO scraper_runs
            (started_at, completed_at, sreality_fetched, bezrealitky_fetched,
             expats_fetched, new_listings, deduplicated, profile_matches,
             errors, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', (
            run['started_at'],
            datetime.utcnow().isoformat(),
            run['sreality_fetched'],
            run['bezrealitky_fetched'],
            run['expats_fetched'],
            run['new_listings'],
            run['deduplicated'],
            json.dumps(run['profile_matches']),
            json.dumps(run['errors']),
            run['status'],
        ))
        _rc.commit()
        _rc.close()
    except Exception as e:
        print(f'[run_check] failed to record run: {e}')


def run_check():
    print('[run_check] started')
    _state['last_run'] = datetime.utcnow().isoformat()
    _state['last_run_count'] = 0

    run = {
        'started_at': datetime.utcnow().isoformat(),
        'sreality_fetched': 0,
        'bezrealitky_fetched': 0,
        'expats_fetched': 0,
        'new_listings': 0,
        'deduplicated': 0,
        'profile_matches': {},
        'errors': [],
        'status': 'ok',
    }

    try:
        print('[run_check] importing scrapers')
        from scrapers.sreality import run_all_sreality
        from scrapers.bezrealitky import run_all_bezrealitky
        from scrapers.expats import run_all_expats
        print('[run_check] scrapers imported')
    except Exception as e:
        import traceback
        print(f'[run_check] CRASH importing scrapers: {e}')
        traceback.print_exc()
        run['errors'].append(f'Scraper error: {str(e)}')
        run['status'] = 'error'
        _record_run(run)
        return

    try:
        print('[run_check] running scrapers')
        sreality_results = run_all_sreality()
        run['sreality_fetched'] = len(sreality_results)
        print(f'[run_check] sreality: {len(sreality_results)}')
        bezrealitky_results = run_all_bezrealitky()
        run['bezrealitky_fetched'] = len(bezrealitky_results)
        print(f'[run_check] bezrealitky: {len(bezrealitky_results)}')
        expats_results = run_all_expats()
        run['expats_fetched'] = len(expats_results)
        print(f'[run_check] expats: {len(expats_results)}')
    except Exception as e:
        import traceback
        print(f'[run_check] CRASH during scraping: {e}')
        traceback.print_exc()
        run['errors'].append(f'Scraper error: {str(e)}')
        run['status'] = 'error'
        _record_run(run)
        return

    try:
        print('[run_check] deduplicating and inserting')
        from database import get_connection

        combined = _dedup_listings(
            list(sreality_results) + list(bezrealitky_results) + list(expats_results)
        )
        total_before_dedup = (run['sreality_fetched'] +
                              run['bezrealitky_fetched'] +
                              run['expats_fetched'])
        run['deduplicated'] = total_before_dedup - len(combined)

        conn = get_connection()
        new_count = 0
        for item in combined:
            lat = item.get('lat')
            lng = item.get('lng')
            cur = conn.execute(
                'INSERT OR IGNORE INTO listings '
                '(hash_id, source, title, locality, price, price_currency, listing_type, '
                'property_type, size_m2, floor_number, image_url, url, lat, lng, raw_data, '
                'first_seen_at, last_seen_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)',
                (
                    item['hash_id'], item['source'], item['title'], item['locality'],
                    item['price'], item['price_currency'], item['listing_type'],
                    item['property_type'], item['size_m2'], item['floor_number'],
                    item['image_url'], item['url'], lat, lng, item['raw_data'],
                ),
            )
            if cur.rowcount == 1:
                new_count += 1
                conn.execute(
                    'INSERT INTO price_history (listing_hash_id, price) VALUES (?, ?)',
                    (item['hash_id'], item['price']),
                )
                # Download and cache image for new listings
                if item.get('image_url') and item.get('source') == 'sreality':
                    from scrapers.sreality import download_image, _session
                    local_url = download_image(
                        item['image_url'],
                        item['hash_id'],
                        session=_session
                    )
                    if local_url != item['image_url']:
                        conn.execute(
                            'UPDATE listings SET image_url = ? WHERE hash_id = ?',
                            (local_url, item['hash_id'])
                        )
            else:
                row = conn.execute(
                    'SELECT price FROM listings WHERE hash_id = ?', (item['hash_id'],)
                ).fetchone()
                current_price = row['price'] if row else None
                if current_price != item['price']:
                    conn.execute(
                        'INSERT INTO price_history (listing_hash_id, price) VALUES (?, ?)',
                        (item['hash_id'], item['price']),
                    )
                    conn.execute(
                        'UPDATE listings SET price = ?, last_seen_at = CURRENT_TIMESTAMP, '
                        'lat = COALESCE(lat, ?), lng = COALESCE(lng, ?) '
                        'WHERE hash_id = ?',
                        (item['price'], lat, lng, item['hash_id']),
                    )
                else:
                    conn.execute(
                        'UPDATE listings SET last_seen_at = CURRENT_TIMESTAMP, '
                        'lat = COALESCE(lat, ?), lng = COALESCE(lng, ?) WHERE hash_id = ?',
                        (lat, lng, item['hash_id']),
                    )

        conn.commit()
        run['new_listings'] = new_count
    except Exception as e:
        import traceback
        print(f'[run_check] CRASH during DB insert: {e}')
        traceback.print_exc()
        run['errors'].append(f'DB insert error: {str(e)}')
        run['status'] = 'error'
        _record_run(run)
        return

    try:
        print('[run_check] scoring')
        from scoring import score_all_listings
        score_all_listings(conn)
    except Exception as e:
        import traceback
        print(f'[run_check] CRASH during scoring: {e}')
        traceback.print_exc()
        run['errors'].append(f'Scoring error: {str(e)}')
        run['status'] = 'error'
        _record_run(run)
        return

    try:
        from database import get_connection as _get_conn
        _conn = _get_conn()
        profiles = _conn.execute(
            'SELECT id, name, score_threshold FROM profiles WHERE active=1'
        ).fetchall()
        for prof in profiles:
            count = _conn.execute(
                'SELECT COUNT(*) FROM listing_scores WHERE profile_id=? AND score>=?',
                (prof['id'], prof['score_threshold'])
            ).fetchone()[0]
            run['profile_matches'][prof['name']] = count
        _conn.close()
    except Exception as e:
        print(f'[run_check] failed to count profile matches: {e}')

    try:
        print('[run_check] notifications')
        try:
            _send_notifications(conn)
        except Exception as e:
            print(f'notification error: {e}')

        conn.close()

        _state['last_run'] = datetime.utcnow().isoformat()
        _state['last_run_count'] = len(combined)

        try:
            if _scheduler:
                job = _scheduler.get_job('check_listings')
                if job and job.next_run_time:
                    _state['next_run'] = job.next_run_time.isoformat()
        except Exception:
            pass
    except Exception as e:
        import traceback
        print(f'[run_check] CRASH during notifications: {e}')
        traceback.print_exc()
        run['errors'].append(f'Notification error: {str(e)}')
        run['status'] = 'error'
        _record_run(run)
        return

    _record_run(run)
    print('[run_check] completed')


def start_scheduler():
    global _scheduler
    from database import get_setting
    interval = int(get_setting('scheduler_interval_minutes', '20'))
    _scheduler = BackgroundScheduler()
    if interval > 0:
        _scheduler.add_job(run_check, 'interval', minutes=interval,
                           id='check_listings', replace_existing=True)
    _scheduler.start()
    _state['running'] = True
    _state['manual_only'] = (interval == 0)


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _state['running'] = False


def restart_scheduler():
    stop_scheduler()
    import time
    time.sleep(0.5)
    start_scheduler()


def trigger_now():
    def _safe_run():
        try:
            run_check()
        except Exception as e:
            import traceback
            print(f'[trigger_now] run_check crashed: {e}')
            traceback.print_exc()
    t = threading.Thread(target=_safe_run, daemon=True)
    t.start()


def get_status():
    from database import get_setting
    next_run = None
    if _scheduler and _scheduler.running:
        jobs = _scheduler.get_jobs()
        if jobs:
            nrt = jobs[0].next_run_time
            if nrt:
                next_run = nrt.isoformat()
    return {
        'running': _scheduler.running if _scheduler else False,
        'last_run': _state.get('last_run'),
        'next_run': next_run,
        'last_run_count': _state.get('last_run_count', 0),
        'manual_only': _state.get('manual_only', False),
        'interval_minutes': int(get_setting('scheduler_interval_minutes', '20')),
    }
