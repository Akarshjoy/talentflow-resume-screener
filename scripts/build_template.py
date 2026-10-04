import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = {}


def ref(x):
    return {"Ref": x}


def sub(x):
    return {"Fn::Sub": x}


def arn(x):
    return {"Fn::GetAtt": [x, "Arn"]}


def add(n, t, p, **kw):
    R[n] = {"Type": t, "Properties": p, **kw}


def allow(a, r, **kw):
    return {"Effect": "Allow", "Action": a, "Resource": r, **kw}


for n, pk, sk, indexes in [
    ("Jobs", "job_id", None, [("ByKind", "kind")]),
    (
        "Documents",
        "doc_id",
        None,
        [("ByJob", "job_id"), ("ByState", "state")],
    ),
    ("Candidates", "doc_id", None, [("ByJob", "job_id")]),
    ("FailedJobs", "failure_id", None, [("ByJob", "job_id")]),
    ("Config", "config_id", None, []),
    ("Audit", "job_id", "event_id", []),
    (
        "Mail",
        "mail_id",
        None,
        [("ByState", "state"), ("ByJob", "job_id")],
    ),
]:
    keys = [{"AttributeName": pk, "KeyType": "HASH"}]

    if sk:
        keys.append({"AttributeName": sk, "KeyType": "RANGE"})

    attrs = sorted(
        set([pk] + ([sk] if sk else []) + [x[1] for x in indexes])
    )

    p = {
        "BillingMode": "PAY_PER_REQUEST",
        "AttributeDefinitions": [
            {"AttributeName": k, "AttributeType": "S"} for k in attrs
        ],
        "KeySchema": keys,
        "SSESpecification": {"SSEEnabled": True},
        "PointInTimeRecoverySpecification": {
            "PointInTimeRecoveryEnabled": True
        },
    }

    if indexes:
        p["GlobalSecondaryIndexes"] = [
            {
                "IndexName": name,
                "KeySchema": [
                    {"AttributeName": key, "KeyType": "HASH"}
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
            for name, key in indexes
        ]

    add(
        n,
        "AWS::DynamoDB::Table",
        p,
        DeletionPolicy="Retain",
        UpdateReplacePolicy="Retain",
    )


add(
    "DeadLetters",
    "AWS::SQS::Queue",
    {
        "MessageRetentionPeriod": 1209600,
        "VisibilityTimeout": 900,
        "SqsManagedSseEnabled": True,
    },
)

for n in ["ParseQueue", "ScoreQueue"]:
    add(
        n,
        "AWS::SQS::Queue",
        {
            "VisibilityTimeout": 900,
            "MessageRetentionPeriod": 345600,
            "SqsManagedSseEnabled": True,
            "RedrivePolicy": {
                "deadLetterTargetArn": arn("DeadLetters"),
                "maxReceiveCount": 4,
            },
        },
    )


data_name = sub(
    "${AWS::StackName}-data-${AWS::AccountId}-${AWS::Region}"
)

data_arn = sub(
    "arn:${AWS::Partition}:s3:::"
    "${AWS::StackName}-data-${AWS::AccountId}-${AWS::Region}"
)

add(
    "UploadQueuePolicy",
    "AWS::SQS::QueuePolicy",
    {
        "Queues": [ref("ParseQueue")],
        "PolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "s3.amazonaws.com"},
                    "Action": "sqs:SendMessage",
                    "Resource": arn("ParseQueue"),
                    "Condition": {
                        "ArnEquals": {"aws:SourceArn": data_arn},
                        "StringEquals": {
                            "aws:SourceAccount": ref("AWS::AccountId")
                        },
                    },
                }
            ],
        },
    },
)


secure = {
    "PublicAccessBlockConfiguration": {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    },
    "BucketEncryption": {
        "ServerSideEncryptionConfiguration": [
            {
                "ServerSideEncryptionByDefault": {
                    "SSEAlgorithm": "AES256"
                }
            }
        ]
    },
}

