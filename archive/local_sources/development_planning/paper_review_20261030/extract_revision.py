from pathlib import Path
from zipfile import ZipFile
from lxml import etree as E
import json

src = Path(r'C:\Users\Lu\Downloads\比赛技术报告_修订版_20261030.docx')
out = Path(__file__).parent / 'revision'
out.mkdir(exist_ok=True)
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
with ZipFile(src) as z:
    doc = E.fromstring(z.read('word/document.xml'))
    rel = E.fromstring(z.read('word/_rels/document.xml.rels'))
    rels = {x.get('Id'): x.get('Target') for x in rel}
    blocks = []
    for i, el in enumerate(doc.find('w:body', ns)):
        if E.QName(el).localname == 'tbl':
            s = '\n'.join(' | '.join(''.join(c.itertext()) if False else ''.join(c.xpath('.//w:t/text()', namespaces=ns)) for c in row.findall('w:tc', ns)) for row in el.findall('w:tr', ns))
            s = 'TABLE\n' + s
        else:
            s = ''.join(el.xpath('.//w:t/text() | .//m:t/text()', namespaces={**ns, 'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}))
        imgs = [rels.get(b.get('{%s}embed' % ns['r'])) for b in el.findall('.//a:blip', ns)]
        if s or imgs:
            blocks.append(f'[{i}] {s}' + (f'\nIMAGES {imgs}' if imgs else ''))
    (out/'paper_text.txt').write_text('\n\n'.join(blocks), encoding='utf-8')
    media=[]
    for name in z.namelist():
        if name.startswith('word/media/'):
            target=out/Path(name).name
            target.write_bytes(z.read(name))
            media.append(target.name)
    info={'blocks':len(blocks),'media':media,'insertions':len(doc.findall('.//w:ins',ns)), 'deletions':len(doc.findall('.//w:del',ns)), 'comments_file':'word/comments.xml' in z.namelist()}
    if 'docProps/app.xml' in z.namelist():
        info['app_properties']=z.read('docProps/app.xml').decode()
    (out/'metadata.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(info,ensure_ascii=False))
