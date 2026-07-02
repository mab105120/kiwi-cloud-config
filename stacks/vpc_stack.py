from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_iam as iam,
    CfnOutput,
)
from constructs import Construct


class VpcStack(Stack):
    def __init__(self, scope: Construct, id: str, env_name: str, **kwargs):
        super().__init__(scope, id, **kwargs)

        # Create the VPC
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=f"{env_name}-vpc",
            max_azs=2,
            # CIDR block for the whole VPC
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,  # 10.0.0.0/24 10.0.1.0/24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,  # 10.0.2.0/24, 10.0.3.0/24
                ),
            ],
            nat_gateways=1,
        )

        self.db_security_group = ec2.SecurityGroup(
            self,
            "DbSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{env_name}-db-sg",
            description="Controls access to the database",
            allow_all_outbound=False,
        )

        self.lambda_security_group = ec2.SecurityGroup(
            self,
            "LambdaSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"${env_name}-lambda-sg",
            description="Attached to lambda functions that need DB access",
            allow_all_outbound=True,
        )

        self.db_security_group.add_ingress_rule(
            peer=self.lambda_security_group,
            connection=ec2.Port.tcp(3306),
            description="Allow inbound MySQL from Lambda security group",
        )

        self.bastion_security_group = None
        if env_name != "prod":
            self.bastion_security_group = ec2.SecurityGroup(
                self,
                "BastionSecurityGroup",
                vpc=self.vpc,
                security_group_name=f"{env_name}-bastion-sg",
                description="Attached to the SSM bastion instance for developer DB access",
                allow_all_outbound=True,
            )

            self.db_security_group.add_ingress_rule(
                peer=self.bastion_security_group,
                connection=ec2.Port.tcp(3306),
                description="Allow inbound MySQL from bastion security group",
            )

            bastion_role = iam.Role(
                self,
                "BastionRole",
                assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
                managed_policies=[
                    iam.ManagedPolicy.from_aws_managed_policy_name(
                        "AmazonSSMManagedInstanceCore"
                    )
                ],
            )

            bastion = ec2.Instance(
                self,
                "BastionInstance",
                instance_type=ec2.InstanceType.of(
                    ec2.InstanceClass.T3, ec2.InstanceSize.MICRO
                ),
                machine_image=ec2.MachineImage.latest_amazon_linux2023(),
                vpc=self.vpc,
                vpc_subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
                ),
                security_group=self.bastion_security_group,
                role=bastion_role,
            )

            bastion_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["ssm:StartSession"],
                    resources=[
                        f"arn:aws:ec2:{self.region}:{self.account}:instance/{bastion.instance_id}"
                    ],
                )
            )

            CfnOutput(
                self,
                "BastionInstanceId",
                value=bastion.instance_id,
                description="SSM bastion instance ID — use as --target in ssm start-session",
            )

        CfnOutput(self, "VpcId", value=self.vpc.vpc_id, description="VPC ID")
        CfnOutput(
            self,
            "DbSecurityGroupId",
            value=self.db_security_group.security_group_id,
            description="DB security group ID",
        )
        CfnOutput(
            self,
            "LambdaSecurityGroupId",
            value=self.lambda_security_group.security_group_id,
            description="Lambda security group ID",
        )
