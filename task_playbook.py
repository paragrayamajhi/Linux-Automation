from typing import Any, Callable

TaskExecutor = Callable[[str, int], tuple[int, str, str]]


def task_update_upgrade(host: dict[str, Any], execute: TaskExecutor, timeout: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task": "update_upgrade",
        "status": "passed",
        "stdout": "",
        "stderr": "",
    }

    username = host.get("username", "root")
    if username == "root":
        command = "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get -y upgrade"
    else:
        command = (
            "export DEBIAN_FRONTEND=noninteractive && "
            "sudo -n apt-get update && sudo -n apt-get -y upgrade"
        )

    rc, stdout, stderr = execute(command, timeout)
    result["stdout"] = stdout
    result["stderr"] = stderr
    if rc != 0:
        result["status"] = "failed"
        result["reason"] = "Update and upgrade task failed"
        result["return_code"] = rc

    return result


def task_docker_healthcheck(host: dict[str, Any], execute: TaskExecutor, timeout: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task": "docker_healthcheck",
        "status": "passed",
        "stdout": "",
        "stderr": "",
    }

    check_cmd = "command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}\t{{.Status}}'"
    rc, stdout, stderr = execute(check_cmd, timeout)
    result["stdout"] = stdout
    result["stderr"] = stderr
    if rc != 0:
        result["status"] = "failed"
        result["reason"] = "Docker health check command failed"
        return result

    unhealthy = [
        line
        for line in stdout.splitlines()
        if "unhealthy" in line.lower()
        or "exited" in line.lower()
        or "dead" in line.lower()
        or "restart" in line.lower()
    ]

    if not unhealthy:
        result["details"] = "Docker containers look healthy."
        return result

    restart_cmd = "sudo -n systemctl restart docker"
    rc2, out2, err2 = execute(restart_cmd, timeout)
    result["stdout"] += out2
    result["stderr"] += err2
    if rc2 != 0:
        result["status"] = "failed"
        result["reason"] = "Docker service restart failed"
        return result

    result["details"] = "Unhealthy containers detected; docker service restart."
    return result


def task_system_healthcheck(host: dict[str, Any], execute: TaskExecutor, timeout: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "task": "system_healthcheck",
        "status": "passed",
        "stdout": "",
        "stderr": "",
        "checks": {},
    }

    # 1. CPU Usage %
    rc_cpu, stdout_cpu, stderr_cpu = execute("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1", timeout)
    if rc_cpu == 0 and stdout_cpu.strip():
        try:
            cpu_percent = float(stdout_cpu.strip())
            result["checks"]["cpu_usage"] = f"{cpu_percent:.1f}%"
        except ValueError:
            result["checks"]["cpu_usage"] = "N/A"
    else:
        result["checks"]["cpu_usage"] = "N/A"

    # 2. Memory Usage in GB
    rc_mem, stdout_mem, stderr_mem = execute("free -b | grep Mem | awk '{printf \"%.2f / %.2f\", $3/(1024**3), $2/(1024**3)}'", timeout)
    if rc_mem == 0 and stdout_mem.strip():
        result["checks"]["memory_usage"] = f"{stdout_mem.strip()} GB"
    else:
        result["checks"]["memory_usage"] = "N/A"

    # 3. DNS Request to 192.168.200.50 with timing
    dns_cmd = "( time nslookup google.com 192.168.200.50 2>/dev/null > /dev/null ) 2>&1 | grep real | awk '{print $2}'"
    rc_dns, stdout_dns, stderr_dns = execute(dns_cmd, timeout)
    if rc_dns == 0 and stdout_dns.strip():
        dns_time = stdout_dns.strip()
        # Convert from format like 0m0.XXXs to milliseconds
        try:
            if 'm' in dns_time and 's' in dns_time:
                parts = dns_time.replace('m', ' ').replace('s', ' ').split()
                if len(parts) >= 2:
                    ms = (float(parts[0]) * 60 + float(parts[1])) * 1000
                    result["checks"]["dns_response_time"] = f"{ms:.1f} ms"
            else:
                result["checks"]["dns_response_time"] = dns_time
        except (ValueError, IndexError):
            result["checks"]["dns_response_time"] = "N/A"
        result["checks"]["dns_test"] = "passed"
    else:
        result["checks"]["dns_test"] = "failed"
        result["checks"]["dns_response_time"] = "N/A"

    # 4. Internet Ping Test (5 pings to 1.1.1.1)
    ping_cmd = "ping -c 5 -W 2 1.1.1.1 2>&1"
    rc_ping, stdout_ping, stderr_ping = execute(ping_cmd, timeout)
    
    ping_loss = "N/A"
    ping_latency = "N/A"
    
    if rc_ping == 0 or "packet loss" in stdout_ping:
        # Extract packet loss percentage
        for line in stdout_ping.splitlines():
            if "% packet loss" in line:
                try:
                    loss_pct = line.split('%')[0].split()[-1]
                    ping_loss = f"{loss_pct}%"
                except (IndexError, ValueError):
                    ping_loss = "N/A"
            elif "min/avg/max" in line:
                try:
                    # Format: min/avg/max/mdev = X.XXX/X.XXX/X.XXX/X.XXX ms
                    avg_latency = line.split('avg=')[1].split('/')[0] if 'avg=' in line else line.split('=')[1].split('/')[1]
                    ping_latency = f"{avg_latency} ms"
                except (IndexError, ValueError):
                    ping_latency = "N/A"
        
        result["checks"]["ping_test"] = "passed"
    else:
        result["checks"]["ping_test"] = "failed"
    
    result["checks"]["packet_loss"] = ping_loss
    result["checks"]["latency"] = ping_latency

    # Build detailed output
    output_lines = [
        "=== System Health Check Report ===",
        f"CPU Usage: {result['checks'].get('cpu_usage', 'N/A')}",
        f"Memory: {result['checks'].get('memory_usage', 'N/A')}",
        f"DNS Response Time: {result['checks'].get('dns_response_time', 'N/A')}",
        f"Packet Loss: {result['checks'].get('packet_loss', 'N/A')}",
        f"Network Latency (avg): {result['checks'].get('latency', 'N/A')}",
    ]
    
    result["stdout"] = "\n".join(output_lines)
    result["details"] = "System health check completed"

    return result


TASK_PLAYBOOK: dict[str, Callable[[dict[str, Any], TaskExecutor, int], dict[str, Any]]] = {
    "update_upgrade": task_update_upgrade,
    "docker_healthcheck": task_docker_healthcheck,
    "system_healthcheck": task_system_healthcheck,
}
