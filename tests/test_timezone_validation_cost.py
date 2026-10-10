from app.services import schedule

def test_repeated_timezone_validation_scans_database_once(monkeypatch):
    calls=[]
    monkeypatch.setattr(schedule,'available_timezones',lambda: calls.append(True) or {'UTC','America/Denver'})
    if hasattr(schedule,'_canonical_timezones'):schedule._canonical_timezones.cache_clear()
    try:
        for _ in range(200):assert schedule.validate_timezone('UTC')=='UTC'
        assert len(calls)==1
    finally:
        if hasattr(schedule,'_canonical_timezones'):schedule._canonical_timezones.cache_clear()