add(
    "Web",
    "AWS::S3::Bucket",
    secure,
    DeletionPolicy="Retain",
    UpdateReplacePolicy="Retain",
)

add(
    "OAC",
    "AWS::CloudFront::OriginAccessControl",
    {
        "OriginAccessControlConfig": {
            "Name": sub("${AWS::StackName}-oac"),
            "OriginAccessControlOriginType": "s3",
            "SigningBehavior": "always",
            "SigningProtocol": "sigv4",
        }
    },
)

add(
    "CDN",
    "AWS::CloudFront::Distribution",
    {
        "DistributionConfig": {
            "Enabled": True,
            "DefaultRootObject": "index.html",
            "PriceClass": "PriceClass_100",
            "Origins": [
                {
                    "Id": "web",
                    "DomainName": {
                        "Fn::GetAtt": ["Web", "RegionalDomainName"]
                    },
                    "OriginAccessControlId": ref("OAC"),
                    "S3OriginConfig": {"OriginAccessIdentity": ""},
                }
            ],
            "DefaultCacheBehavior": {
                "TargetOriginId": "web",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": ["GET", "HEAD"],
                "ForwardedValues": {"QueryString": False},
                "MinTTL": 0,
                "DefaultTTL": 60,
                "MaxTTL": 300,
                "ResponseHeadersPolicyId": (
                    "67f7725c-6f97-4210-82d7-5512b31e9d03"
                ),
            },
            "ViewerCertificate": {
                "CloudFrontDefaultCertificate": True
            },
        }
    },
)

portal = sub("https://${CDN.DomainName}")

add(
    "Data",
    "AWS::S3::Bucket",
    {
        **secure,
        "BucketName": data_name,
        "VersioningConfiguration": {"Status": "Enabled"},
        "CorsConfiguration": {
            "CorsRules": [
                {
                    "AllowedOrigins": [portal],
                    "AllowedMethods": ["POST"],
                    "AllowedHeaders": ["*"],
                    "MaxAge": 600,
                }
            ]
        },
        "NotificationConfiguration": {
            "QueueConfigurations": [
                {
                    "Event": "s3:ObjectCreated:*",
                    "Queue": arn("ParseQueue"),
                    "Filter": {
                        "S3Key": {
                            "Rules": [
                                {"Name": "prefix", "Value": "uploads/"}
                            ]
                        }
                    },
                }
            ]
        },
    },
    DependsOn="UploadQueuePolicy",
    DeletionPolicy="Retain",
    UpdateReplacePolicy="Retain",
)

for bucket in ["Web", "Data"]:
    stm = [
        {
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:*",
            "Resource": [
                arn(bucket),
                sub("${" + bucket + ".Arn}/*"),
            ],
            "Condition": {"Bool": {"aws:SecureTransport": "false"}},
        }
    ]

    if bucket == "Web":
        stm.append(
            {
                "Effect": "Allow",
                "Principal": {"Service": "cloudfront.amazonaws.com"},
                "Action": "s3:GetObject",
                "Resource": sub("${Web.Arn}/*"),
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": sub(
                            "arn:${AWS::Partition}:cloudfront::"
                            "${AWS::AccountId}:distribution/${CDN}"
                        )
                    }
                },
            }
        )

    add(
        bucket + "Policy",
        "AWS::S3::BucketPolicy",
        {
            "Bucket": ref(bucket),
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": stm,
            },
        },
    )


