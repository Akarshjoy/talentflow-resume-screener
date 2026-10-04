import csv, gzip, hashlib, io, json, os, re, tarfile, time, uuid
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import unquote_plus, urlparse
import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from domain import Invalid, require, MAX_UPLOAD, bounded_text, docx_text, parsed, score, safe_csv

DB=boto3.resource('dynamodb'); S3=boto3.client('s3'); Q=boto3.client('sqs')
NLP=boto3.client('comprehend'); OCR=boto3.client('textract'); SES=boto3.client('ses'); TX=boto3.client('dynamodb')
SER=TypeSerializer()

def now(): return datetime.now(timezone.utc).isoformat()
def table(name): return DB.Table(os.environ[name])
def clean(value): return json.loads(json.dumps(value,default=lambda x:(int(x) if x == x.to_integral_value() else float(x)) if isinstance(x,Decimal) else str(x)))
def dbvalue(value): return json.loads(json.dumps(value),parse_float=Decimal)
def enc(value): return {k:SER.serialize(v) for k,v in dbvalue(value).items()}
def put(t,item,**kw): table(t).put_item(Item=dbvalue(item),**kw)
def get(t,key): return clean(table(t).get_item(Key=key,ConsistentRead=True).get('Item',{}))
def query(t,pk,value,index=None):
    args={'KeyConditionExpression':Key(pk).eq(value)}
    if index: args['IndexName']=index
    out=[]
    while True:
        r=table(t).query(**args);out.extend(r['Items'])
        if not r.get('LastEvaluatedKey'):break
        args['ExclusiveStartKey']=r['LastEvaluatedKey']
    return clean(out)
def update(t,key,values,condition=None,extra=None):
    args={'Key':key,'UpdateExpression':'SET '+', '.join(f'#n{i}=:v{i}' for i in range(len(values))),
          'ExpressionAttributeNames':{f'#n{i}':k for i,k in enumerate(values)},
          'ExpressionAttributeValues':{f':v{i}':dbvalue(v) for i,v in enumerate(values.values())}}
    if condition:
        args['ConditionExpression']=condition
        args['ExpressionAttributeValues'].update(dbvalue(extra or {}))
    table(t).update_item(**args)
def state(doc, status, **values):
    update('DOCS',{'doc_id':doc['doc_id']},{'state':status,'updated_at':now(),**values},
           '#n0 = :expected', {':expected': doc['state']})
def send(queue,body): Q.send_message(QueueUrl=os.environ[queue],MessageBody=json.dumps(body))
def audit(job_id,actor,action,details):
    item={'job_id':job_id,'event_id':now()+'#'+str(uuid.uuid4()),'actor':actor,'action':action,'details':details}
    put('AUDIT',item);return item

def result(status,data,content='application/json'):
    return {'statusCode':status,'headers':{'Content-Type':content,'Access-Control-Allow-Origin':os.environ['PORTAL'],
            'Cache-Control':'no-store'},'body':json.dumps(clean(data)) if content=='application/json' else data}

def authenticated(event):
    claims=event.get('requestContext',{}).get('authorizer',{}).get('claims',{})
    groups=claims.get('cognito:groups','')
    if isinstance(groups,str): groups=groups.replace('[','').replace(']','').split(',')
    require(claims.get('sub') and any(str(g).strip()=='Recruiter' for g in groups),'Recruiter access required')
    return claims['sub']

