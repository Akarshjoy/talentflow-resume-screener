import csv,importlib,io,json,os,sys,tarfile,zipfile
from datetime import date
from pathlib import Path
import pytest
import boto3
from moto import mock_aws
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from domain import experience,parsed,score,Invalid,docx_text,safe_csv,canonical

@pytest.fixture
def app(monkeypatch):
    for k,v in {'AWS_ACCESS_KEY_ID':'testing','AWS_SECRET_ACCESS_KEY':'testing','AWS_DEFAULT_REGION':'us-east-1','AWS_SESSION_TOKEN':'testing',
      'PORTAL':'https://portal.test','DATA':'talentflow-test-data','NLP_ROLE':'arn:aws:iam::123456789012:role/nlp','SENDER':'sender@example.test'}.items():monkeypatch.setenv(k,v)
    with mock_aws():
        db=boto3.client('dynamodb');template=json.loads((ROOT/'template.json').read_text())
        mapping={'JOBS':'Jobs','DOCS':'Documents','CANDIDATES':'Candidates','FAILED':'FailedJobs','CONFIG':'Config','AUDIT':'Audit','MAIL':'Mail'}
        for env,logical in mapping.items():
            monkeypatch.setenv(env,logical)
            props=template['Resources'][logical]['Properties']
            args={k:props[k] for k in ('AttributeDefinitions','KeySchema','BillingMode','GlobalSecondaryIndexes') if k in props}
            db.create_table(TableName=logical,**args)
        s3=boto3.client('s3');s3.create_bucket(Bucket='talentflow-test-data');s3.put_bucket_versioning(Bucket='talentflow-test-data',VersioningConfiguration={'Status':'Enabled'})
        q=boto3.client('sqs')
        for env in ['PARSE_QUEUE','SCORE_QUEUE']:monkeypatch.setenv(env,q.create_queue(QueueName=env)['QueueUrl'])
        sys.modules.pop('app',None);module=importlib.import_module('app');yield module

def call(app,path,method='GET',body=None,group='Recruiter'):
    return app.api({'httpMethod':method,'path':path,'body':json.dumps(body or {}),'requestContext':{'authorizer':{'claims':{'sub':'actor-1','cognito:groups':group}}}},None)
def job(app):
    j={'job_id':'J1','kind':'JOB','status':'READY','title':'Cloud Engineer','required_skills':['AWS','Python'],'acceptable_titles':['Cloud Engineer'],'minimum_years':3,'threshold':70,'version':1}
    app.put('JOBS',j);return j

def candidate():
    return {'name':'Alex','email':'alex@example.test','skills':['Amazon Web Services','Python'],'titles':['Cloud Engineer'],
            'years_experience':4,'review_flags':[],'model_arn':'model-test'}

def test_overlap_experience_not_double_counted():
    t='Work Experience\nJan 2020 - Dec 2022\nJan 2022 - Dec 2023\nEducation\nJan 2010 - Dec 2014'
    assert experience(t,date(2026,1,1))[0]==4

def test_unknown_experience_not_zero():assert experience('Education\nJan 2020 - Dec 2023')[0] is None

def test_future_date_not_counted():assert experience('Experience\nJan 2030 - Dec 2034',date(2026,1,1))[0] is None

def test_working_present_date():assert experience('Experience\nJan 2025 - Present',date(2025,12,3))[0]==1

def test_alias_normalizes_entities():assert canonical(' AWS ')==canonical('Amazon Web Services')

def test_score_weights_and_cap(app):
    result=score(candidate(),job(app));assert result['score']==100 and result['recommended']

def test_partial_match(app):
    c=candidate();c.update(skills=['Python'],titles=['Data Analyst'],years_experience=1.5)
    r=score(c,job(app));assert r['score']==35 and not r['recommended']

def test_uncertainty_excluded_from_rank(app):
    c=candidate();c['review_flags']=['Uncertain OCR'];assert not score(c,job(app))['rankable']

def test_unknown_experience_has_no_total(app):
    c=candidate();c['years_experience']=None;r=score(c,job(app));assert r['score'] is None and not r['recommended']

