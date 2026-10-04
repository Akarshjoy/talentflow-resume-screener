import argparse,json
from pathlib import Path
import boto3
p=argparse.ArgumentParser();p.add_argument('--profile',default='my-account');p.add_argument('--region',default='us-east-1');p.add_argument('--stack',default='talentflow');p.add_argument('--document-ids',nargs='+',required=True)
a=p.parse_args();s=boto3.Session(profile_name=a.profile,region_name=a.region)
o={x['OutputKey']:x['OutputValue'] for x in s.client('cloudformation').describe_stacks(StackName=a.stack)['Stacks'][0]['Outputs']}
folder=Path(__file__).resolve().parents[1]/'docs/live-evidence';folder.mkdir(exist_ok=True)
for did in a.document_ids:
    d=s.resource('dynamodb').Table(o['DocumentsTable']).get_item(Key={'doc_id':did},ConsistentRead=True).get('Item',{})
    if not d.get('evidence_key'):raise SystemExit('Evidence not ready: '+did)
    s.client('s3').download_file(o['DataBucket'],d['evidence_key'],str(folder/(did+'.json')))
    print('Saved real extraction evidence:',did)
print('Review/redact personal data before committing evidence to GitHub.')
