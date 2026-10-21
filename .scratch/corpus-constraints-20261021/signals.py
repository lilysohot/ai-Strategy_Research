"""Adapt attributable constraints to the frozen retrieval experiment, no labels."""
import importlib.util
import re
from dataclasses import asdict
from pathlib import Path
from plugins.corpus.retrieval.constraints import AliasEvidence,ConstraintResolver

spec=importlib.util.spec_from_file_location('prior_body_signals',Path(__file__).resolve().parents[1]/'corpus-body-ranking-20261021/signals.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
body_text=prior.body_text

class Signals(prior.Signals):
    def __init__(self,corpus,authority,metadata):
        super().__init__(corpus,authority,metadata)
        aliases=[]
        for s in corpus:
            for company in self.company[s['source_id']]:
                aliases.append(AliasEvidence(company,company,f"source:{s['source_id']}:original_names"))
                for u in s['units']:
                    text=''.join(u['raw_text'].split())
                    for m in re.finditer(re.escape(company)+r'[（(](\d{6}(?:\.[A-Za-z]{2})?)[）)]',text):
                        code=m.group(1)
                        aliases.append(AliasEvidence(company,code,f"{s['build_id']}:{u['unit_id']}"))
                        if '.' in code:
                            aliases.append(AliasEvidence(company,code.split('.')[0],f"{s['build_id']}:{u['unit_id']}"))
            for u in s['units']:
                for m in re.finditer(r'资料来源[:：]\s*([\u4e00-\u9fff]{2,8})([A-Z][A-Za-z]{3,})',u['raw_text']):
                    aliases.append(AliasEvidence(m.group(1),m.group(2),f"{s['build_id']}:{u['unit_id']}"))
        self.aliases=tuple(dict.fromkeys(aliases))
        self.resolver=ConstraintResolver(self.aliases,tuple(self.issuer.values()))
        self.constraints={}

    def intent(self,query,lexemes):
        result=super().intent(query,lexemes)
        constraint=self.resolver.parse(query)
        result.update(entities=[e.identities[0] if len(e.identities)==1 else e.surface for e in constraint.entities],
                      issuers=list(constraint.issuers),constraints=asdict(constraint))
        # Caller-local key, not a case id. Only the actual query determines parsing.
        result['query']=query
        self.constraints[query]=constraint
        return result

    def feature(self,hit,intent):
        result=super().feature(hit,intent)
        companies=self.company.get(hit.source_id,set())
        match=self.resolver.match(self.constraints[intent['query']],self.body[hit.chunk_id],
            source_company=next(iter(companies)) if len(companies)==1 else None,
            source_issuer=self.issuer.get(hit.source_id))
        result.update(entity=match.entity_fraction,direct=list(match.direct_entities),inherited=list(match.inherited_entities),
            source_hint=int(match.source_status=='matched' and result['facet']>0 and match.entity_status in ('unconstrained','matched','partial')),
            constraints=asdict(match))
        return result

rerank_pool=prior.rerank_pool
final_rank=prior.final_rank

def guarded_year_order(hits,features,intent):
    """Only promote same-source body with no weaker topic/entity support."""
    rows=list(hits)
    for i,current in enumerate(rows):
        if current.kind!='body':continue
        old=features[current.chunk_id]
        candidates=[]
        for j,h in enumerate(rows[i+1:],i+1):
            f=features[h.chunk_id]
            if h.source_id!=current.source_id or h.kind!='body':continue
            if f['entity']<old['entity'] or f['facet']<old['facet']:continue
            if f['source_hint']<old['source_hint']:continue
            if f['constraints']['year_fraction']<=old['constraints']['year_fraction']:continue
            if intent['constraints']['fact_mode']=='actual' and f['constraints']['fact_status'] in ('forecast_cues','mixed'):continue
            candidates.append(j)
        if candidates:
            j=max(candidates,key=lambda j:features[rows[j].chunk_id]['constraints']['year_fraction'])
            rows[i],rows[j]=rows[j],rows[i]
    return tuple(rows)