def api(event,context):
    try:
        actor=authenticated(event)
        method=event['httpMethod']; path=event.get('path','').strip('/').split('/')
        raw=event.get('body') or '{}';require(len(raw)<100000,'Request too large');body=json.loads(raw)
        if path==['status'] and method=='GET':
            cfg=get('CONFIG',{'config_id':'model'})
            return result(200,{'model':cfg,'message':'Async ML jobs can take several minutes. Human review is required.'})
        if path==['jobs']:
            if method=='GET': return result(200,query('JOBS','kind','JOB','ByKind'))
            if method=='POST':
                title=str(body.get('title','')).strip();require(2<=len(title)<=150,'Enter a job title')
                j={'job_id':str(uuid.uuid4()),'kind':'JOB','title':title,'status':'AWAITING_JD','created_at':now(),'created_by':actor,'version':1}
                put('JOBS',j);audit(j['job_id'],actor,'CREATE_JOB',{'title':title});return result(201,j)
        require(len(path)>=2 and path[0]=='jobs','Unknown route')
        job=get('JOBS',{'job_id':path[1]});require(job,'Job not found');jid=job['job_id']
        action=path[2] if len(path)>2 else ''
        if method=='GET' and not action:
            return result(200,{'job':job,'documents':query('DOCS','job_id',jid,'ByJob'),
                               'candidates':query('CANDIDATES','job_id',jid,'ByJob')})
        if method=='POST' and action=='uploads':
            kind=body.get('kind');filename=str(body.get('filename',''));ext=filename.rsplit('.',1)[-1].lower()
            require(kind in ('jd','resume') and ext in ('pdf','docx'),'Choose PDF or DOCX and a valid document kind')
            require(0<int(body.get('size',0))<=MAX_UPLOAD,'Maximum upload size is 10 MB')
            require(get('CONFIG',{'config_id':'model'}).get('recognizer_arn'),'Train and connect a custom recognizer first')
            require(kind!='jd' or job['status']=='AWAITING_JD','JD already uploaded; create a new job for revised requirements')
            did=str(uuid.uuid4());key=f"uploads/{'jds' if kind=='jd' else 'resumes'}/{jid}/{did}/document.{ext}"
            if kind=='jd':
                update('JOBS',{'job_id':jid},{'status':'PARSING_JD','jd_doc_id':did},'#n0 = :before',{':before':'AWAITING_JD'})
            doc={'doc_id':did,'job_id':jid,'kind':kind,'key':key,'extension':ext,'filename':filename[:180],
                 'state':'UPLOAD_PENDING','created_at':now(),'updated_at':now(),'attempt':0}
            put('DOCS',doc)
            # Browser can re-request an expired form for this exact document via /documents/{id}/upload.
            return result(201,{'document':doc,'upload':upload_form(doc)})
        if method=='POST' and action=='confirm':
            require(job['status']=='JD_REVIEW','Wait for JD extraction before reviewing requirements')
            skills=body.get('required_skills',[]);titles=body.get('acceptable_titles',[])
            require(isinstance(skills,list) and isinstance(titles,list) and 0<len(skills)<=100 and 0<len(titles)<=30,'Confirm required skills and acceptable titles')
            require(all(isinstance(x,str) and 0<len(x)<=120 for x in skills+titles),'Invalid skills or titles')
            years=float(body.get('minimum_years',0));threshold=float(body.get('threshold',70))
            require(0<=years<=60 and 0<=threshold<=100,'Invalid experience or threshold')
            values={'status':'READY','required_skills':skills,'acceptable_titles':titles,'minimum_years':years,
                    'threshold':threshold,'reviewed_by':actor,'reviewed_at':now()}
            update('JOBS',{'job_id':jid},values,'#n0 = :before',{':before':'JD_REVIEW'})
            audit(jid,actor,'CONFIRM_REQUIREMENTS',values);return result(200,values)
        if method=='GET' and action=='audit': return result(200,query('AUDIT','job_id',jid))
        if method=='GET' and action=='failures': return result(200,query('FAILED','job_id',jid,'ByJob'))
        if method=='GET' and action=='export':
            rows=[c for c in query('CANDIDATES','job_id',jid,'ByJob') if c.get('decision')=='SHORTLISTED']
            return result(200,safe_csv(rows),'text/csv; charset=utf-8')
        if action=='documents' and len(path)==5:
            doc=get('DOCS',{'doc_id':path[3]});require(doc and doc['job_id']==jid,'Document not found')
            operation=path[4]
            if method=='GET' and operation in ('source','evidence'):
                key=doc['key'] if operation=='source' else doc.get('evidence_key')
                require(key,'Evidence not ready')
                args={'Bucket':os.environ['DATA'],'Key':key}
                if operation=='source' and doc.get('s3_version'):args['VersionId']=doc['s3_version']
                return result(200,{'url':S3.generate_presigned_url('get_object',Params=args,ExpiresIn=120)})
            if method=='POST' and operation=='upload':
                require(doc['state']=='UPLOAD_PENDING','Upload already received');return result(200,{'upload':upload_form(doc)})
            if method=='POST' and operation=='retry':
                require(doc['state']=='FAILED','Only failed documents can be retried')
                # send before state mutation: handler owns transition; duplicate delivery is safe.
                send('PARSE_QUEUE',{'doc_id':doc['doc_id'],'retry':True,'attempt':int(doc.get('attempt',0))+1})
                audit(jid,actor,'RETRY_REQUESTED',{'doc_id':doc['doc_id']});return result(202,{'queued':True})
        if action=='candidates' and len(path)==5:
            cid=path[3];candidate=get('CANDIDATES',{'doc_id':cid});require(candidate and candidate['job_id']==jid,'Candidate not found')
            op=path[4]
            if method=='POST' and op=='review':
                require(candidate.get('decision')=='REVIEW','Decision already final; review a new application instead')
                name=str(body.get('name','')).strip();email=str(body.get('email','')).strip()
                require(name and len(name)<=150 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email),'Confirm name and email')
                years=float(body['years_experience']);require(0<=years<=60,'Confirm experience in years')
                skills=body.get('skills',[]);titles=body.get('titles',[]);employers=body.get('employers',[])
                require(isinstance(employers,list) and len(employers)<=80 and all(isinstance(x,str) and 0<len(x)<=150 for x in employers),'Invalid employers')
                require(isinstance(skills,list) and isinstance(titles,list) and len(skills)<=150 and len(titles)<=50,'Invalid lists')
                require(all(isinstance(x,str) and 0<len(x)<=120 for x in skills+titles),'Invalid reviewed entities')
                require(str(body.get('note','')).strip(),'Enter evidence/reason for your review')
                reviewed={**candidate,'name':name,'email':email,'years_experience':years,'skills':skills,'titles':titles,'employers':employers,'review_flags':[]}
                reviewed.update(match=score(reviewed,job),reviewed_by=actor,reviewed_at=now(),review_note=str(body['note'])[:1000])
                reviewed['revision']=int(candidate.get('revision',0))+1
                put('CANDIDATES',reviewed,ConditionExpression='revision = :r AND decision = :d',ExpressionAttributeValues={':r':candidate['revision'],':d':'REVIEW'})
                audit(jid,actor,'REVIEW_CANDIDATE',{'doc_id':cid,'revision':reviewed['revision'],'note':reviewed['review_note'],'before':{k:candidate.get(k) for k in ('name','email','skills','titles','years_experience','employers')},'after':{k:reviewed.get(k) for k in ('name','email','skills','titles','years_experience','employers')}})
                return result(200,reviewed)
            if method=='POST' and op=='decision':
                decision=body.get('decision');reason=str(body.get('reason','')).strip()
                require(decision in ('SHORTLISTED','REJECTED') and reason,'Choose a decision and give a reason')
                if candidate.get('decision')==decision:return result(200,candidate)
                require(candidate.get('decision')=='REVIEW','Decision already final')
                require(candidate.get('reviewed_by'),'Review source, identity, skills and experience before deciding')
                invitation=str(body.get('interview_details','')).strip()
                if decision=='SHORTLISTED':
                    require(body.get('confirm_send') is True and 10<=len(invitation)<=3000,'Confirm sending and enter interview scheduling details')
                stamp=now(); audit_item={'job_id':jid,'event_id':stamp+'#'+str(uuid.uuid4()),'actor':actor,'action':'DECISION',
                                       'details':{'doc_id':cid,'decision':decision,'reason':reason[:1000],'match':candidate['match']}}
                actions=[{'Update':{'TableName':os.environ['CANDIDATES'],'Key':enc({'doc_id':cid}),
                    'UpdateExpression':'SET decision=:new, decision_reason=:reason, decided_by=:actor, decided_at=:at',
                    'ConditionExpression':'decision=:old AND revision=:rev',
                    'ExpressionAttributeValues':enc({':new':decision,':reason':reason[:1000],':actor':actor,':at':stamp,':old':'REVIEW',':rev':candidate['revision']})}},
                    {'Put':{'TableName':os.environ['AUDIT'],'Item':enc(audit_item)}}]
                if decision=='SHORTLISTED':
                    actions.append({'Put':{'TableName':os.environ['MAIL'],'Item':enc({'mail_id':cid,'state':'PENDING','to':candidate['email'],
                        'job_id':jid,'subject':'Interview invitation: '+job['title'], 'body':f"Hello {candidate['name']},\n\n{invitation}\n\nRecruitment team",'created_at':stamp}),
                        'ConditionExpression':'attribute_not_exists(mail_id)'}})
                TX.transact_write_items(TransactItems=actions)
                return result(200,{'decision':decision,'email_status':'PENDING' if decision=='SHORTLISTED' else 'NOT_REQUESTED'})
        if action=='mail' and method=='GET':return result(200,query('MAIL','job_id',jid,'ByJob'))
        return result(404,{'error':'Unknown route'})
    except Invalid as e:return result(400,{'error':str(e)})
    except (KeyError,ValueError,TypeError,json.JSONDecodeError):return result(400,{'error':'Invalid input'})
    except ClientError as e:
        code=e.response['Error']['Code'];print(json.dumps({'event':'api_error','code':code}))
        if code in ('ConditionalCheckFailedException','TransactionCanceledException'):return result(409,{'error':'Record changed or operation already completed. Refresh.'})
        return result(500,{'error':'AWS operation failed. Inspect API logs.'})

