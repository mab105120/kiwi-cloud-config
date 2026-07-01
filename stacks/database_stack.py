import typing
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    BundlingOptions,
    aws_secretsmanager as secretsmanager,
    aws_ec2 as ec2,
    aws_rds as rds,
    CfnOutput,
    aws_lambda as lambda_,
    custom_resources as cr,
    CustomResource,
)
from constructs import Construct


class DatabaseStack(Stack):
    def __init__(
        self,
        scope: Construct,
        id: str,
        env_name: str,
        env_config: dict,
        vpc: ec2.Vpc,
        db_security_group: ec2.SecurityGroup,
        lambda_security_group: ec2.SecurityGroup,
        **kwargs,
    ):
        super().__init__(scope, id, **kwargs)

        self.db_secret = secretsmanager.Secret(
            self,
            "MasterDbSecret",
            secret_name=f"{env_name}/kiwi/db-master-credentials",
            description="MySQL Database credentials for master",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "admin"}',
                generate_string_key="password",
                exclude_characters="\"@/\\ '",
                password_length=32,
            ),
        )

        self.db_appuser_secret = secretsmanager.Secret(
            self,
            "AppUserDbSecret",
            secret_name=f"{env_name}/kiwi/db-appuser-credentials",
            description="MySQL database credentials for app user",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username": "kiwidbuser"}',
                generate_string_key="password",
                exclude_characters="\"@/\\ '",
                password_length=32,
            ),
        )

        subnet_group = rds.SubnetGroup(
            self,
            "DbSubnetGroup",
            subnet_group_name=f"{env_name}-db-subnet-group",
            description=f"{env_name} database subnet group",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
        )

        parameter_group = rds.ParameterGroup(
            self,
            "DbParameterGroup",
            engine=rds.DatabaseInstanceEngine.mysql(
                version=rds.MysqlEngineVersion.VER_8_0_35
            ),
            description=f"{env_name} database parameter group",
            parameters={
                "character_set_server": "utf8mb4",
                "collation_server": "utf8mb4_unicode_ci",
            },
        )

        self.instance = rds.DatabaseInstance(
            self,
            "RdsInstance",
            vpc=vpc,
            subnet_group=subnet_group,
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO
            ),
            engine=rds.DatabaseInstanceEngine.mysql(
                version=rds.MysqlEngineVersion.VER_8_4_8
            ),
            credentials=rds.Credentials.from_secret(
                typing.cast(secretsmanager.ISecret, self.db_secret)
            ),
            database_name=env_config["db_name"],
            security_groups=[db_security_group],
            parameter_group=parameter_group,
            publicly_accessible=False,
            multi_az=False,
            backup_retention=Duration.days(1),
            preferred_backup_window="02:00-03:00",
            preferred_maintenance_window="Mon:03:00-Mon:04:00",
            auto_minor_version_upgrade=True,
            # storage settings
            allocated_storage=20,
            max_allocated_storage=20,
            storage_encrypted=True,
            removal_policy=RemovalPolicy.DESTROY,
            delete_automated_backups=True,
        )

        create_user_fn = lambda_.Function(
            self,
            "CreateDbUserFn",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_asset(
                "lambda/create_db_user",
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -au . /asset-output",
                    ],
                ),
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[lambda_security_group],
            timeout=Duration.minutes(2),
            environment={
                "DB_ENDPOINT": self.instance.db_instance_endpoint_address,
                "DB_NAME": env_config["db_name"],
                "MASTER_SECRET_ARN": self.db_secret.secret_arn,
                "APP_SECRET_ARN": self.db_appuser_secret.secret_arn,
            },
        )

        self.db_secret.grant_read(create_user_fn)
        self.db_appuser_secret.grant_read(create_user_fn)

        # PICK UP FROM HERE

        # create a provider to orchestrate the call with cloud formation
        provider = cr.Provider(
            self,
            "CreateDbUserProvider",
            on_event_handler=typing.cast(lambda_.IFunction, create_user_fn),
        )
        # next create the custom resource that CloudFormation will deploy which in turns triggers the lambda code by calling the provider.service_token url.

        create_user_resource = CustomResource(
            self, "CreateDbUserCustomResource", service_token=provider.service_token
        )

        create_user_resource.node.add_dependency(self.instance)

        CfnOutput(
            self,
            "InstanceEndpoint",
            value=self.instance.db_instance_endpoint_address,
            description="Database endpoint",
        )
        CfnOutput(
            self,
            "InstancePort",
            value=self.instance.db_instance_endpoint_port,
            description="Database port",
        )
        CfnOutput(self, "InstanceIdentifier", value=self.instance.instance_identifier)
        CfnOutput(
            self,
            "MasterDbSecretArn",
            value=self.db_secret.secret_arn,
            description="ARN of the DB master credential secret",
        )
        CfnOutput(
            self,
            "AppUserDbSecretArn",
            value=self.db_appuser_secret.secret_arn,
            description="ARN of the DB user credential secret",
        )
