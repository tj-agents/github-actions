const tagName = process.env.TAG_NAME;
if (!/^v\d+\.\d+\.\d+$/.test(tagName)) {
  throw new Error("production tags must be vMAJOR.MINOR.PATCH");
}
const repo = {owner: context.repo.owner, repo: context.repo.repo};
const reference = await github.rest.git.getRef({...repo, ref: `tags/${tagName}`});
let target = reference.data.object;
let depth = 0;
while (target.type === "tag") {
  if (++depth > 16) throw new Error("annotated tag nesting exceeds the supported limit");
  const tag = await github.rest.git.getTag({...repo, tag_sha: target.sha});
  target = tag.data.object;
}
if (target.type !== "commit") throw new Error("release tag must resolve to a commit");
if (target.sha !== context.sha) throw new Error("release tag must match the immutable triggering commit");
const runs = await github.rest.actions.listWorkflowRuns({
  ...repo, workflow_id: "ci.yml", branch: "main", event: "push", status: "success", per_page: 1,
});
const run = runs.data.workflow_runs[0];
if (!run || run.head_sha !== target.sha) {
  throw new Error("release commit must be the latest successful ci.yml run on main");
}
let artifactId = "";
if (process.env.REQUIRE_ARTIFACT === "true") {
  const artifacts = await github.paginate(github.rest.actions.listWorkflowRunArtifacts, {...repo, run_id: run.id, per_page: 100});
  const candidates = artifacts.filter(item => item.name === "deployment" && !item.expired);
  if (candidates.length !== 1 || !/^sha256:[a-f0-9]{64}$/.test(candidates[0].digest || "")) {
    throw new Error("the verified run must retain one immutable deployment artifact");
  }
  artifactId = String(candidates[0].id);
}
core.setOutput("source-sha", target.sha);
core.setOutput("source-run-id", String(run.id));
core.setOutput("artifact-id", artifactId);
