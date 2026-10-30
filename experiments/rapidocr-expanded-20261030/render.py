import json
from pathlib import Path
import pymupdf
from PIL import Image,ImageDraw
root=Path('/lab')
out=root/'outputs/previews'
out.mkdir(exist_ok=True)
manifest=json.loads((root/'manifest.json').read_text())
for item in manifest:
    with pymupdf.open(item['path']) as doc:
        p=doc[item['page']-1]
        p.get_pixmap(dpi=120,alpha=False).save(out/f"{item['id']}.png")
        (out/f"{item['id']}-native.txt").write_text(p.get_text('text',sort=True),encoding='utf8')
        blocks=p.get_text('blocks',sort=True)
        (out/f"{item['id']}-blocks.json").write_text(json.dumps(blocks,ensure_ascii=False,indent=2),encoding='utf8')
for start in range(0,len(manifest),6):
    sheet=Image.new('RGB',(1200,1600),'#dddddd')
    draw=ImageDraw.Draw(sheet)
    for j,item in enumerate(manifest[start:start+6]):
        im=Image.open(out/f"{item['id']}.png")
        im.thumbnail((390,750))
        x=(j%3)*400;y=(j//3)*800
        sheet.paste(im,(x,y+30));draw.text((x+10,y+8),item['id'],fill='black')
    sheet.save(out/f'contact-{start//6+1}.jpg')
print('Rendered',len(manifest),'pages before OCR')