def upload_form(doc):
    mime='application/pdf' if doc['extension']=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    return S3.generate_presigned_post(os.environ['DATA'],doc['key'],Fields={'Content-Type':mime},
        Conditions=[{'Content-Type':mime},['content-length-range',1,MAX_UPLOAD]],ExpiresIn=600)

def object_json(key,value):
    S3.put_object(Bucket=os.environ['DATA'],Key=key,Body=json.dumps(clean(value)).encode(),ContentType='application/json')

def failed(doc,stage,error):
    message=str(error)[:1200]
    item={'failure_id':hashlib.sha256((doc['doc_id']+stage+str(doc.get('attempt',0))).encode()).hexdigest(),
          'job_id':doc['job_id'],'doc_id':doc['doc_id'],'stage':stage,'error':message,'created_at':now()}
    put('FAILED',item);state(doc,'FAILED',last_error=message)
    if doc['kind']=='jd':update('JOBS',{'job_id':doc['job_id']},{'status':'JD_FAILED'})
    print(json.dumps({'event':'pipeline_failure','doc_id':doc['doc_id'],'stage':stage}))

def intake_one(body):
    if body.get('Event')=='s3:TestEvent':return
    if 'Records' in body:
        for record in body['Records']:
            s=record['s3'];key=unquote_plus(s['object']['key']);parts=key.split('/')
            if len(parts)!=5 or parts[0]!='uploads':continue
            doc=get('DOCS',{'doc_id':parts[3]})
            if not doc or doc['key']!=key or s['bucket']['name']!=os.environ['DATA']:continue
            version=s['object'].get('versionId');require(version,'Versioned upload required')
            if doc['state']=='UPLOAD_PENDING':
                try:update('DOCS',{'doc_id':doc['doc_id']},{'state':'VALIDATING','s3_version':version},'#n0 = :old',{':old':'UPLOAD_PENDING'})
                except ClientError as e:
                    if e.response['Error']['Code']!='ConditionalCheckFailedException':raise
            process_upload(get('DOCS',{'doc_id':doc['doc_id']}))
    else:
        doc=get('DOCS',{'doc_id':body['doc_id']})
        if body.get('retry') and doc.get('state')=='FAILED':
            state(doc,'VALIDATING',attempt=int(body['attempt']),last_error='')
            doc=get('DOCS',{'doc_id':doc['doc_id']})
        process_upload(doc)