def test_empty_job_requirements_rejected(app):
    j=job(app);j['required_skills']=[]
    with pytest.raises(Invalid):score(candidate(),j)

def test_extraction_confidence_and_no_false_title():
    p=parsed('Alex alex@example.test\nSkills Python', [{'Type':'PERSON','Text':'Alex','Score':.99},{'Type':'TITLE','Text':'Some book','Score':.99}],
       [{'Type':'SKILL','Text':'Python','Score':.9},{'Type':'JOB_TITLE','Text':'Engineer','Score':.3}], 'custom-model')
    assert p['skills']==['Python'] and not p['titles'] and p['years_experience'] is None

def test_no_skills_not_fabricated():
    assert parsed('Unstructured document text',[],[],'model')['skills']==[]

def test_docx_archive_validation():
    with pytest.raises(Invalid):docx_text(b'not a word file')

def test_docx_actual_sample():
    t=docx_text((ROOT/'samples/resumes/graduate-software.docx').read_bytes());assert 'Python' in t and 'Sam Rivera' in t

def test_csv_formula_escaped():assert "'=HYPERLINK" in safe_csv([{'doc_id':'1','name':'=HYPERLINK("bad")'}])

def test_non_recruiter_denied(app):assert call(app,'/jobs',group='Employee')['statusCode']==400

def test_job_creation_and_confirm_freeze(app):
    r=call(app,'/jobs','POST',{'title':'Cloud Engineer'});assert r['statusCode']==201
    j=json.loads(r['body']);app.update('JOBS',{'job_id':j['job_id']},{'status':'JD_REVIEW'})
    body={'required_skills':['AWS'],'acceptable_titles':['Cloud Engineer'],'minimum_years':3,'threshold':70}
    assert call(app,f"/jobs/{j['job_id']}/confirm",'POST',body)['statusCode']==200
    assert call(app,f"/jobs/{j['job_id']}/confirm",'POST',body)['statusCode']==400

def test_upload_requires_real_model(app):
    j=job(app);r=call(app,'/jobs/J1/uploads','POST',{'filename':'cv.pdf','size':100,'kind':'resume'})
    assert r['statusCode']==400 and 'recognizer' in r['body']

def test_large_upload_rejected(app):
    job(app);r=call(app,'/jobs/J1/uploads','POST',{'filename':'cv.pdf','size':999999999,'kind':'resume'});assert r['statusCode']==400

def test_duplicate_scoring_preserves_decision(app):
    job(app);d={'doc_id':'D1','job_id':'J1','kind':'resume','state':'SCORE_QUEUED','parsed':candidate(),'evidence_key':'evidence/D1/entities.json'};app.put('DOCS',d)
    app.score_one({'doc_id':'D1'});app.update('CANDIDATES',{'doc_id':'D1'},{'decision':'SHORTLISTED'})
    app.score_one({'doc_id':'D1'});assert app.get('CANDIDATES',{'doc_id':'D1'})['decision']=='SHORTLISTED'

def test_stale_transition_cannot_reopen_complete(app):
    old={'doc_id':'D1','state':'VALIDATING','job_id':'J1'};app.put('DOCS',{**old,'state':'COMPLETE'})
    from botocore.exceptions import ClientError
    with pytest.raises(ClientError):app.state(old,'NLP_PENDING')
    assert app.get('DOCS',{'doc_id':'D1'})['state']=='COMPLETE'

def seed_candidate(app):
    j=job(app);c={**candidate(),'doc_id':'D1','job_id':'J1','decision':'REVIEW','revision':0,'match':score(candidate(),j)};app.put('CANDIDATES',c);return c

def test_decision_requires_human_review(app):
    seed_candidate(app);r=call(app,'/jobs/J1/candidates/D1/decision','POST',{'decision':'REJECTED','reason':'test'})
    assert r['statusCode']==400 and 'Review' in r['body']

