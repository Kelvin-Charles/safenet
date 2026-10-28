"""Snippe's fee is paid by the guest on top of the package price, so the business gets the full price
(ClickPesa already charges its fee to the payer)."""
import os, sys
from decimal import Decimal
os.environ.update(DB_PASSWORD='x', SECRET_KEY='k' * 40, PAYMENT_PROVIDER='snippe', SNIPPE_API_KEY='snp_platform',
                  CLICKPESA_CLIENT_ID='cp', CLICKPESA_API_KEY='cpk', PLATFORM_FEE_PERCENT='3', PAYMENT_NETWORKS='airtel')
sys.path.insert(0, os.getcwd())
import config; config.Config.SQLALCHEMY_DATABASE_URI = 'sqlite://'
import clickpesa, snippe
sent = []
snippe.create_payment = lambda amount, phone, ref, creds, webhook_url=None, customer=None: sent.append(('snippe', amount, customer)) or {'reference': 'r-' + ref, 'status': 'pending'}
snippe.get_payment = lambda ref, creds: {'status': 'completed', 'amount': {'value': 1026, 'currency': 'TZS'}}
clickpesa.preview_ussd_push = lambda a, p, r, c=None: ['AIRTEL-MONEY']
clickpesa.initiate_ussd_push = lambda a, p, r, c=None: sent.append(('clickpesa', a)) or {'id': 'TX', 'status': 'PROCESSING'}
import app as appmod
appmod.send_sms_async = lambda *a, **k: None
from app import app, db, _start_purchase, _refresh_payment, _customer_fee
import migrations, payments as paylib
from models import Tenant, Package, PlatformSetting
from tenancy import tenant_sites
app.config.update(TESTING=True)
with app.app_context():
    db.create_all(); migrations.run()
    t = Tenant(name='Cafe', slug='cafe', status='active'); db.session.add(t); db.session.flush()
    pkg = Package(tenant_id=t.id, name='1 Day', price=Decimal(1000), validity_minutes=1440); db.session.add(pkg); db.session.commit()
    site = tenant_sites(t.id)[0].id

    # the fee: whole shillings, rounded up, so what's left after Snippe's 2.5 % is at least the price
    snp = appmod._tenant_account(t); assert snp.provider == 'snippe'
    assert _customer_fee(snp, Decimal(1000)) == 26 and _customer_fee(snp, Decimal(500)) == 13
    for price in (500, 700, 1000, 2500, 30000):
        charged = price + _customer_fee(snp, Decimal(price))
        assert charged * Decimal('0.975') >= price, price

    # a Snippe sale: the guest is asked for 1,026; the sale, the SafeNet Pay fee and the business's share stay on 1,000
    p, error, _ = _start_purchase(t, site, pkg, '0684000111', 'airtel')
    assert not error and sent[-1][:2] == ('snippe', 1026)
    # Snippe's Customer column shows the site and the business
    assert (sent[-1][2]['firstname'], sent[-1][2]['lastname']) == (tenant_sites(t.id)[0].name, 'Cafe')
    assert (p.amount, p.customer_fee, p.charged, p.fee_amount, p.net_amount) == (1000, 26, 1026, 30, 970)
    p = _refresh_payment(p.reference, force=True)
    assert p.status == 'paid' and p.voucher.price == 1000          # 1,026 collected: not short

    # ClickPesa adds its own fee for the payer: nothing extra from SafeNet
    db.session.add(PlatformSetting(key='payment_provider', value='clickpesa')); db.session.commit()
    cp = appmod._tenant_account(t); assert cp.provider == 'clickpesa' and _customer_fee(cp, Decimal(1000)) == 0
    p2, error, _ = _start_purchase(t, site, pkg, '0684000222', 'airtel')
    assert not error and sent[-1] == ('clickpesa', 1000) and p2.charged == 1000

    # switched off in Platform settings (0 %): guests pay the price, Snippe's fee comes off the sale
    config.Config.SNIPPE_FEE_PERCENT = 0
    assert _customer_fee(snp, Decimal(1000)) == 0
print('CUSTOMER FEE OK')
