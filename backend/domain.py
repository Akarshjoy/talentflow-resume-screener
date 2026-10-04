"""Pure, testable extraction helpers and transparent decision-support scoring."""
import csv
import io
import re
import zipfile
from datetime import date
from xml.etree import ElementTree as ET

MAX_UPLOAD = 10 * 1024 * 1024
MAX_TEXT = 90000
VERSION = 'entity-overlap-v1'
ALIASES = {'aws': 'amazon web services', 'js': 'javascript', 'postgres': 'postgresql',
           'k8s': 'kubernetes', 'node.js': 'nodejs', 'ci/cd': 'continuous integration and delivery'}

class Invalid(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise Invalid(message)

def canonical(value):
    value = re.sub(r'\s+', ' ', str(value).strip().lower())
    return ALIASES.get(value, value)

def names(values):
    return sorted({canonical(v) for v in values if str(v).strip()})

def docx_text(data):
    require(data[:2] == b'PK', 'Not a DOCX archive')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        require(len(z.infolist()) < 2000, 'Too many DOCX archive entries')
        require(sum(x.file_size for x in z.infolist()) < 30 * 1024 * 1024, 'Expanded DOCX too large')
        require('word/document.xml' in z.namelist(), 'DOCX document.xml missing')
        require(not any('vbaProject' in n for n in z.namelist()), 'Macro-containing files are not accepted')
        raw = z.read('word/document.xml')
        require(b'<!DOCTYPE' not in raw and b'<!ENTITY' not in raw, 'XML declarations not allowed')
        root = ET.fromstring(raw)
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        text = '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t'))
                         for p in root.iter(ns+'p'))
        require(text.strip(), 'No text found; image-only DOCX must be converted to PDF')
        return bounded_text(text)

def bounded_text(text):
    text = text.replace('\x00', '').strip()
    require(20 <= len(text.encode('utf-8')) <= MAX_TEXT, 'Text must contain 20 to 90000 UTF-8 bytes')
    return text

def extract_email(text):
    found = sorted(set(re.findall(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)))
    return found[0] if len(found) == 1 else ''

def experience(text, today=None):
    """Conservative heuristic: explicit month/year ranges inside Experience section only."""
    today = today or date.today()
    active = False
    intervals = []
    evidence = []
    months = {m: i+1 for i, m in enumerate('jan feb mar apr may jun jul aug sep oct nov dec'.split())}
    pattern = re.compile(r'\b(Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+(20\d{2}|19\d{2})\s*[-–—]\s*(?:(Jan\w*|Feb\w*|Mar\w*|Apr\w*|May|Jun\w*|Jul\w*|Aug\w*|Sep\w*|Oct\w*|Nov\w*|Dec\w*)\s+(20\d{2}|19\d{2})|(Present|Current|Now))', re.I)
    for line in text.splitlines():
        heading = line.strip().lower().strip(':')
        if heading in ('experience', 'work experience', 'employment history', 'professional experience'):
            active = True
            continue
        if heading in ('education', 'projects', 'skills', 'certifications', 'interests'):
            active = False
        if not active:
            continue
        for m in pattern.finditer(line):
            start = int(m[2])*12 + months[m[1][:3].lower()]-1
            end = today.year*12+today.month if m[5] else int(m[4])*12+months[m[3][:3].lower()]
            if start < end <= today.year*12+today.month:
                intervals.append((start,end)); evidence.append(m[0])
    merged=[]
    for start,end in sorted(intervals):
        if merged and start <= merged[-1][1]: merged[-1][1]=max(end,merged[-1][1])
        else: merged.append([start,end])
    return (round(sum(b-a for a,b in merged)/12,2) if merged else None), evidence

def parsed(text, general, custom, model):
    def picks(entities, kind):
        return sorted({e['Text'].strip() for e in entities if e.get('Type') == kind and float(e.get('Score',0)) >= .8})
    skills=picks(custom,'SKILL'); titles=picks(custom,'JOB_TITLE')
    people=picks(general,'PERSON'); years,ranges=experience(text)
    flags=[]
    if len(people)!=1: flags.append('Candidate name needs review')
    if not extract_email(text): flags.append('A single contact email was not identified')
    if not skills: flags.append('No high-confidence skills extracted; do not interpret as no ability')
    if not titles: flags.append('No high-confidence job titles extracted')
    if years is None: flags.append('Experience dates could not be calculated')
    return {'name':people[0] if len(people)==1 else '', 'name_candidates':people[:20],
            'email':extract_email(text),'skills':skills[:150],'titles':titles[:50],
            'employers':[], 'organization_mentions':picks(general,'ORGANIZATION')[:80],
            'date_mentions':picks(general,'DATE')[:100], 'years_experience':years,
            'experience_evidence':ranges[:40], 'review_flags':flags,'model_arn':model,
            'confidence_threshold':.8, 'experience_method':'section-month-ranges-union-v1'}

def score(candidate, job):
    needed=set(names(job['required_skills'])); have=set(names(candidate['skills']))
    jt=set(names(job['acceptable_titles'])); ct=set(names(candidate['titles']))
    require(needed and jt, 'Recruiter must confirm nonempty job skills and titles')
    matched=sorted(needed & have); missing=sorted(needed-have)
    skills=50*len(matched)/len(needed)
    title=30 if jt & ct else 0
    target=float(job['minimum_years']); years=candidate.get('years_experience')
    exp=20 if target==0 else (None if years is None else 20*min(max(float(years),0)/target,1))
    total=None if exp is None else round(skills+title+exp,2)
    flags=list(candidate.get('review_flags',[]))
    # Every candidate remains a human decision; unknown extraction excludes automatic ranking.
    rankable=not flags and total is not None
    return {'score':total,'rankable':rankable,'recommended':rankable and total>=float(job['threshold']),
            'skills_points':round(skills,2),'title_points':title,'experience_points':exp,
            'matched_skills':matched,'missing_skills':missing,'review_flags':flags,
            'scoring_version':VERSION,'weights':{'skills':50,'titles':30,'experience':20},
            'job_version':job['version'],'model_arn':candidate['model_arn']}

def safe_csv(rows):
    out=io.StringIO();w=csv.writer(out)
    w.writerow(['candidate_id','name','email','score','decision','skills'])
    for row in rows:
        fields=[row['doc_id'],row.get('name',''),row.get('email',''),row.get('match',{}).get('score',''),row.get('decision','REVIEW'),'; '.join(row.get('skills',[]))]
        w.writerow([("'"+str(x)) if str(x).lstrip().startswith(('=','+','-','@','\t','\r')) else str(x) for x in fields])
    return out.getvalue()
