"""Generate an administrator-reviewed deployment-policy starting point; does not attach it."""
import argparse,json
from pathlib import Path
import boto3
p=argparse.ArgumentParser();p.add_argument('--profile',default='my-account');p.add_argument('--region',default='us-east-1');p.add_argument('--stack',default='talentflow');a=p.parse_args()
account=boto3.Session(profile_name=a.profile).client('sts').get_caller_identity()['Account'];region=a.region;stack=a.stack
stm=[]
def allow(actions,resources,**kw):stm.append({'Effect':'Allow','Action':actions,'Resource':resources,**kw})
allow(['cloudformation:*'],[f'arn:aws:cloudformation:{region}:{account}:stack/{stack}*/*',f'arn:aws:cloudformation:{region}:{account}:stack/aws-sam-cli-managed-default/*',f'arn:aws:cloudformation:{region}:{account}:changeSet/*/*', 'arn:aws:cloudformation:us-east-1:aws:transform/Serverless-2016-10-31'])
allow(['cloudformation:ValidateTemplate','cloudformation:GetTemplateSummary','cloudformation:ListStacks'],'*')
for svc,resource in [('dynamodb','table'),('lambda','function'),('sns',''),('sqs',''),('cognito-idp','userpool')]:
    pattern=f'arn:aws:{svc}:{region}:{account}:'+(resource+'/' if resource in ('table','userpool') else resource+':' if resource else '')
    allow([svc+':*'],pattern+('*' if svc=='cognito-idp' else stack+'*'))
allow(['lambda:CreateEventSourceMapping','lambda:ListEventSourceMappings'],'*')
allow(['lambda:GetEventSourceMapping','lambda:UpdateEventSourceMapping','lambda:DeleteEventSourceMapping','lambda:TagResource','lambda:UntagResource','lambda:ListTags'],f'arn:aws:lambda:{region}:{account}:event-source-mapping:*')
allow(['iam:CreateRole','iam:GetRole','iam:DeleteRole','iam:PutRolePolicy','iam:DeleteRolePolicy','iam:GetRolePolicy','iam:AttachRolePolicy','iam:DetachRolePolicy','iam:ListRolePolicies','iam:ListAttachedRolePolicies','iam:TagRole','iam:UntagRole','iam:UpdateAssumeRolePolicy','iam:PassRole'],f'arn:aws:iam::{account}:role/{stack}-*')
allow(['iam:CreateServiceLinkedRole'],'*',Condition={'StringEquals':{'iam:AWSServiceName':'email.cognito-idp.amazonaws.com'}})
allow(['s3:*'],[f'arn:aws:s3:::{stack}-*',f'arn:aws:s3:::{stack}-*/*','arn:aws:s3:::aws-sam-cli-managed-default-*','arn:aws:s3:::aws-sam-cli-managed-default-*/*'])
allow(['s3:ListAllMyBuckets'],'*')
allow(['logs:*'],f'arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{stack}-*')
allow(['events:*'],f'arn:aws:events:{region}:{account}:rule/{stack}-*')
allow(['cloudwatch:PutMetricAlarm','cloudwatch:DeleteAlarms','cloudwatch:DescribeAlarms','cloudwatch:TagResource','cloudwatch:UntagResource','cloudwatch:ListTagsForResource'],'*')
allow(['apigateway:*'],f'arn:aws:apigateway:{region}::*')
allow(['cloudfront:CreateDistribution','cloudfront:CreateDistributionWithTags','cloudfront:GetDistribution','cloudfront:GetDistributionConfig','cloudfront:UpdateDistribution','cloudfront:DeleteDistribution','cloudfront:TagResource','cloudfront:UntagResource','cloudfront:ListTagsForResource','cloudfront:CreateOriginAccessControl','cloudfront:GetOriginAccessControl','cloudfront:UpdateOriginAccessControl','cloudfront:DeleteOriginAccessControl','cloudfront:CreateInvalidation'],'*')
allow(['cognito-idp:CreateUserPool'],'*')
allow(['comprehend:CreateEntityRecognizer','comprehend:DescribeEntityRecognizer','comprehend:ListEntityRecognizers','comprehend:DeleteEntityRecognizer','comprehend:TagResource'],'*')
policy={'Version':'2012-10-17','Statement':stm}
f=Path(__file__).resolve().parents[1]/'deployment-policy.json';f.write_text(json.dumps(policy,indent=2))
print('Created',f,'\nAsk an account administrator to review and attach as a customer-managed policy. Some create/list actions require wildcard scope. Split if account policy-size limits require it. No policy was attached.')