def process_upload(doc):
    if doc.get('state')!='VALIDATING':return
    args={'Bucket':os.environ['DATA'],'Key':doc['key'],'VersionId':doc['s3_version']}
    meta=S3.head_object(**args);require(0<meta['ContentLength']<=MAX_UPLOAD,'Invalid upload size')
    if doc['extension']=='pdf':
        require(S3.get_object(**args,Range='bytes=0-4')['Body'].read()==b'%PDF-','File is not a PDF')
        token=hashlib.sha256((doc['doc_id']+doc['s3_version']+str(doc.get('attempt',0))).encode()).hexdigest()
        r=OCR.start_document_text_detection(DocumentLocation={'S3Object':{'Bucket':os.environ['DATA'],'Name':doc['key'],'Version':doc['s3_version']}},ClientRequestToken=token)
        state(doc,'OCR_RUNNING',ocr_job=r['JobId'],started_at=int(time.time()))
    else:
        text=docx_text(S3.get_object(**args)['Body'].read());save_text(doc,text)

def save_text(doc,text):
    text=bounded_text(text);key=f"text/{doc['doc_id']}/document.txt"
    S3.put_object(Bucket=os.environ['DATA'],Key=key,Body=text.encode(),ContentType='text/plain; charset=utf-8')
    state(doc,'NLP_PENDING',text_key=key,updated_at=now())

