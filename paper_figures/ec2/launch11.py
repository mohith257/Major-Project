import boto3
S = "C:/Users/MOHITH/AppData/Local/Temp/claude/C--Users-MOHITH-Desktop-major-project/7a4a991d-4117-41d4-b560-72b6bf07b60c/scratchpad"
B, R = "fedgrid-weightsbucket-kwh3ffbpsq5a", "ap-south-1"
s3, ssm = boto3.client("s3", region_name=R), boto3.client("ssm", region_name=R)
s3.upload_file(f"{S}/experiments11.tar.gz", B, "deploy/experiments11.tar.gz")
s3.upload_file("C:/Users/MOHITH/Desktop/major project/paper_figures/ec2/run_all11.sh", B, "deploy/run_all11.sh")
# exp11: does federation separate Fuzzers better with more Fuzzers clients / longer local training?
jobs = {
    "i-0b31d377eaacd6ca5": "lora_r4:123 spread2:123 spread3:123 long:123",
    "i-02f3503e21b9f5efb": "lora_r4:456 spread2:456 spread3:456 long:456",
    "i-02336b4f5de7011ac": "lora_r4:789 spread2:789 spread3:789 long:789",
    "i-0ec77ce0efffbba45": "spread3_long:123 spread3_long:456 spread3_long:789",
}
for i, j in jobs.items():
    c = ssm.send_command(InstanceIds=[i], DocumentName="AWS-RunShellScript", Parameters={"commands": [
        f"aws s3 cp s3://{B}/deploy/run_all11.sh /opt/fedgrid/run_all11.sh --region {R} --quiet",
        f"nohup bash /opt/fedgrid/run_all11.sh {j} > /opt/fedgrid/run11.out 2>&1 &", "echo launched"]})
    print(i, c["Command"]["CommandId"])
