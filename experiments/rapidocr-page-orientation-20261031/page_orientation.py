"""Experimental page-level orientation from image evidence only.

No PDF names, expected strings, test rotation, or ground truth enter this API.
Unknown orientation must not be promoted to an automatically corrected page.
"""
import math
import re


def inverse_point(point, clockwise):
    x, y = point
    return {0: (x,y), 90: (y,1-x), 180: (1-x,1-y), 270: (1-y,x)}[clockwise]


def axis_evidence(boxes):
    horizontal = vertical = 0.0
    eligible = 0
    for box in boxes:
        width = max(p[0] for p in box)-min(p[0] for p in box)
        height = max(p[1] for p in box)-min(p[1] for p in box)
        if min(width,height)<=0 or max(width,height)/min(width,height)<2.5:
            continue
        eligible += 1
        weight = min(max(width,height),300)
        if width>height: horizontal += weight
        else: vertical += weight
    total=horizontal+vertical
    fraction=max(horizontal,vertical)/total if total else 0
    return {'axis_clockwise':(0 if horizontal>=vertical else 90) if eligible>=3 and fraction>=.8 else None,
            'elongated_boxes':eligible,'majority_fraction':fraction,
            'horizontal_weight':horizontal,'vertical_weight':vertical}


def language_support(raw):
    anchors=[]
    for i,(text,score,box) in enumerate(zip(raw['lines'],raw['scores'],raw['boxes_normalized'])):
        compact=re.sub(r'\s+','',text)
        letters=sum(c.isalpha() for c in compact)
        width=max(p[0] for p in box)-min(p[0] for p in box)
        height=max(p[1] for p in box)-min(p[1] for p in box)
        # Aspect is measured in pixels, not normalized page fractions.
        pixel_aspect=(width*raw['render_pixels'][0])/max(1,height*raw['render_pixels'][1])
        if letters<6 or letters/max(1,len(compact))<.5 or score<.85 or pixel_aspect<2.5:
            continue
        center_y=sum(p[1] for p in box)/4
        anchors.append({'line':i,'text':text,'score':score,'letters':letters,
                        'band':min(5,int(center_y*6)),'weight':min(letters,40)*score**2})
    mass=sum(a['weight'] for a in anchors)
    return {'anchors':anchors,'anchor_count':len(anchors),'bands':len({a['band'] for a in anchors}),
            'mass':mass,'enough':len(anchors)>=3 and len({a['band'] for a in anchors})>=2}


def choose_direction(candidates):
    ordered=sorted(candidates,key=lambda c:c['support']['mass'],reverse=True)
    if len(ordered)!=2 or not all(math.isfinite(c['support']['mass']) for c in ordered):
        return {'status':'unknown','reason':'invalid_candidate_evidence','correction_clockwise':None}
    best,other=ordered
    margin=(best['support']['mass']-other['support']['mass'])/max(1,best['support']['mass'])
    if not best['support']['enough'] or margin<.25:
        return {'status':'unknown','reason':'weak_or_conflicting_page_direction',
                'correction_clockwise':None,'relative_margin':margin}
    return {'status':'oriented','reason':'multi_line_language_agreement',
            'correction_clockwise':best['correction_clockwise'],'relative_margin':margin}


def recognize(rgb,engine,clockwise):
    import numpy as np
    rotated=np.rot90(rgb,k=-(clockwise//90)).copy()
    height,width=rotated.shape[:2]
    result=engine(rotated[:,:,::-1].copy(),use_det=True,use_cls=False,use_rec=True)
    boxes=result.boxes.tolist() if result.boxes is not None else []
    raw={'lines':list(result.txts) if result.txts is not None else [],
         'scores':[float(s) for s in result.scores] if result.scores is not None else [],
         'boxes_normalized':[[[x/width,y/height] for x,y in box] for box in boxes],
         'render_pixels':[width,height]}
    return {'correction_clockwise':clockwise,'raw':raw,'support':language_support(raw)}


def orient_image(rgb,engine):
    detected=engine(rgb[:,:,::-1].copy(),use_det=True,use_cls=False,use_rec=False)
    boxes=detected.boxes.tolist() if detected.boxes is not None else []
    axis=axis_evidence(boxes)
    if axis['axis_clockwise'] is None:
        return {'status':'unknown','reason':'weak_or_mixed_text_axis','correction_clockwise':None,
                'axis':axis,'candidates':[],'needs_review':True}
    first=axis['axis_clockwise']
    candidates=[recognize(rgb,engine,first),recognize(rgb,engine,(first+180)%360)]
    decision=choose_direction(candidates)
    decision.update(axis=axis,candidates=candidates,needs_review=True)
    if decision['status']=='oriented':
        selected=next(c for c in candidates if c['correction_clockwise']==decision['correction_clockwise'])
        decision['raw']=selected['raw']
        # Even a strong orientation decision is not numeric/semantic approval.
        decision['boxes_normalized_input']=[[inverse_point(p,decision['correction_clockwise']) for p in box]
                                            for box in selected['raw']['boxes_normalized']]
    return decision