def batch(event,handler):
    errors=[]
    for record in event.get('Records',[]):
        try:handler(json.loads(record['body']))
        except Exception as e:
            print(json.dumps({'event':'queue_retry','type':type(e).__name__,'error':str(e)[:700]}))
            errors.append({'itemIdentifier':record['messageId']})
    return {'batchItemFailures':errors}
def intake(event,context):return batch(event,intake_one)

def ocr_result(doc):
    r=OCR.get_document_text_detection(JobId=doc['ocr_job'])
    if r['JobStatus']=='IN_PROGRESS':return
    require(r['JobStatus']=='SUCCEEDED','Textract failed or returned partial results; review source file')
    require(r.get('DocumentMetadata',{}).get('Pages',1)<=30,'Maximum 30 pages per document')
    blocks=r.get('Blocks',[])
    while r.get('NextToken'):
        r=OCR.get_document_text_detection(JobId=doc['ocr_job'],NextToken=r['NextToken']);blocks.extend(r.get('Blocks',[]))
    object_json(f"evidence/{doc['doc_id']}/textract.json",{'Blocks':blocks})
    low=sum(1 for b in blocks if b['BlockType']=='LINE' and b.get('Confidence',100)<80)
    update('DOCS',{'doc_id':doc['doc_id']},{'ocr_low_confidence_lines':low})
    save_text(doc,'\n'.join(b['Text'] for b in blocks if b['BlockType']=='LINE'))

def start_nlp(doc):
    cfg=get('CONFIG',{'config_id':'model'});arn=cfg.get('recognizer_arn')
    require(arn,'No recognizer configured; connect a trained model then retry')
    token=hashlib.sha256((doc['doc_id']+arn+str(doc.get('attempt',0))).encode()).hexdigest()
    r=NLP.start_entities_detection_job(JobName='tf-'+token[:40],ClientRequestToken=token,LanguageCode='en',
        EntityRecognizerArn=arn,DataAccessRoleArn=os.environ['NLP_ROLE'],
        InputDataConfig={'S3Uri':f"s3://{os.environ['DATA']}/{doc['text_key']}",'InputFormat':'ONE_DOC_PER_FILE'},
        OutputDataConfig={'S3Uri':f"s3://{os.environ['DATA']}/nlp-output/{doc['doc_id']}/"})
    state(doc,'NLP_RUNNING',nlp_job=r['JobId'],model_arn=arn,started_at=int(time.time()))

def custom_output(uri):
    u=urlparse(uri);require(u.netloc==os.environ['DATA'],'Unexpected NLP output bucket')
    blob=S3.get_object(Bucket=u.netloc,Key=u.path.lstrip('/'))['Body'].read()
    rows=[]
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        require(sum(m.size for m in archive.getmembers())<10*1024*1024,'NLP output too large')
        for m in archive.getmembers():
            if m.isfile():
                for line in archive.extractfile(m).read().decode().splitlines():
                    if line.strip():rows.append(json.loads(line))
    require(rows,'Empty Comprehend output')
    require(not any(r.get('ErrorCode') or r.get('ErrorMessage') for r in rows),'Custom extraction returned an error')
    entities=[e for row in rows for e in row.get('Entities',[])]
    return entities,rows

def nlp_result(doc):
    props=NLP.describe_entities_detection_job(JobId=doc['nlp_job'])['EntitiesDetectionJobProperties']
    if props['JobStatus'] in ('SUBMITTED','IN_PROGRESS'):return
    require(props['JobStatus']=='COMPLETED','Custom entity job failed: '+props.get('Message','unknown'))
    text=S3.get_object(Bucket=os.environ['DATA'],Key=doc['text_key'])['Body'].read().decode()
    general=NLP.detect_entities(Text=text,LanguageCode='en')['Entities']
    custom,raw=custom_output(props['OutputDataConfig']['S3Uri'])
    value=parsed(text,general,custom,doc['model_arn'])
    if doc.get('ocr_low_confidence_lines',0):value['review_flags'].append('Low-confidence OCR lines; review PDF source')
    key=f"evidence/{doc['doc_id']}/entities.json"
    object_json(key,{'general':general,'custom':raw,'parsed':value,'source_version':doc['s3_version'],'generated_at':now()})
    if doc['kind']=='jd':
        try:
            update('JOBS',{'job_id':doc['job_id']},{'status':'JD_REVIEW','extracted':value,'jd_evidence_key':key},'attribute_not_exists(reviewed_at)')
        except ClientError as e:
            if e.response['Error']['Code']!='ConditionalCheckFailedException':raise
        state(doc,'COMPLETE',parsed=value,evidence_key=key)
    else:state(doc,'PARSED_RESUME',parsed=value,evidence_key=key)

