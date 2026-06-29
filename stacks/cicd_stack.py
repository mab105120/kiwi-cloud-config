import typing
from aws_cdk import (
    Stack,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class CiCdStack(Stack):
    def __init__(
        self, scope: Construct, id: str, env_name: str, github_repo: str, **kwargs
    ):
        super().__init__(scope, id, **kwargs)

        # Register GitHub as an OIDC identity provider for this account.
        # This means that JWTs issued from this provider are accepted here.
        oidc_provider = iam.OpenIdConnectProvider(
            self,
            "GitHubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
            # GitHub's OIDC thumbprint (stable — tied to GitHub's root CA, not leaf cert)
            thumbprints=["6938fd4d98bab03faadb97b34396831e3780aea1"],
        )

        principal = iam.FederatedPrincipal(
            oidc_provider.open_id_connect_provider_arn,
            conditions={
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": f"repo:{github_repo}:ref:refs/heads/main"
                    if env_name == "prod"
                    else f"repo:{github_repo}:*",
                },
            },
            assume_role_action="sts:AssumeRoleWithWebIdentity",
        )

        role = iam.Role(
            self,
            "GitHubActionsRole",
            role_name=f"github-actions-kiwi-deploy-{env_name}",
            assumed_by=typing.cast(iam.IPrincipal, principal),
            description=f"Assumed by GitHub Actions to deploy the {env_name} environment",
        )

        # CloudFormation — needed to create/update/delete stacks
        role.add_to_policy(
            iam.PolicyStatement(
                sid="CloudFormation",
                actions=["cloudformation:*"],
                resources=["*"],
            )
        )

        # EC2 — VPC, subnets, route tables, NAT gateways, security groups
        role.add_to_policy(
            iam.PolicyStatement(
                sid="EC2",
                actions=["ec2:*"],
                resources=["*"],
            )
        )

        # RDS — DB instances and subnet groups
        role.add_to_policy(
            iam.PolicyStatement(
                sid="RDS",
                actions=["rds:*"],
                resources=["*"],
            )
        )

        # Secrets Manager — master and app credentials
        role.add_to_policy(
            iam.PolicyStatement(
                sid="SecretsManager",
                actions=[
                    "secretsmanager:CreateSecret",
                    "secretsmanager:DeleteSecret",
                    "secretsmanager:DescribeSecret",
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:PutSecretValue",
                    "secretsmanager:TagResource",
                    "secretsmanager:UpdateSecret",
                ],
                resources=["*"],
            )
        )

        # Lambda — create_db_user custom resource function
        role.add_to_policy(
            iam.PolicyStatement(
                sid="Lambda",
                actions=["lambda:*"],
                resources=["*"],
            )
        )

        # IAM — Lambda execution role created by CDK
        role.add_to_policy(
            iam.PolicyStatement(
                sid="IAM",
                actions=[
                    "iam:CreateRole",
                    "iam:DeleteRole",
                    "iam:AttachRolePolicy",
                    "iam:DetachRolePolicy",
                    "iam:PutRolePolicy",
                    "iam:DeleteRolePolicy",
                    "iam:GetRole",
                    "iam:GetRolePolicy",
                    "iam:PassRole",
                    "iam:TagRole",
                    "iam:UntagRole",
                    "iam:ListRolePolicies",
                    "iam:ListAttachedRolePolicies",
                ],
                resources=["*"],
            )
        )

        # S3 — CDK bootstrap asset bucket
        role.add_to_policy(
            iam.PolicyStatement(
                sid="S3",
                actions=["s3:*"],
                resources=["arn:aws:s3:::cdk-*", "arn:aws:s3:::cdk-*/*"],
            )
        )

        # ECR — CDK bootstrap (Docker-based Lambda bundling)
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ECR",
                actions=["ecr:*"],
                resources=["*"],
            )
        )

        # SSM — CDK bootstrap parameter reads
        role.add_to_policy(
            iam.PolicyStatement(
                sid="SSM",
                actions=["ssm:GetParameter"],
                resources=["arn:aws:ssm:*:*:parameter/cdk-bootstrap/*"],
            )
        )

        # STS — CDK internally assumes the CDK deploy role
        role.add_to_policy(
            iam.PolicyStatement(
                sid="STS",
                actions=["sts:AssumeRole"],
                resources=["arn:aws:iam::*:role/cdk-*"],
            )
        )

        CfnOutput(
            self,
            "GitHubActionsRoleArn",
            value=role.role_arn,
            description="Set this as the AWS_ROLE_ARN secret in GitHub Actions",
        )