add(
    "NlpRole",
    "AWS::IAM::Role",
    {
        "AssumeRolePolicyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "comprehend.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "aws:SourceAccount": ref("AWS::AccountId")
                        },
                        "ArnLike": {
                            "aws:SourceArn": sub(
                                "arn:${AWS::Partition}:comprehend:"
                                "${AWS::Region}:${AWS::AccountId}:*"
                            )
                        },
                    },
                }
            ],
        },
        "Policies": [
            {
                "PolicyName": "ModelData",
                "PolicyDocument": {
                    "Version": "2012-10-17",
                    "Statement": [
                        allow(
                            ["s3:GetObject"],
                            [
                                sub("${Data.Arn}/training/*"),
                                sub("${Data.Arn}/text/*"),
                            ],
                        ),
                        allow(
                            ["s3:PutObject"],
                            sub("${Data.Arn}/nlp-output/*"),
                        ),
                        allow(
                            ["s3:ListBucket", "s3:GetBucketLocation"],
                            arn("Data"),
                        ),
                    ],
                },
            }
        ],
    },
)


add(
    "Pool",
    "AWS::Cognito::UserPool",
    {
        "UserPoolName": sub("${AWS::StackName}-recruiters"),
        "UsernameAttributes": ["email"],
        "AutoVerifiedAttributes": ["email"],
        "AdminCreateUserConfig": {
            "AllowAdminCreateUserOnly": True,
            "InviteMessageTemplate": {
                "EmailSubject": "Your TalentFlow recruiter account",
                "EmailMessage": sub(
                    "Username: {username}. Temporary password: {####}. "
                    "Sign in at https://${CDN.DomainName}"
                ),
            },
        },
        "Policies": {
            "PasswordPolicy": {
                "MinimumLength": 12,
                "RequireUppercase": True,
                "RequireLowercase": True,
                "RequireNumbers": True,
                "RequireSymbols": True,
            }
        },
        "EmailConfiguration": {
            "EmailSendingAccount": "DEVELOPER",
            "SourceArn": ref("SESIdentityArn"),
            "From": ref("SenderEmail"),
        },
    },
    DeletionPolicy="Retain",
    UpdateReplacePolicy="Retain",
)

add(
    "Recruiters",
    "AWS::Cognito::UserPoolGroup",
    {
        "UserPoolId": ref("Pool"),
        "GroupName": "Recruiter",
    },
)

add(
    "Client",
    "AWS::Cognito::UserPoolClient",
    {
        "UserPoolId": ref("Pool"),
        "GenerateSecret": False,
        "ExplicitAuthFlows": [
            "ALLOW_USER_PASSWORD_AUTH",
            "ALLOW_REFRESH_TOKEN_AUTH",
        ],
        "PreventUserExistenceErrors": "ENABLED",
        "ReadAttributes": ["email"],
        "WriteAttributes": ["email"],
    },
)

add(
    "Api",
    "AWS::Serverless::Api",
    {
        "StageName": "prod",
        "EndpointConfiguration": {"Type": "REGIONAL"},
        "Cors": {
            "AllowOrigin": sub("'https://${CDN.DomainName}'"),
            "AllowHeaders": "'Content-Type,Authorization'",
            "AllowMethods": "'GET,POST,OPTIONS'",
        },
        "Auth": {
            "DefaultAuthorizer": "Cognito",
            "AddDefaultAuthorizerToCorsPreflight": False,
            "Authorizers": {
                "Cognito": {"UserPoolArn": arn("Pool")}
            },
        },
    },
)


env = {
    k: ref(v)
    for k, v in [
        ("JOBS", "Jobs"),
        ("DOCS", "Documents"),
        ("CANDIDATES", "Candidates"),
        ("FAILED", "FailedJobs"),
        ("CONFIG", "Config"),
        ("AUDIT", "Audit"),
        ("MAIL", "Mail"),
        ("DATA", "Data"),
        ("PARSE_QUEUE", "ParseQueue"),
        ("SCORE_QUEUE", "ScoreQueue"),
        ("SENDER", "SenderEmail"),
    ]
}

env.update(PORTAL=portal, NLP_ROLE=arn("NlpRole"))


def db(names, actions):
    return allow(
        actions,
        [
            item
            for n in names
            for item in [
                arn(n),
                sub("${" + n + ".Arn}/index/*"),
            ]
        ],
    )