def test_review_then_shortlist_one_outbox(app):
    seed_candidate(app)
    review={**candidate(),'note':'Checked dates and skill evidence in source'}
    assert call(app,'/jobs/J1/candidates/D1/review','POST',review)['statusCode']==200
    body={'decision':'SHORTLISTED','reason':'Relevant evidence','interview_details':'Monday 10:00 UTC; online. Reply to schedule.','confirm_send':True}
    assert call(app,'/jobs/J1/candidates/D1/decision','POST',body)['statusCode']==200
    assert call(app,'/jobs/J1/candidates/D1/decision','POST',body)['statusCode']==200
    assert len(app.query('MAIL','job_id','J1','ByJob'))==1
    assert app.get('CANDIDATES',{'doc_id':'D1'})['decision']=='SHORTLISTED'

def test_no_invitation_without_confirmation(app):
    c=seed_candidate(app);app.update('CANDIDATES',{'doc_id':'D1'},{'reviewed_by':'actor'})
    r=call(app,'/jobs/J1/candidates/D1/decision','POST',{'decision':'SHORTLISTED','reason':'Fit','interview_details':'Tomorrow at 10 AM'})
    assert r['statusCode']==400 and not app.get('MAIL',{'mail_id':'D1'})

def test_failed_jobs_persisted(app):
    d={'doc_id':'D1','job_id':'J1','kind':'resume','state':'VALIDATING','attempt':0};app.put('DOCS',d)
    app.failed(d,'PARSING','Invalid PDF');assert app.get('DOCS',{'doc_id':'D1'})['state']=='FAILED'
    assert len(app.query('FAILED','job_id','J1','ByJob'))==1

def test_partial_batch_retry_identifiers(app):
    def bad(body):raise Invalid('bad document')
    assert app.batch({'Records':[{'body':'{}','messageId':'m1'}]},bad)=={'batchItemFailures':[{'itemIdentifier':'m1'}]}

def test_custom_output_tar_parsing(app):
    b=io.BytesIO()
    with tarfile.open(fileobj=b,mode='w:gz') as t:
        data=json.dumps({'File':'document.txt','Entities':[{'Type':'SKILL','Text':'Python','Score':.99}]}).encode()
        info=tarfile.TarInfo('output');info.size=len(data);t.addfile(info,io.BytesIO(data))
    app.S3.put_object(Bucket=os.environ['DATA'],Key='nlp-output/result.tar.gz',Body=b.getvalue())
    entities,raw=app.custom_output('s3://'+os.environ['DATA']+'/nlp-output/result.tar.gz');assert entities[0]['Text']=='Python'

def test_custom_output_error_not_zero_score(app):
    b=io.BytesIO()
    with tarfile.open(fileobj=b,mode='w:gz') as t:
        data=json.dumps({'File':'doc.txt','ErrorCode':'INVALID_REQUEST','ErrorMessage':'bad'}).encode();info=tarfile.TarInfo('output');info.size=len(data);t.addfile(info,io.BytesIO(data))
    app.S3.put_object(Bucket=os.environ['DATA'],Key='bad.tar.gz',Body=b.getvalue())
    with pytest.raises(Invalid):app.custom_output('s3://'+os.environ['DATA']+'/bad.tar.gz')

def test_training_offsets_and_disjoint_documents():
    corpora=[]
    for split in ['train','test']:
        lines=(ROOT/f'training/{split}/{split}.txt').read_text().splitlines();corpora.append(set(lines));counts={}
        with (ROOT/f'training/{split}-annotations.csv').open() as f:
            for r in csv.DictReader(f):
                span=lines[int(r['Line'])][int(r['Begin Offset']):int(r['End Offset'])]
                assert span and '\n' not in span;counts[r['Type']]=counts.get(r['Type'],0)+1
        assert all(v>=25 for v in counts.values())
    assert not corpora[0]&corpora[1]

def test_template_every_business_route_authorized():
    t=json.loads((ROOT/'template.json').read_text());auth=t['Resources']['Api']['Properties']['Auth']
    assert auth['DefaultAuthorizer']=='Cognito'
    assert not auth['AddDefaultAuthorizerToCorsPreflight']

