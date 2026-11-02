"""Ruijie Cloud allows one App ID 5,000 requests a day: SafeNet counts every request (all workers, in the database),
the background sync stops at its share and spaces itself out to last the day, and codes for guests who paid can
still use the rest; requests are spaced out in time too."""
import io, json, os, sys, time
from datetime import datetime
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40)
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
config.Config.RUIJIE_DAILY_LIMIT = 100
import ruijie
sent = []


class Reply(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *a): return False


def fake_urlopen(req, timeout=20):
    sent.append((time.time(), req.full_url))
    if 'access_token?' in req.full_url:
        return Reply(json.dumps({'code': 0, 'accessToken': 'tok'}).encode())
    return Reply(json.dumps({'code': 0, 'voucherData': {'code': 0, 'list': [], 'count': 0}}).encode())


ruijie.urllib.request.urlopen = fake_urlopen
import app as appmod
from app import app, db
import migrations
from models import RuijieUsage
with app.app_context():
    db.create_all(); migrations.run()
    assert ruijie.meter is appmod._ruijie_meter
    cloud = ruijie.Cloud('https://cloud-eu.ruijienetworks.com', 'openabc', 'secret')
    # every request is counted, the login too
    cloud.vouchers('9001')
    assert appmod._ruijie_used('openabc') == 2 and len(sent) == 2
    # requests from one process are spaced out
    assert sent[1][0] - sent[0][0] >= ruijie.MIN_GAP - 0.01
    ruijie.MIN_GAP = 0
    # the sync stops at its share (65 of 100)...
    with ruijie.lane('sync'):
        while True:
            try:
                cloud.vouchers('9001')
            except ruijie.RuijieError as e:
                stop = str(e)
                break
    assert appmod._ruijie_used('openabc') == 65 and "today's Ruijie Cloud requests" in stop and ruijie.busy(stop)
    assert db.session.query(RuijieUsage).one().sync_calls == 63
    assert appmod._ruijie_sync_gap('openabc', [1]) is None             # no more syncs today
    # ...pages can go on to 90, codes for guests who paid to 98
    for _ in range(25):
        cloud.vouchers('9001')
    try:
        cloud.vouchers('9001'); assert False, 'pages should stop at 90'
    except ruijie.RuijieError:
        pass
    with ruijie.lane('push'):
        for _ in range(8):
            cloud.vouchers('9001')
        try:
            cloud.vouchers('9001'); assert False, 'push should stop at 98'
        except ruijie.RuijieError:
            pass
    assert appmod._ruijie_used('openabc') == 98
    assert appmod._ruijie_used('other-app') == 0                        # each App ID has its own count
    # the sync spaces itself out: 3 sites costing 4 requests each with 3,250 left of a whole day
    config.Config.RUIJIE_DAILY_LIMIT = 5000
    db.session.query(RuijieUsage).delete(); db.session.commit()
    gap = appmod._ruijie_sync_gap('openabc', [1, 2, 3])
    now = datetime.utcnow()
    secs_left = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
    assert abs(gap - max(180, secs_left * 12 / 3250)) < 5, gap
    appmod._ruijie_sync_cost.update({1: 40})                            # a site with many codes costs more: syncs less often
    assert appmod._ruijie_sync_gap('openabc', [1, 2, 3]) > gap
print('RUIJIE BUDGET OK')