def enqueue_score(doc):
    if get('JOBS',{'job_id':doc['job_id']}).get('status')!='READY':return
    send('SCORE_QUEUE',{'doc_id':doc['doc_id']})
    try:update('DOCS',{'doc_id':doc['doc_id']},{'state':'SCORE_QUEUED'},'#n0 = :old',{':old':'PARSED_RESUME'})
    except ClientError as e:
        if e.response['Error']['Code']!='ConditionalCheckFailedException':raise

def score_one(body):
    doc=get('DOCS',{'doc_id':body['doc_id']});require(doc and doc.get('parsed'),'Parsed document missing')
    job=get('JOBS',{'job_id':doc['job_id']});require(job.get('status')=='READY','JD requirements are not confirmed')
    row={**doc['parsed'],'doc_id':doc['doc_id'],'job_id':doc['job_id'],'original_extraction':doc['parsed'],
         'evidence_key':doc['evidence_key'],'match':score(doc['parsed'],job),'decision':'REVIEW','revision':0,'created_at':now()}
    try:put('CANDIDATES',row,ConditionExpression='attribute_not_exists(doc_id)')
    except ClientError as e:
        if e.response['Error']['Code']!='ConditionalCheckFailedException':raise
    state(doc,'COMPLETE')
def scoring(event,context):return batch(event,score_one)

def poll(event,context):
    # Reserved concurrency 1 avoids overlapping dispatchers. Each state query is paginated.
    count=0
    for status,handler in [('OCR_RUNNING',ocr_result),('NLP_RUNNING',nlp_result),('NLP_PENDING',start_nlp),('PARSED_RESUME',enqueue_score)]:
        for doc in query('DOCS','state',status,'ByState'):
            if context and context.get_remaining_time_in_millis()<20000:return
            if status=='NLP_PENDING' and count>=2:break
            if status in ('OCR_RUNNING','NLP_RUNNING') and time.time()-doc.get('started_at',time.time())>86400:
                failed(doc,status,'Processing exceeded 24 hours; inspect service job before retrying');continue
            try:
                handler(doc)
                if status=='NLP_PENDING':count+=1
            except ClientError as e:
                code=e.response['Error']['Code']
                if code in ('ConditionalCheckFailedException','TooManyRequestsException','ThrottlingException','ProvisionedThroughputExceededException','InternalServerError','InternalServerException','ServiceUnavailableException'):continue
                failed(doc,status,code+': '+e.response['Error'].get('Message',''))
            except Exception as e:failed(doc,status,str(e))

def deadletter_one(body):
    ids=[body['doc_id']] if body.get('doc_id') else [unquote_plus(r['s3']['object']['key']).split('/')[3] for r in body.get('Records',[]) if r.get('s3')]
    for did in ids:
        doc=get('DOCS',{'doc_id':did})
        expected = ('VALIDATING',) if 'Records' in body or body.get('retry') else ('PARSED_RESUME','SCORE_QUEUED')
        same_attempt = not body.get('retry') or int(body.get('attempt',-1)) == int(doc.get('attempt',0))
        if doc and doc['state'] in expected and same_attempt:
            failed(doc,'QUEUE_EXHAUSTED','Processing retries exhausted. Inspect Intake/Scoring CloudWatch logs; fix cause and retry from dashboard.')
def deadletter(event,context):return batch(event,deadletter_one)

def mailer(event,context):
    # Transactional outbox prevents lost intent; SES delivery is at-least-once, not exactly-once.
    for item in query('MAIL','state','PENDING','ByState')[:30]:
        try:
            r=SES.send_email(Source=os.environ['SENDER'],Destination={'ToAddresses':[item['to']]},Message={
                'Subject':{'Data':item['subject']},'Body':{'Text':{'Data':item['body']}}})
            update('MAIL',{'mail_id':item['mail_id']},{'state':'SENT','ses_message_id':r['MessageId'],'sent_at':now()})
        except ClientError as e:
            update('MAIL',{'mail_id':item['mail_id']},{'last_error':e.response['Error']['Code'],'last_attempt':now()})
            print(json.dumps({'event':'mail_failed','mail_id':item['mail_id'],'code':e.response['Error']['Code']}))
