from collections import OrderedDict
from mcptoai_core.receipts import prune_receipts


def test_receipts_expire_and_bound_without_payload():
    items = OrderedDict((str(i), {'updated_at': 100, 'status': 'completed'}) for i in range(5))
    items['expired'] = {'updated_at': -100}
    assert prune_receipts(items, 100, ttl=10, maximum=3)
    assert list(items) == ['2', '3', '4']


def test_receipt_future_timestamp_legacy_behavior():
    items = OrderedDict([('future', {'updated_at': 1000}), ('bad', {'updated_at': 'x'})])
    assert prune_receipts(items, 100, ttl=10, maximum=10)
    assert list(items) == ['future']
