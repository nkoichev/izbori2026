"""Генерира data/*.json за сайта от CSV-тата с резултатите (results.cik.bg, протоколи на СИК).

    python tools/build_data.py [папка с CSV] [sections файл от парламентарните избори за координати]

По подразбиране чете C:\\veasbg\\izbori\\veasbg_pvr2026 (I тур). За II тур: втора папка → --round.
"""
import argparse
import json
import os
import re

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ap = argparse.ArgumentParser()
ap.add_argument('src', nargs='?', default=r'C:\veasbg\izbori\veasbg_pvr2026')
ap.add_argument('--coords', default=r'C:\veasbg\izbori\Актуализирана база данни\sections_19.04.2026.txt')
ap.add_argument('--round', default='1', help='1 или 2 — записва data/round<N>.json')
args = ap.parse_args()

dt = {'region_id': str, 'sik': str}
cand = pd.read_csv(os.path.join(args.src, 'candidates.csv'))
cand = cand[cand['column'].str.match(r'c\d+')]
ccols = list(cand['column'])
labels = {}
for _, r in cand.iterrows():
    pair = [' '.join([w.split()[0], w.split()[-1]]) for w in r['candidates'].split(' и ')]
    labels[r['column']] = ' / '.join(pair)
c_gyu = next(c for c, l in labels.items() if 'ГЮРОВ' in l.upper())
c_iot = next(c for c, l in labels.items() if 'ЙОТОВА' in l.upper())

reg = pd.read_csv(os.path.join(args.src, 'regions.csv'), dtype=dt)
mun = pd.read_csv(os.path.join(args.src, 'municipalities.csv'), dtype=dt)
stl = pd.read_csv(os.path.join(args.src, 'settlements.csv'), dtype=dt)
sec = pd.read_csv(os.path.join(args.src, 'sections.csv'), dtype=dt)

date = None
readme = os.path.join(args.src, 'README.txt')
if os.path.exists(readme):
    with open(readme, encoding='utf-8') as f:
        m = re.search(r'\d{2}\.\d{2}\.\d{4}', f.read())
    date = m.group(0) if m else None


def rows(df, name_cols):
    out = []
    for _, r in df.iterrows():
        out.append({**{k: r[v] for k, v in name_cols.items()},
                    'voters': int(r['voters']), 'voted': int(r['voted']), 'valid': int(r['valid_total']),
                    'g': int(r[c_gyu]), 'y': int(r[c_iot])})
    return out


# Градове: само „гр.“, без чужбина; София (МИР 23/24/25) се сумира по населено място
cs = stl[(stl['region_id'] != '32') & stl['settlement'].str.startswith('гр.')].copy()
cs['key'] = cs['settlement'] + '|' + cs['municipality'].where(cs['settlement'] != 'гр.София', '')
cities = cs.groupby('key', as_index=False).agg(
    {**{c: 'sum' for c in ['voters', 'voted', 'valid_total', c_gyu, c_iot]}, 'settlement': 'first', 'region': 'first'})
cities['name'] = cities['settlement'].str.replace('гр.', 'гр. ', regex=False)

muni = mun[mun['region_id'] != '32'].copy()
muni['name'] = 'общ. ' + muni['municipality'] + ' (' + muni['region'] + ')'
# Столична община е разделена от ЦИК между МИР 23/24/25 → един ред
muni.loc[muni['region_id'].isin(['23', '24', '25']), ['name', 'region']] = ['Столична община', 'София град']
muni = muni.groupby(['name', 'region'], as_index=False)[['voters', 'voted', 'valid_total', c_gyu, c_iot]].sum()

# Секции в гр. Стара Загора + координати (същите номера на секции като в парламентарните избори)
coords = {}
with open(args.coords, encoding='utf-8') as f:
    for ln in f:
        p = ln.strip().split(';')
        if len(p) >= 8 and p[0].startswith('2731'):
            try:
                coords[p[0]] = (round(float(p[7]), 6), round(float(p[6]), 6))
            except ValueError:
                pass
sz = sec[(sec['municipality'] == 'Стара Загора') & (sec['settlement'] == 'гр.Стара Загора')].copy()
sz['valid_total'] = sz['valid_for_candidates'] + sz['none']
sz_rows = []
for _, r in sz.iterrows():
    if r['sik'] not in coords:
        continue
    sz_rows.append({'sik': r['sik'], 'addr': r['address'], 'lat': coords[r['sik']][0], 'lon': coords[r['sik']][1],
                    'voters': int(r['voters_list'] + r['voters_added']), 'voted': int(r['voted']),
                    'valid': int(r['valid_total']), 'none': int(r['none']),
                    'v': [int(r[c]) for c in ccols]})

data = {
    'date': date,
    'candidates': [{'col': c, 'label': labels[c], 'nominated_by': n} for c, n in zip(ccols, cand['nominated_by'])],
    'gyu': ccols.index(c_gyu), 'iot': ccols.index(c_iot),
    'national': {'voters': int(reg['voters'].sum()), 'voted': int(reg['voted'].sum()),
                 'valid': int(reg['valid_total'].sum()), 'none': int(reg['none'].sum()),
                 'sections': int(reg['sections'].sum()),
                 'v': [int(reg[c].sum()) for c in ccols]},
    'regions': [{**x, 'id': rid, 'v': [int(v) for v in vv]} for x, rid, vv in
                zip(rows(reg, {'name': 'region'}), reg['region_id'], reg[ccols].values)],
    'cities': rows(cities, {'name': 'name', 'region': 'region'}),
    'municipalities': rows(muni, {'name': 'name', 'region': 'region'}),
    'sz_sections': sz_rows,
}
os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
out = os.path.join(ROOT, 'data', f'round{args.round}.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
print(out, os.path.getsize(out), 'bytes;', len(data['regions']), 'МИР,', len(data['cities']), 'града,',
      len(data['municipalities']), 'общини,', len(sz_rows), 'секции СЗ')
