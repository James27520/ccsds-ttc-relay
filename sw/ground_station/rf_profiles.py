"""Business frequency bounds and historical examples; all units are explicit."""
from decimal import Decimal, InvalidOperation, localcontext

STEP_HZ = 1000
# 100 ksym/s, beta=.35: nominal half occupied bandwidth is 67.5 kHz.
# Reserve 100 kHz at each n256 band edge; this is not a spectral-mask test.
CENTER_LIMITS_HZ = {'sender': (1980100000, 2009900000),
                    'receiver': (2170100000, 2199900000)}
DEMO_RELAY_PAIRS = ((1989, 2179), (1990, 2180), (1982, 2172), (1999, 2189), (2007, 2197))
LEGACY_RELAY_PAIRS = ((900, 1000), (900, 1001), (901, 1000), (901, 1001))
CONTROL_RELAY_PAIRS = LEGACY_RELAY_PAIRS + DEMO_RELAY_PAIRS
DEMO_TX_CENTERS = tuple(f'{rx}.5' for rx, _ in DEMO_RELAY_PAIRS)
DEMO_RX_CENTERS = tuple(f'{tx}.5' for _, tx in DEMO_RELAY_PAIRS)
BUSINESS_TX_CENTERS = ('900.5', '901.5') + DEMO_TX_CENTERS
BUSINESS_RX_CENTERS = ('1000.5', '1001.5') + DEMO_RX_CENTERS
BUSINESS_TX_LO_HZ = (900000000, 901000000) + tuple(rx*1000000 for rx, _ in DEMO_RELAY_PAIRS)
BUSINESS_RX_LO_HZ = (1000750000, 1001750000) + tuple(tx*1000000+750000 for _, tx in DEMO_RELAY_PAIRS)
DEMO_HINT = '输入 1980.100–2009.900 MHz；输出 2170.100–2199.900 MHz；步进 0.001 MHz（1 kHz）'


def business_center_hz(role, value, *, legacy=False):
    if role not in CENTER_LIMITS_HZ:
        raise ValueError('业务角色须为 sender / receiver')
    if isinstance(value, bool) or len(str(value)) > 32:
        raise ValueError('请输入有效频率')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('请输入有效频率') from exc
    if not number.is_finite():
        raise ValueError('请输入有限频率值')
    low, high = CENTER_LIMITS_HZ[role]
    old = BUSINESS_TX_CENTERS if role == 'sender' else BUSINESS_RX_CENTERS
    legacy_match = legacy and number in map(Decimal, old)
    # Check range before arithmetic: an extreme exponent must produce the same
    # user-facing validation error, not Decimal overflow or an unbounded int.
    if not legacy_match and not Decimal(low)/1000000 <= number <= Decimal(high)/1000000:
        title = '业务输入' if role == 'sender' else '业务输出'
        raise ValueError(f'{title}范围 {low/1e6:.3f}–{high/1e6:.3f} MHz（已预留带宽边界）')
    with localcontext() as context:
        context.prec = 64
        hz = number * 1000000
    if hz != hz.to_integral_value() or hz % STEP_HZ:
        raise ValueError('频率步进为 0.001 MHz（1 kHz），不能自动取整')
    return int(hz)


def business_lo_allowed(role, value):
    """Validate a register value without widening other radio permissions."""
    if isinstance(value, bool):
        return False
    try:
        hz = int(value)
        if str(hz) != str(value):
            return False
        offset = 500000 if role == 'sender' else -250000
        center = Decimal(hz + offset) / 1000000
        business_center_hz(role, center, legacy=True)
    except (ValueError, TypeError, InvalidOperation):
        return False
    return True


def is_demo_request(request):
    if isinstance(request, dict) and request.get('encoding') == 'n256_khz_v1':
        from sw.tools.telecontrol_protocol import normalize_hz_request
        try:
            return normalize_hz_request(**request) == request
        except (ValueError, TypeError):
            return False
    return (type(request) is dict and type(request.get('rx_mhz')) is int and
            type(request.get('tx_mhz')) is int and
            (request['rx_mhz'], request['tx_mhz']) in DEMO_RELAY_PAIRS)
