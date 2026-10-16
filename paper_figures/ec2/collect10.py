import boto3, time
# SSM truncates stdout at 24,000 chars -> read the concatenated logs in 20 KB chunks
ssm = boto3.client("ssm", region_name="ap-south-1")
ids = ["i-0b31d377eaacd6ca5", "i-02f3503e21b9f5efb", "i-02336b4f5de7011ac", "i-0ec77ce0efffbba45"]
out = "C:/Users/MOHITH/Desktop/major project/paper_figures/aws_logs"
LOGS = "/opt/fedgrid/exp10/all.log /opt/fedgrid/exp10/gbm.log /opt/fedgrid/exp10/agent11.log /opt/fedgrid/exp10/curve.log"
CH = 20000


def run(i, cmd):
    c = ssm.send_command(InstanceIds=[i], DocumentName="AWS-RunShellScript", Parameters={"commands": [cmd]})["Command"]["CommandId"]
    time.sleep(2)
    while True:
        r = ssm.get_command_invocation(CommandId=c, InstanceId=i)
        if r["Status"] not in ("Pending", "InProgress"):
            return r["StandardOutputContent"]
        time.sleep(2)


for i in ids:
    n = int(run(i, f"cat {LOGS} 2>/dev/null | wc -c").strip() or 0)
    txt = "".join(run(i, f"cat {LOGS} 2>/dev/null | tail -c +{k + 1} | head -c {CH}") for k in range(0, n, CH))
    assert len(txt.encode()) == n, (i, len(txt.encode()), n)
    open(f"{out}/exp10_{i}.txt", "w", encoding="utf-8", newline="\n").write(txt)
    print(i, n, "bytes | jobs done:", txt.count("### END"), "ALLDONE" in txt, "AGENT11DONE" in txt, "GBMDONE" in txt,
          "CURVEDONE" in txt, "| errors:", txt.count("Traceback") + txt.count("Killed"))