def test_full_docx_intake_pins_version(app):
    job(app);key='uploads/resumes/J1/D1/document.docx'
    version=app.S3.put_object(Bucket=os.environ['DATA'],Key=key,Body=(ROOT/'samples/resumes/graduate-software.docx').read_bytes())['VersionId']
    app.put('DOCS',{'doc_id':'D1','job_id':'J1','kind':'resume','state':'UPLOAD_PENDING','extension':'docx','key':key,'attempt':0})
    event={'Records':[{'s3':{'bucket':{'name':os.environ['DATA']},'object':{'key':key,'versionId':version}}}]}
    app.intake_one(event);d=app.get('DOCS',{'doc_id':'D1'});assert d['state']=='NLP_PENDING' and d['s3_version']==version
    newer=app.S3.put_object(Bucket=os.environ['DATA'],Key=key,Body=b'changed file')['VersionId']
    event['Records'][0]['s3']['object']['versionId']=newer;app.intake_one(event)
    assert app.get('DOCS',{'doc_id':'D1'})['s3_version']==version

def test_async_custom_job_to_scored_candidate(app,monkeypatch):
    job(app);app.put('CONFIG',{'config_id':'model','recognizer_arn':'arn:aws:comprehend:us-east-1:123456789012:entity-recognizer/tf/version/v1'})
    key='text/D1/document.txt';app.S3.put_object(Bucket=os.environ['DATA'],Key=key,Body=b'Alex alex@example.test\nCloud Engineer\nSkills\nPython AWS\nWork Experience\nJan 2020 - Dec 2025')
    d={'doc_id':'D1','job_id':'J1','kind':'resume','state':'NLP_PENDING','text_key':key,'s3_version':'version-1'};app.put('DOCS',d)
    monkeypatch.setattr(app.NLP,'start_entities_detection_job',lambda **kw:{'JobId':'custom-job'})
    app.start_nlp(d);d=app.get('DOCS',{'doc_id':'D1'});assert d['state']=='NLP_RUNNING'
    monkeypatch.setattr(app.NLP,'describe_entities_detection_job',lambda **kw:{'EntitiesDetectionJobProperties':{'JobStatus':'COMPLETED','OutputDataConfig':{'S3Uri':'s3://unused'}}})
    monkeypatch.setattr(app.NLP,'detect_entities',lambda **kw:{'Entities':[{'Type':'PERSON','Text':'Alex','Score':.99}]})
    custom=[{'Type':'SKILL','Text':'Python','Score':.99},{'Type':'SKILL','Text':'AWS','Score':.99},{'Type':'JOB_TITLE','Text':'Cloud Engineer','Score':.99}]
    monkeypatch.setattr(app,'custom_output',lambda uri:(custom,[{'Entities':custom}]))
    app.nlp_result(d);d=app.get('DOCS',{'doc_id':'D1'});assert d['state']=='PARSED_RESUME' and d['parsed']['model_arn']
    app.enqueue_score(d);messages=app.Q.receive_message(QueueUrl=os.environ['SCORE_QUEUE'])['Messages']
    app.score_one(json.loads(messages[0]['Body']));c=app.get('CANDIDATES',{'doc_id':'D1'})
    assert c['match']['score']==100 and c['decision']=='REVIEW'

def test_stale_deadletter_cannot_fail_new_stage(app):
    app.put('DOCS',{'doc_id':'D1','job_id':'J1','kind':'resume','state':'NLP_RUNNING','attempt':1})
    app.deadletter_one({'Records':[{'s3':{'object':{'key':'uploads/resumes/J1/D1/document.pdf'}}}]})
    assert app.get('DOCS',{'doc_id':'D1'})['state']=='NLP_RUNNING'

def test_ocr_partial_success_requires_review(app,monkeypatch):
    monkeypatch.setattr(app.OCR,'get_document_text_detection',lambda **kw:{'JobStatus':'PARTIAL_SUCCESS','Blocks':[]})
    with pytest.raises(Invalid):app.ocr_result({'ocr_job':'ocr1'})

def test_retry_attempt_requires_failed_state(app):
    doc={'doc_id':'D1','job_id':'J1','kind':'resume','state':'COMPLETE','attempt':0};app.put('DOCS',doc)
    app.intake_one({'doc_id':'D1','retry':True,'attempt':1})
    assert app.get('DOCS',{'doc_id':'D1'})['attempt']==0