reads = ["dynamodb:GetItem", "dynamodb:Query"]

writes = reads + [
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:ConditionCheckItem",
]


def fn(n, handler, policies, events=None, timeout=120, reserved=None):
    add(
        n + "Logs",
        "AWS::Logs::LogGroup",
        {
            "LogGroupName": sub(
                "/aws/lambda/${AWS::StackName}-" + n
            ),
            "RetentionInDays": 14,
        },
    )

    p = {
        "Runtime": "python3.14",
        "CodeUri": "backend/",
        "Handler": "app." + handler,
        "MemorySize": 512,
        "Timeout": timeout,
        "LoggingConfig": {
            "LogGroup": ref(n + "Logs")
        },
        "Environment": {
            "Variables": env
        },
        "Policies": [
            {
                "Version": "2012-10-17",
                "Statement": policies,
            }
        ],
    }

    if events:
        p["Events"] = events

    if reserved:
        p["ReservedConcurrentExecutions"] = reserved

    add(n, "AWS::Serverless::Function", p)


def queue_event(queue):
    return {
        "Queue": {
            "Type": "SQS",
            "Properties": {
                "Queue": arn(queue),
                "BatchSize": 1,
                "FunctionResponseTypes": ["ReportBatchItemFailures"],
                "ScalingConfig": {"MaximumConcurrency": 2},
            },
        }
    }


s3read = allow(
    ["s3:GetObject", "s3:GetObjectVersion"],
    sub("${Data.Arn}/*"),
)

s3write = allow(
    ["s3:PutObject"],
    sub("${Data.Arn}/*"),
)

queuewrite = allow(
    ["sqs:SendMessage"],
    [arn("ParseQueue"), arn("ScoreQueue")],
)


fn(
    "ApiFunction",
    "api",
    [
        db(["Jobs", "Documents", "Candidates", "Audit", "Mail"], writes),
        db(["Config", "FailedJobs"], reads),
        s3read,
        s3write,
        queuewrite,
    ],
    {
        "Proxy": {
            "Type": "Api",
            "Properties": {
                "RestApiId": ref("Api"),
                "Path": "/{proxy+}",
                "Method": "ANY",
            },
        }
    },
    timeout=29,
)

fn(
    "Intake",
    "intake",
    [
        db(["Documents"], writes),
        s3read,
        s3write,
        allow(["textract:StartDocumentTextDetection"], "*"),
    ],
    queue_event("ParseQueue"),
)

fn(
    "Poll",
    "poll",
    [
        db(["Documents", "Jobs", "FailedJobs"], writes),
        db(["Config"], reads),
        s3read,
        s3write,
        queuewrite,
        allow(["textract:GetDocumentTextDetection"], "*"),
        allow(
            [
                "comprehend:DetectEntities",
                "comprehend:StartEntitiesDetectionJob",
                "comprehend:DescribeEntitiesDetectionJob",
            ],
            "*",
        ),
        allow(
            ["iam:PassRole"],
            arn("NlpRole"),
            Condition={
                "StringEquals": {
                    "iam:PassedToService": "comprehend.amazonaws.com"
                }
            },
        ),
    ],
    {
        "Tick": {
            "Type": "Schedule",
            "Properties": {"Schedule": "rate(1 minute)"},
        }
    },
    timeout=120,
    reserved=1,
)

fn(
    "Scoring",
    "scoring",
    [
        db(["Documents", "Candidates"], writes),
        db(["Jobs"], reads),
    ],
    queue_event("ScoreQueue"),
)

fn(
    "Failures",
    "deadletter",
    [
        db(["Documents", "FailedJobs", "Jobs"], writes)
    ],
    queue_event("DeadLetters"),
)

