import argparse,json,time,uuid
from pathlib import Path
import boto3
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description='Asynchronous custom entity training. Training and inference incur AWS charges; no persistent endpoint is created.')
p.add_argument('--profile',default='my-account');p.add_argument('--region',default='us-east-1');p.add_argument('--stack',default='talentflow')
s=p.add_subparsers(dest='action',required=True);s.add_parser('start');status=s.add_parser('status');status.add_argument('--model-arn',required=True)
act=s.add_parser('activate');act.add_argument('--model-arn',required=True);act.add_argument('--accept-demo-model',action='store_true')
a=p.parse_args();session=boto3.Session(profile_name=a.profile,region_name=a.region);nlp=session.client('comprehend')
o={v['OutputKey']:v['OutputValue'] for v in session.client('cloudformation').describe_stacks(StackName=a.stack)['Stacks'][0]['Outputs']}
if a.action=='start':
    for path in ['train/train.txt','test/test.txt','train-annotations.csv','test-annotations.csv']:
        f=ROOT/'training'/path
        if not f.exists():raise SystemExit('Run python scripts/make_training.py first')
        session.client('s3').upload_file(str(f),o['DataBucket'],'training/'+path)
    base='s3://'+o['DataBucket']+'/training/'
    r=nlp.create_entity_recognizer(RecognizerName=a.stack+'-entities',VersionName='v'+str(int(time.time())),LanguageCode='en',DataAccessRoleArn=o['NlpDataRoleArn'],
        InputDataConfig={'DataFormat':'COMPREHEND_CSV','EntityTypes':[{'Type':'SKILL'},{'Type':'JOB_TITLE'}],
         'Documents':{'S3Uri':base+'train/','TestS3Uri':base+'test/','InputFormat':'ONE_DOC_PER_LINE'},
         'Annotations':{'S3Uri':base+'train-annotations.csv','TestS3Uri':base+'test-annotations.csv'}})
    print('Training started. Save this ARN:',r['EntityRecognizerArn'])
    print('Poll with: python scripts/train.py --profile',a.profile,'--stack',a.stack,'status --model-arn ARN')
else:
    props=nlp.describe_entity_recognizer(EntityRecognizerArn=a.model_arn)['EntityRecognizerProperties']
    if a.action=='status':print(json.dumps(props,indent=2,default=str))
    else:
        if props['Status']!='TRAINED':raise SystemExit('Model must be TRAINED. Current status: '+props['Status'])
        if not a.accept_demo_model:raise SystemExit('Review evaluation metrics. For this synthetic demo, explicitly pass --accept-demo-model. Do not use it for real hiring.')
        session.resource('dynamodb').Table(o['ConfigTable']).put_item(Item={'config_id':'model','recognizer_arn':a.model_arn,
            'dataset':'synthetic-demo','use':'human-reviewed demonstration only','activated_at':str(int(time.time()))})
        (ROOT/'docs/model-evaluation.json').write_text(json.dumps(props.get('RecognizerMetadata',{}),indent=2,default=str))
        print('Custom recognizer connected. Evaluation metadata saved in docs/model-evaluation.json. Upload a JD in the portal next.')
