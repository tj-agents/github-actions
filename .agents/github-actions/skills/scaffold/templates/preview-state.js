const rawNumber = process.env.PREVIEW_NUMBER || "";
if (rawNumber === "") {
  core.setOutput("closed", "false");
  core.setOutput("default-branch", "");
  return;
}
if (!/^[1-9]\d*$/.test(rawNumber) || !Number.isSafeInteger(Number(rawNumber))) {
  throw new Error("preview number must be a positive safe integer");
}
const repo = {owner: context.repo.owner, repo: context.repo.repo};
const expectedRepository = `${repo.owner}/${repo.repo}`.toLowerCase();
const number = Number(rawNumber);
const response = await github.rest.pulls.get({...repo, pull_number: number});
const pull = response.data;
if (pull.number !== number || pull.base?.repo?.full_name?.toLowerCase() !== expectedRepository ||
    pull.head?.repo?.full_name?.toLowerCase() !== expectedRepository) {
  throw new Error("preview operations require a trusted same-repository pull request");
}
if (pull.state !== "open" && pull.state !== "closed") {
  throw new Error("preview pull request state is invalid");
}
let defaultBranch = "";
if (pull.state === "closed") {
  const repository = await github.rest.repos.get(repo);
  if (repository.data.full_name?.toLowerCase() !== expectedRepository ||
      typeof repository.data.default_branch !== "string" || !repository.data.default_branch.trim()) {
    throw new Error("closed preview cleanup requires the trusted repository default branch");
  }
  defaultBranch = repository.data.default_branch;
}
core.setOutput("closed", String(pull.state === "closed"));
core.setOutput("default-branch", defaultBranch);
