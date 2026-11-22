#!/usr/bin/env python3
"""Đóng gói hiệu ứng lp-* thành registry HyperFrames (registry.json + blocks/<ten>/registry-item.json).
Chạy: python3 make_lp_registry.py <thu-vien-hieu-ung/compositions> <thư mục registry đích>
Chỉ chép, không sửa tệp gốc. Hiệu ứng có chữ "chuyển cảnh" trong chú thích đầu tệp được gắn tag transition.
"""
import json, os, re, shutil, sys
src, out = sys.argv[1], sys.argv[2]
os.makedirs(os.path.join(out, 'blocks'), exist_ok=True)
items, rows = [], []
for f in sorted(os.listdir(src)):
    if not (f.startswith('lp-') and f.endswith('.html')): continue
    name = f[:-5]; text = open(os.path.join(src, f), encoding='utf-8').read()
    m = re.search(r'<!--\s*\n\s*(lp-[\w-]+)\s*·\s*([^\n]+)\n(.*?)-->', text, re.S)
    head = m.group(2).strip() if m else name
    desc = ' '.join(l.strip() for l in (m.group(3).splitlines() if m else []) if l.strip())[:400]
    title = re.sub(r'\s*\(.*$', '', head).strip().title()
    dur = re.search(r'data-composition-duration="([\d.]+)"', text)
    var = re.search(r"data-composition-variables='(\[.*?\])'", text, re.S)
    params = []
    if var:
        try:
            for v in json.loads(var.group(1)):
                params.append({'key': v['id'], 'label': v.get('label', v['id']), 'type': v.get('type', 'string'), 'default': v.get('default')})
        except Exception: pass
    low = (head + ' ' + desc).lower()
    tags = ['lp', 'newtecons']
    if 'chuyển cảnh' in low: tags.insert(0, 'transition')
    if 'chữ' in low or 'tiêu đề' in low: tags.append('text')
    d = os.path.join(out, 'blocks', name); os.makedirs(d, exist_ok=True)
    shutil.copy2(os.path.join(src, f), os.path.join(d, f))
    item = {'$schema': 'https://hyperframes.heygen.com/schema/registry-item.json', 'name': name, 'type': 'hyperframes:block',
            'title': title, 'description': desc or head, 'tags': tags, 'dimensions': {'width': 1920, 'height': 1080},
            'duration': float(dur.group(1)) if dur else None,
            'files': [{'path': f, 'target': f'compositions/{f}', 'type': 'hyperframes:composition'}], 'params': params}
    json.dump(item, open(os.path.join(d, 'registry-item.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    items.append({'name': name, 'type': 'hyperframes:block'})
    rows.append(f"| `{name}` | {title} | {item['duration']} s | {', '.join(tags)} |")
json.dump({'$schema': 'https://hyperframes.heygen.com/schema/registry.json', 'name': 'lp-newtecons', 'items': items},
          open(os.path.join(out, 'registry.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
open(os.path.join(out, 'DANH_SACH.md'), 'w', encoding='utf-8').write('| Khối | Tên | Dài | Tag |\n|---|---|---|---|\n' + '\n'.join(rows) + '\n')
print(len(items), 'khoi;', sum('transition' in r for r in rows), 'chuyen canh')