fn(
    "Mailer",
    "mailer",
    [
        db(["Mail"], writes),
        allow(
            ["ses:SendEmail"],
            sub(
                "arn:${AWS::Partition}:ses:${AWS::Region}:"
                "${AWS::AccountId}:identity/*"
            ),
            Condition={
                "StringEquals": {
                    "ses:FromAddress": ref("SenderEmail")
                }
            },
        ),
    ],
    {
        "Tick": {
            "Type": "Schedule",
            "Properties": {"Schedule": "rate(1 minute)"},
        }
    },
    reserved=1,
)


add(
    "Alerts",
    "AWS::SNS::Topic",
    {
        "Subscription": [
            {
                "Protocol": "email",
                "Endpoint": ref("RecruiterEmail"),
            }
        ]
    },
)

for name, metric, namespace, dims in [
    (
        "PollErrors",
        "Errors",
        "AWS/Lambda",
        [{"Name": "FunctionName", "Value": ref("Poll")}],
    ),
    (
        "FailureReview",
        "Invocations",
        "AWS/Lambda",
        [{"Name": "FunctionName", "Value": ref("Failures")}],
    ),
    (
        "MailErrors",
        "Errors",
        "AWS/Lambda",
        [{"Name": "FunctionName", "Value": ref("Mailer")}],
    ),
]:
    add(
        name,
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": namespace,
            "MetricName": metric,
            "Dimensions": dims,
            "Statistic": "Sum",
            "Period": 300,
            "EvaluationPeriods": 1,
            "Threshold": 0,
            "ComparisonOperator": "GreaterThanThreshold",
            "TreatMissingData": "notBreaching",
            "AlarmActions": [ref("Alerts")],
        },
    )

for func, event in [
    ("Poll", "pipeline_failure"),
    ("Mailer", "mail_failed"),
]:
    metric = sub("${AWS::StackName}-" + event)

    add(
        func + "ErrorMetric",
        "AWS::Logs::MetricFilter",
        {
            "LogGroupName": ref(func + "Logs"),
            "FilterPattern": '{ $.event = "' + event + '" }',
            "MetricTransformations": [
                {
                    "MetricNamespace": "TalentFlow",
                    "MetricName": metric,
                    "MetricValue": "1",
                }
            ],
        },
    )

    add(
        func + "BusinessAlarm",
        "AWS::CloudWatch::Alarm",
        {
            "Namespace": "TalentFlow",
            "MetricName": metric,
            "Statistic": "Sum",
            "Period": 300,
            "EvaluationPeriods": 1,
            "Threshold": 0,
            "ComparisonOperator": "GreaterThanThreshold",
            "TreatMissingData": "notBreaching",
            "AlarmActions": [ref("Alerts")],
        },
    )


outputs = {
    "PortalUrl": portal,
    "ApiUrl": sub(
        "https://${Api}.execute-api.${AWS::Region}.amazonaws.com/prod"
    ),
    "Region": ref("AWS::Region"),
    "UserPoolId": ref("Pool"),
    "ClientId": ref("Client"),
    "WebBucket": ref("Web"),
    "DataBucket": ref("Data"),
    "DistributionId": ref("CDN"),
    "ConfigTable": ref("Config"),
    "DocumentsTable": ref("Documents"),
    "CandidatesTable": ref("Candidates"),
    "FailedJobsTable": ref("FailedJobs"),
    "NlpDataRoleArn": arn("NlpRole"),
    "ParseQueueUrl": ref("ParseQueue"),
    "DlqUrl": ref("DeadLetters"),
}

t = {
    "AWSTemplateFormatVersion": "2010-09-09",
    "Transform": "AWS::Serverless-2016-10-31",
    "Description": "TalentFlow: human-reviewed ML recruitment demo",
    "Parameters": {
        "SenderEmail": {"Type": "String"},
        "RecruiterEmail": {"Type": "String"},
        "SESIdentityArn": {"Type": "String"},
    },
    "Resources": R,
    "Outputs": {
        k: {"Value": v}
        for k, v in outputs.items()
    },
}

(ROOT / "template.json").write_text(
    json.dumps(t, indent=2) + "\n"
)

print("Generated template.json")