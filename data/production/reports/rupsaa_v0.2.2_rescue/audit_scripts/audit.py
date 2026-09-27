import json,re,collections
C=json.load(open('corpus.json'))
BN=re.compile(r'[ঀ-৿]'); LAT=re.compile(r'[A-Za-z]')
def script(t):
    b,l=len(BN.findall(t)),len(LAT.findall(t))
    return 'bn' if b>l*0.5 and b>=l else ('latin' if b==0 else 'mix')
HINDI=r'\b(hai|nahi|nahin|kya|kyun|kyu|karo|karna|raha|rahi|bahut|mera|meri|tera|teri|accha|acha|bilkul|kuch|sab kuch|thoda|matlab hai|hain|aap|tum ho|kaise|kaisa|lekin|phir|jaldi|samajh|pata nahi|dekho na yaar)\b'
FILL_OPEN=r'^(fair|honestly|actually|hmm|haha|oh|ah|totally|valid|true|sheta valo|eta khub common)\b'
COUNSEL=r'(nijer modh|kokhon theke|ki mone hoy tomar|tumi ki mone koro|kemon lagche eta|emon kichu\?|ache emon kichu)'
def intra(t):  # a single word containing both scripts
    return re.findall(r'\S*[ঀ-৿][A-Za-z]\S*|\S*[A-Za-z][ঀ-৿]\S*',t)
def flags(lang,t):
    f=[]
    s=script(t)
    iw=intra(t)
    if iw: f.append(('HARD','intra-word mixed script',iw[:3]))
    if lang=='banglish':
        if s!='latin': f.append(('HARD','Bengali script in Banglish reply',None))
    if lang=='bn':
        if s=='latin': f.append(('HARD','bn-labelled reply written in Latin',None))
        elif s=='mix' or (BN.search(t) and len(re.findall(r'\b[a-z]{2,}\b',t))>=4 and re.search(r'\b(ar|kore|korte|eta|kichu|mane|na|hoy|ache|ki)\b',t)):
            f.append(('HARD','Banglish (Latin) sentences inside Bengali reply',None))
    if lang in('banglish','mixed') and s=='latin' and '।' in t: f.append(('HARD','Bengali danda in Latin text',None))
    if lang in('banglish','mixed') and re.search(HINDI,t.lower()): f.append(('HARD','Hindi leakage',re.findall(HINDI,t.lower())[:3]))
    if re.search(FILL_OPEN,t.strip().lower()): f.append(('SOFT','filler/template opener',t.split()[0]))
    if re.search(COUNSEL,t.lower()): f.append(('SOFT','counselling-question template',None))
    if t.strip().endswith('?'): f.append(('SOFT','ends with question',None))
    return f
rows=[]
for o in C:
    if o['copy']!=1: continue
    ms=o['messages']
    for i,m in enumerate(ms):
        if m['role']!='assistant': continue
        lang=o.get('language')
        rows.append({'id':o.get('id'),'src':o.get('source_type'),'lang':lang,'cat':o.get('category'),'user':ms[i-1]['content'],'reply':m['content'],'script':script(m['content']),'flags':flags(lang,m['content']),'weight':2 if o['source']!='rupsaa_v0.2_train' else 1})
json.dump(rows,open('turns.json','w'),ensure_ascii=False)
if __name__=='__main__':
    for lang in ('banglish','mixed','bn','en'):
        R=[r for r in rows if r['lang']==lang]
        c=collections.Counter(f[1] for r in R for f in r['flags'])
        print(lang,len(R),'scripts',collections.Counter(r['script'] for r in R))
        for k,v in c.most_common(): print('   ',k,v)
