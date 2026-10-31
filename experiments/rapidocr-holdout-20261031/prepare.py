"""Freeze visually transcribed checks before the bounded unseen-page run."""
import hashlib
import json
from pathlib import Path

LAB = Path(__file__).resolve().parent
REPO = LAB.parent.parent
INPUTS = LAB / 'outputs/frozen/inputs'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)


def main():
    checks = {key: [] for key in ('review20', 'tech', 'discover', 'cyber')}

    def add(doc, key, expected, rect, kind='contains'):
        x0, y0, x1, y1 = rect
        checks[doc].append({'id': key, 'expected': expected, 'kind': kind,
                            'rect': [x0/1157, y0/1638, x1/1157, y1/1638]})

    for doc, high_y, rsi_y, macd_y in [('review20', 245, 1030, 1250),
                                      ('tech', 222, 1008, 1227)]:
        add(doc, 'high', '781.62', (490, high_y-24, 850, high_y+24))
        add(doc, 'rsi', 'RSI', (85, rsi_y-20, 190, rsi_y+20))
        add(doc, 'macd', 'MACD', (85, macd_y-20, 200, macd_y+20))
        for value, y in [('780', 270 if doc == 'review20' else 247),
                         ('750', 558 if doc == 'review20' else 514),
                         ('720', 848 if doc == 'review20' else 783),
                         ('-2', 1414 if doc == 'review20' else 1392)]:
            add(doc, 'axis-'+value, value, (985, y-17, 1065, y+17), 'exact')
    cards = [('HPQ', '33.45', 100, 598), ('MSI', '479.34', 345, 598),
             ('AAPL', '346.59', 590, 598), ('ADP', '305.88', 835, 598),
             ('ALLE', '179.97', 100, 945), ('ELV', '440.70', 345, 945),
             ('FAST', '52.22', 590, 945), ('HAS', '117.23', 835, 945),
             ('RBRK', '129.21', 100, 1278), ('RMD', '253.77', 345, 1278),
             ('SUNB', '78.89', 590, 1278), ('TW', '122.54', 835, 1278)]
    for ticker, price, x, y in cards:
        add('discover', ticker+'-ticker', ticker, (x, y-15, x+215, y+32))
        add('discover', ticker+'-price', price, (x, y-15, x+215, y+32))
    for key, expected, rect in [
        ('calls', 'Calls Bought (85)', (100, 178, 310, 218)),
        ('puts', 'Puts Bought (15)', (425, 178, 680, 218)),
        ('sold', 'Puts Sold (74)', (745, 178, 1030, 218)),
        ('first-call-strike', '362.5C', (160, 232, 230, 259)),
        ('first-call-date', '2026-11-20', (230, 232, 330, 259)),
        ('first-call-size', '1500', (325, 232, 377, 259)),
        ('first-call-value', '$671K', (375, 232, 430, 259)),
    ]:
        add('discover', key, expected, rect)
    for key, expected, rect in [
        ('nikesh', 'Nikesh Arora', (112, 211, 268, 239)),
        ('sam', 'Sam Altman', (112, 313, 268, 343)),
        ('greg', 'Greg Brockman', (112, 411, 268, 441)),
        ('logan', 'Logan Graham', (112, 499, 268, 529)),
        ('dane', 'Dane Knecht', (112, 835, 268, 865)),
        ('george', 'George Kurtz', (112, 934, 268, 964)),
        ('dan', 'Dan Lorenc', (112, 1025, 268, 1055)),
        ('anand', 'Anand Oswal', (112, 1122, 268, 1152)),
        ('percent', '25%', (272, 411, 438, 485)),
        ('months', '18 months', (272, 830, 438, 930)),
        ('heading', 'Executive Views and Implications', (100, 110, 1050, 149)),
    ]:
        add('cyber', key, expected, rect)
    save(INPUTS/'checks.json', checks)
    files = [REPO/'experiments/rapidocr-page-orientation-20261031/page_orientation.py',
             REPO/'experiments/rapidocr-page-orientation-20261031/regression.py',
             REPO/'experiments/rapidocr-smoke-20261019/config.py', LAB/'prepare.py',
             LAB/'holdout.py', LAB/'run.sh']
    files += sorted((REPO/'plugins/tools').glob('*.py'))
    save(INPUTS/'manifest.json', {
        'documents': json.loads((INPUTS/'selection.json').read_text()),
        'checks_sha256': digest(INPUTS/'checks.json'),
        'source_sha256': {str(p.relative_to(REPO)): digest(p) for p in files},
        'image': 'sha256:141ee6ffbc6d0ec0c025f9deccbf93ae832f6721ef90018de93312b6dfc36c1b',
        'scope': 'Four unseen real pages, no synthetic rotations; frozen model/algorithm/thresholds.',
        'major_incidents': ['worker crash or timeout', 'incorrect accepted page orientation',
                            'entire text image unreadable without review flag',
                            'material sign/decimal/magnitude errors in checked financial values',
                            'changed existing baseline output'],
        'unknown_policy': 'Not an automatic pass. Zero-degree candidate assessed only as manual reference.',
        'human_review': 'pending', 'production_ingestion': False,
    })


if __name__ == '__main__':
    main()
