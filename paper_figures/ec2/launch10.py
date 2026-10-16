import boto3
S = "C:/Users/MOHITH/AppData/Local/Temp/claude/C--Users-MOHITH-Desktop-major-project/d04a649d-80ad-4626-8afc-2aaa92b3083e/scratchpad"
B, R = "fedgrid-weightsbucket-kwh3ffbpsq5a", "ap-south-1"
s3, ssm = boto3.client("s3", region_name=R), boto3.client("ssm", region_name=R)
s3.upload_file(f"{S}/experiments10.tar.gz", B, "deploy/experiments10.tar.gz")
s3.upload_file(f"{S}/run_all10.sh", B, "deploy/run_all10.sh")
jobs = {
    "i-0b31d377eaacd6ca5": "agent_ton:0 agent_unsw:0 lora_r4:123 full:123 median:123 lora_r8:123",
    "i-02f3503e21b9f5efb": "agent_ton:1 agent_unsw:1 lora_r4:456 full:456 median:456 lora_r8:456",
    "i-02336b4f5de7011ac": "agent_ton:2 agent_unsw:2 lora_r4:789 full:789 median:789 lora_r8:789",
    "i-0ec77ce0efffbba45": "baseline:0 baseline:1 baseline:2",
}
for i, j in jobs.items():
    c = ssm.send_command(InstanceIds=[i], DocumentName="AWS-RunShellScript", Parameters={"commands": [
        f"aws s3 cp s3://{B}/deploy/run_all10.sh /opt/fedgrid/run_all10.sh --region {R} --quiet",
        f"nohup bash /opt/fedgrid/run_all10.sh {j} > /opt/fedgrid/run10.out 2>&1 &", "echo launched"]})
    print(i, c["Command"]["CommandId"])
