import { spawnSync } from "node:child_process";

const containerName = "agent_rs_pg";
const timeoutMs = 30_000;
const pollIntervalMs = 1_000;
const deadline = Date.now() + timeoutMs;

function readHealthStatus() {
  const result = spawnSync(
    "docker",
    ["inspect", "--format", "{{.State.Health.Status}}", containerName],
    { encoding: "utf8", windowsHide: true },
  );

  if (result.error) {
    throw new Error(`无法执行 docker：${result.error.message}`);
  }

  return {
    status: result.status,
    health: result.stdout.trim(),
    error: result.stderr.trim(),
  };
}

while (Date.now() < deadline) {
  const result = readHealthStatus();
  if (result.status === 0 && result.health === "healthy") {
    console.log(`数据库容器 ${containerName} 已就绪。`);
    process.exit(0);
  }

  await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
}

const finalResult = readHealthStatus();
const detail = finalResult.error || finalResult.health || "容器不存在或未返回健康状态";
console.error(`等待数据库容器 ${containerName} 就绪超时：${detail}`);
process.exit(1);
