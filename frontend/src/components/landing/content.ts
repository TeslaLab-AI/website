/**
 * Purpose:
 * Holds TeslaLab landing-page copy in one place.
 *
 * Responsibilities:
 * - Keep product messaging consistent across landing sections.
 * - Avoid fabricated claims, metrics, or customer evidence.
 */

export const productFlowSteps = [
  "Detect",
  "Investigate",
  "Plan",
  "Execute safely",
  "Validate",
  "Pull request",
  "Human review",
] as const;

export const capabilities = [
  { title: "Bugs", detail: "Routine defects that show up in application code." },
  { title: "Dependencies", detail: "Outdated or risky packages that need a controlled update." },
  { title: "Security", detail: "Known vulnerability classes that can be investigated and patched through a PR." },
  { title: "CI failures", detail: "Broken checks that block a healthy delivery path." },
  { title: "Testing", detail: "Gaps and failures in the test suite that should be understood before a change lands." },
] as const;

export const howItWorksSteps = [
  "Connect GitHub",
  "Configure the AI engineer",
  "TeslaLab monitors the repository",
  "Maintenance work is detected",
  "AI investigates and plans",
  "Changes are executed in a controlled environment",
  "Tests, security, and build validation run",
  "A pull request is created",
  "A human reviews the change",
] as const;
