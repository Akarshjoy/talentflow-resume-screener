import argparse,json
from pathlib import Path
import boto3
p=argparse.ArgumentParser();p.add_argument('--profile',default='my-account');p.add_argument('--region',default='us-east-1');p.add_argument('--stack',default='talentflow')
s=p.add_subparsers(dest='action',required=True);s.add_parser('configure');u=s.add_parser('recruiter');u.add_argument('--email',required=True)
a=p.parse_args();session=boto3.Session(profile_name=a.profile,region_name=a.region)
o={x['OutputKey']:x['OutputValue'] for x in session.client('cloudformation').describe_stacks(StackName=a.stack)['Stacks'][0]['Outputs']}
if a.action=='configure':
    cfg={'apiUrl':o['ApiUrl'],'clientId':o['ClientId'],'region':o['Region']}
    (Path(__file__).resolve().parents[1]/'frontend/config.js').write_text('window.CONFIG = '+json.dumps(cfg)+';\n')
    print('Frontend configured. Web bucket:',o['WebBucket']);print('Portal:',o['PortalUrl'])
else:
    pool=session.client('cognito-idp');email=a.email.strip().lower()
    try:r=pool.admin_create_user(UserPoolId=o['UserPoolId'],Username=email,UserAttributes=[{'Name':'email','Value':email},{'Name':'email_verified','Value':'true'}],DesiredDeliveryMediums=['EMAIL']);username=r['User']['Username']
    except pool.exceptions.UsernameExistsException:username=email
    pool.admin_add_user_to_group(UserPoolId=o['UserPoolId'],Username=username,GroupName='Recruiter')
    print('Recruiter configured:',email,'\nUse the invitation and change the temporary password. Existing users are not sent a new invitation automatically.')
